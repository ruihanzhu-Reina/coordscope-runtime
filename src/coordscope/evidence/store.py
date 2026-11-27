"""Immutable evidence, resource stamps and durable, host-owned access records."""

import hashlib
import json
from collections.abc import Mapping

from .provenance import ProvenanceGraph, SourceRef, json_snapshot, pointer_value


def text(value):
    def encode(item):
        return item.model_dump(mode="json") if hasattr(item, "model_dump") else str(item)

    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=encode)


class _EntriesView(Mapping):
    """Legacy read interface; retrieved rows cannot mutate stored snapshots."""

    def __init__(self, snapshots):
        self._snapshots = snapshots

    def __getitem__(self, key):
        return json.loads(self._snapshots[key])

    def __iter__(self):
        return iter(self._snapshots)

    def __len__(self):
        return len(self._snapshots)


class EvidenceStore:
    def __init__(self, preview_chars=6000):
        self.preview_chars = preview_chars
        self._snapshots = {}
        self._visible = {"agent_0": set()}
        self.graph = ProvenanceGraph()
        self.journal = None

    def attach_journal(self, journal):
        """Bind to the task ledger before publishing any evidence.

        The journal authenticates task identity and policy before this state is
        loaded. Stored source fields remain data, never execution authority.
        """
        if self.journal is not None or self._snapshots:
            raise ValueError("Evidence journal must be attached before use.")
        state = journal.load_evidence()
        if state:
            self._snapshots = dict(state["snapshots"])
            self._visible = {actor: set(refs) for actor, refs in state["visible"].items()}
            self.graph._nodes = dict(state["nodes"])
            self.graph._events = list(state["events"])
        self.journal = journal

    def _persist(self):
        if self.journal is not None:
            self.journal.save_evidence(
                dict(
                    snapshots=self._snapshots,
                    visible={actor: sorted(refs) for actor, refs in self._visible.items()},
                    nodes=self.graph._nodes,
                    events=self.graph._events,
                )
            )

    @property
    def entries(self):
        return _EntriesView(self._snapshots)

    @property
    def visible(self):
        return {actor: set(refs) for actor, refs in self._visible.items()}

    def _row(self, actor, ref):
        if not isinstance(ref, str) or ref not in self._visible.get(actor, set()):
            raise ValueError("Evidence is outside this agent's visible scope.")
        return json.loads(self._snapshots[ref])

    @staticmethod
    def _metadata(row):
        # Do not duplicate the full payload outside the bounded preview.
        return {key: value for key, value in row.items() if key not in {"content", "value"}}

    def add(self, value, *, tool, arguments, actor, resources=None, success=None, parents=(), parent_ids=()):
        """Host-only tool receipt. Strings stay strings, including JSON text.

        An explicit failure cannot be overridden by success=True. Parent links
        validate source existence/access, never correctness of derived content.
        """
        if not isinstance(tool, str) or not tool or not isinstance(actor, str) or not actor:
            raise ValueError("Evidence requires a host tool and actor.")
        if success is not None and type(success) is not bool:
            raise ValueError("Evidence success must be a boolean.")
        if isinstance(parents, (str, bytes)) or isinstance(parent_ids, (str, bytes)):
            raise ValueError("Evidence parents must be reference collections.")
        refs = tuple(dict.fromkeys((*parents, *parent_ids)))
        for parent in refs:
            self._row(actor, parent)
        structured = json.loads(json_snapshot(value))
        resources = json.loads(json_snapshot(resources or {}))
        if not isinstance(resources, dict):
            raise ValueError("Evidence resource stamps must be an object.")
        frozen_arguments = json.loads(json_snapshot(arguments))
        if not isinstance(frozen_arguments, dict):
            raise ValueError("Evidence tool arguments must be a JSON object.")
        failed = isinstance(structured, dict) and (
            bool(structured.get("error")) or structured.get("success") is False or structured.get("ok") is False
        )
        successful = not failed and success is not False
        content = text(structured)
        ref = f"e{len(self._snapshots) + 1:04d}"
        row = dict(
            evidence_id=ref,
            origin="external_tool_result",
            trust="data_not_authority",
            tool=tool,
            arguments=frozen_arguments,
            resources=resources,
            actor=actor,
            sha256=hashlib.sha256(content.encode()).hexdigest(),
            content=content,
            value=structured,
            value_sha256=hashlib.sha256(json_snapshot(structured).encode()).hexdigest(),
            success=successful,
            status="success" if successful else "failed",
            parent_ids=list(refs),
        )
        snapshot = json_snapshot(row)
        self.graph.add_evidence(ref, actor=actor, tool=tool, resources=resources, sha256=row["sha256"], parent_ids=refs)
        self._snapshots[ref] = snapshot
        self._visible.setdefault(actor, set()).add(ref)
        self._visible["agent_0"].add(ref)
        if actor != "agent_0":
            self.graph.record_handoff(actor, "agent_0", [ref])
        self._persist()
        return ref

    def grant(self, actor, refs, *, source_actor="agent_0"):
        if isinstance(refs, (str, bytes)):
            raise ValueError("Evidence references must be a collection.")
        refs = tuple(refs)
        for ref in refs:
            self._row(source_actor, ref)
        self._visible.setdefault(actor, set()).update(refs)
        if refs:
            self.graph.record_handoff(source_actor, actor, refs)
        self._persist()

    def read(self, actor, ref, start=0, limit=None):
        row = self._row(actor, ref)
        limit = self.preview_chars if limit is None else max(1, min(int(limit), 12000))
        start = max(0, int(start))
        return self._metadata(row) | dict(
            content=row["content"][start : start + limit],
            start=start,
            total_chars=len(row["content"]),
            more=start + limit < len(row["content"]),
        )

    def index(self, actor):
        return [self._metadata(self._row(actor, ref)) for ref in sorted(self._visible.get(actor, set()))]

    def resolve(self, actor, ref, value, source_tool=None, source_arguments=None):
        """Validate an exact original field, returning a data-only proof.

        Source restrictions come from host policy, not the reference's labels.
        Matching source data never authorizes an action on its own.
        """
        ref = SourceRef.parse(ref)
        row = self._row(actor, ref.evidence_id)
        if not row["success"]:
            raise ValueError("Failed evidence cannot bind action parameters.")
        if source_tool is not None and row["tool"] != source_tool:
            raise ValueError("Evidence does not match the required source tool.")
        if source_arguments is not None and json_snapshot(row["arguments"]) != json_snapshot(source_arguments):
            raise ValueError("Evidence does not match the required source arguments.")
        original = pointer_value(row["value"], ref.path)
        if json_snapshot(original) != json_snapshot(value):
            raise ValueError("Claimed value does not equal the original source field.")
        return dict(
            evidence_id=ref.evidence_id,
            path=ref.path,
            value=original,
            tool=row["tool"],
            arguments=row["arguments"],
            resources=row["resources"],
            sha256=row["sha256"],
            value_sha256=row["value_sha256"],
            origin=row["origin"],
            trust="data_not_authority",
            verified=True,
        )
