"""Single-owner durable operation journal; external effects are never inferred."""

import copy
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


class Journal:
    """Local SQLite state bound to one task, with an exclusive process owner."""

    def __init__(self, path, identity):
        if str(path) == ":memory:":
            raise ValueError("A durable journal requires a filesystem path.")
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._owner = None
        self._acquire()
        try:
            with self._db() as db:
                db.execute("PRAGMA journal_mode=WAL")
                db.executescript("""
                    CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS operations(
                        id TEXT PRIMARY KEY, grant_id TEXT NOT NULL, tool TEXT NOT NULL,
                        arguments TEXT NOT NULL, state TEXT NOT NULL, footprint TEXT NOT NULL,
                        result TEXT, evidence_id TEXT, resources TEXT NOT NULL DEFAULT '{}');
                    CREATE TABLE IF NOT EXISTS events(
                        sequence INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, payload TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS revisions(resource TEXT PRIMARY KEY, revision INTEGER NOT NULL);
                """)
            with self.transaction() as db:
                encoded = canonical(identity)
                row = db.execute("SELECT value FROM metadata WHERE key='identity'").fetchone()
                if row and row[0] != encoded:
                    raise ValueError("Journal task, user request, policy or tool catalog does not match.")
                db.execute("INSERT OR IGNORE INTO metadata VALUES('identity', ?)", (encoded,))
                for row in db.execute("SELECT id FROM operations WHERE state IN ('reserved','dispatched')").fetchall():
                    db.execute("UPDATE operations SET state='unknown' WHERE id=?", (row[0],))
                    self._event(db, "recovered_unknown", {"operation_id": row[0]})
        except BaseException:
            self.close()
            raise

    def _acquire(self):
        import os

        stream = self.path.with_suffix(self.path.suffix + ".lock").open("a+b")
        try:
            stream.seek(0, 2)
            if stream.tell() == 0:
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._owner = stream
        except OSError as exc:
            stream.close()
            raise RuntimeError("Journal already has an active owner.") from exc

    def close(self):
        import os

        if self._owner is None:
            return
        stream, self._owner = self._owner, None
        try:
            stream.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        finally:
            stream.close()

    @contextmanager
    def _db(self):
        if self._owner is None:
            raise RuntimeError("Journal is closed.")
        db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA synchronous=FULL")
        try:
            yield db
        finally:
            db.close()

    @contextmanager
    def transaction(self):
        with self._db() as db:
            try:
                db.execute("BEGIN IMMEDIATE")
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise

    @staticmethod
    def _event(db, kind, payload):
        db.execute("INSERT INTO events(kind,payload) VALUES(?,?)", (kind, canonical(payload)))

    def event(self, kind, payload):
        with self.transaction() as db:
            self._event(db, kind, payload)

    @staticmethod
    def _decode(row):
        if row is None:
            return None
        value = dict(row)
        for key in ("arguments", "footprint", "resources", "result"):
            if value.get(key) is not None:
                value[key] = json.loads(value[key])
        return value

    def operation(self, operation_id):
        with self._db() as db:
            return self._decode(db.execute("SELECT * FROM operations WHERE id=?", (operation_id,)).fetchone())

    @staticmethod
    def _conflict(a, b):
        ar, aw, br, bw = (set(a["reads"]), set(a["writes"]), set(b["reads"]), set(b["writes"]))
        return bool((aw & (br | bw)) or (bw & (ar | aw)))

    def check_conflicts(self, footprint, exclude_operation=None):
        with self._db() as db:
            for row in db.execute(
                "SELECT id,footprint FROM operations WHERE state IN ('reserved','dispatched','unknown')"
            ):
                if row[0] != exclude_operation and self._conflict(footprint, json.loads(row[1])):
                    raise PermissionError(
                        "An uncertain operation conflicts with these resources; host reconciliation required."
                    )

    def reserve(self, operation_id, grant, name, arguments, footprint):
        """Consume budget and persist the exact invocation before any dispatch."""
        with self.transaction() as db:
            old = db.execute("SELECT * FROM operations WHERE id=?", (operation_id,)).fetchone()
            if old and (old["grant_id"], old["tool"], old["arguments"]) != (grant.id, name, canonical(arguments)):
                raise PermissionError("Operation identity was reused for a different invocation.")
            if old and old["state"] != "not_applied":
                return self._decode(old)
            for row in db.execute(
                "SELECT footprint FROM operations WHERE state IN ('reserved','dispatched','unknown')"
            ):
                if self._conflict(footprint, json.loads(row[0])):
                    raise PermissionError(
                        "An uncertain operation conflicts with these resources; host reconciliation required."
                    )
            used = db.execute(
                "SELECT COUNT(*) FROM operations WHERE grant_id=? AND state!='not_applied'", (grant.id,)
            ).fetchone()[0]
            if used >= grant.max_uses:
                raise PermissionError("Action grant execution budget is exhausted.")
            db.execute(
                "INSERT INTO operations(id,grant_id,tool,arguments,state,footprint) VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET state='reserved',footprint=excluded.footprint,result=NULL,evidence_id=NULL,resources='{}'",
                (operation_id, grant.id, name, canonical(arguments), "reserved", canonical(footprint)),
            )
            self._event(db, "reserved", {"operation_id": operation_id, "grant_id": grant.id})
            return self._decode(db.execute("SELECT * FROM operations WHERE id=?", (operation_id,)).fetchone())

    def dispatched(self, operation_id):
        with self.transaction() as db:
            changed = db.execute(
                "UPDATE operations SET state='dispatched' WHERE id=? AND state='reserved'", (operation_id,)
            ).rowcount
            if changed != 1:
                raise PermissionError("Operation cannot enter dispatch from its current state.")
            self._event(db, "dispatched", {"operation_id": operation_id})

    def cancel_reserved(self, operation_id):
        """Release a reservation only while dispatch is proven not to have begun."""
        with self.transaction() as db:
            changed = db.execute(
                "UPDATE operations SET state='not_applied' WHERE id=? AND state='reserved'", (operation_id,)
            ).rowcount
            if changed != 1:
                raise PermissionError("A dispatched reservation cannot be cancelled.")
            self._event(db, "cancelled_before_dispatch", {"operation_id": operation_id})

    def finish(self, operation_id, state, result=None, evidence_id=None, resources=None):
        if state not in {"committed", "unknown"}:
            raise ValueError("Invalid transport outcome.")
        with self.transaction() as db:
            changed = db.execute(
                "UPDATE operations SET state=?,result=?,evidence_id=?,resources=? WHERE id=? AND state='dispatched'",
                (state, canonical(result), evidence_id, canonical(resources or {}), operation_id),
            ).rowcount
            if changed != 1:
                raise PermissionError("Only a dispatched operation can receive a transport outcome.")
            self._event(db, state, {"operation_id": operation_id, "evidence_id": evidence_id})

    def reconcile(self, operation_id, outcome, result=None, evidence_id=None, resources=None):
        if outcome not in {"committed", "not_applied"}:
            raise ValueError("Reconciliation requires an attested committed or not_applied outcome.")
        with self.transaction() as db:
            changed = db.execute(
                "UPDATE operations SET state=?,result=?,evidence_id=?,resources=? WHERE id=? AND state='unknown'",
                (outcome, canonical(result), evidence_id, canonical(resources or {}), operation_id),
            ).rowcount
            if changed != 1:
                raise PermissionError("Only an unknown operation can be reconciled.")
            self._event(db, "host_reconciled", {"operation_id": operation_id, "outcome": outcome})

    def revisions(self, keys):
        with self._db() as db:
            result = {}
            for key in keys:
                row = db.execute("SELECT revision FROM revisions WHERE resource=?", (key,)).fetchone()
                result[key] = row[0] if row else 0
            return result

    def bump(self, keys):
        with self.transaction() as db:
            for key in set(keys):
                db.execute(
                    "INSERT INTO revisions VALUES(?,1) ON CONFLICT(resource) DO UPDATE SET revision=revision+1", (key,)
                )

    def save_evidence(self, state):
        with self.transaction() as db:
            db.execute(
                "INSERT INTO metadata VALUES('evidence',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (canonical(state),),
            )

    def load_evidence(self):
        with self._db() as db:
            row = db.execute("SELECT value FROM metadata WHERE key='evidence'").fetchone()
            return json.loads(row[0]) if row else None

    def snapshot(self):
        with self._db() as db:
            operations = [self._decode(row) for row in db.execute("SELECT * FROM operations ORDER BY rowid")]
            events = [
                dict(sequence=row[0], kind=row[1], **json.loads(row[2]))
                for row in db.execute("SELECT * FROM events ORDER BY sequence")
            ]
        return copy.deepcopy(
            dict(
                operations=operations,
                receipts=[
                    event
                    | dict(
                        outcome=event.get(
                            "outcome", "unknown" if event["kind"] == "recovered_unknown" else event["kind"]
                        )
                    )
                    for event in events
                    if event["kind"] in {"committed", "unknown", "recovered_unknown", "host_reconciled"}
                ],
                events=events,
                unresolved=any(op["state"] in {"reserved", "dispatched", "unknown"} for op in operations),
            )
        )
