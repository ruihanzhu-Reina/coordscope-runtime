"""Deterministic authorization and a durable, host-owned dispatch boundary."""

import copy
import hashlib
import json
import threading

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from coordscope.evidence.provenance import json_snapshot

from .journal import Journal, canonical
from .resources import Footprint, ResourceTracker


class GovernedGateway:
    def __init__(self, tools, store, policy, *, journal_path, task_id, user_request, resources=None):
        if not isinstance(task_id, str) or not task_id or not isinstance(user_request, str):
            raise ValueError("A stable host task identity and user request are required.")
        self.tools = {tool["name"]: tool for tool in tools}
        if len(self.tools) != len(tools):
            raise ValueError("Duplicate host tool names.")
        for tool in tools:
            if tool.get("effect") not in {"read", "navigate", "send", "mutate", "consume"}:
                raise ValueError("Every host tool requires an explicit reviewed effect.")
            if not callable(tool.get("handler")):
                raise ValueError("Every host tool requires a handler.")
            Draft202012Validator.check_schema(tool["parameters"])
        self.validators = {tool["name"]: Draft202012Validator(tool["parameters"]) for tool in tools}
        policy.validate(tools)
        catalog = [{key: value for key, value in tool.items() if key not in {"handler", "resources"}} for tool in tools]
        policy_document = policy.to_document()
        policy_document["grants"].sort(key=lambda grant: grant["id"])
        self.journal = Journal(
            journal_path,
            dict(
                task_id=task_id,
                user_request=user_request,
                policy=policy_document,
                policy_fingerprint=policy.fingerprint,
                catalog=sorted(catalog, key=lambda t: t["name"]),
            ),
        )
        try:
            self.store, self.policy, self.task_scope = store, policy, task_id
            self.resources = ResourceTracker(self.journal, resources)
            self.permissions, self.events = {}, []
            self.lock = threading.RLock()
            self.store.attach_journal(self.journal)
        except BaseException:
            self.journal.close()
            raise

    def close(self):
        with self.lock:
            self.journal.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def permit(self, actor, names):
        with self.lock:
            names = set(names)
            if not names <= self.tools.keys():
                raise ValueError("Cannot permit tools outside the host catalog.")
            self.permissions[actor] = names

    def _validate(self, name, args):
        if name not in self.tools or not isinstance(args, dict):
            raise ValueError("Unknown tool or invalid arguments.")
        schema = self.tools[name]["parameters"]
        if set(args) - set(schema.get("properties", {})):
            raise ValueError("Undeclared arguments cannot receive authority.")
        if not set(schema.get("required", ())) <= set(args):
            raise ValueError("Missing required arguments.")
        self.validators[name].validate(args)
        canonical(args)

    def _sources(self, actor, arguments, sources, exclude_operation=None):
        if not isinstance(sources, dict) or set(sources) - set(arguments):
            raise ValueError("Argument sources must name actual arguments.")
        proofs = []
        for parameter, ref in sources.items():
            proof = self.store.resolve(actor, ref, arguments[parameter])
            stamps = proof.get("resources", {})
            self.journal.check_conflicts(Footprint(reads=tuple(stamps)).to_document(), exclude_operation)
            current = self.resources.capture(stamps)
            if canonical(current) != canonical(stamps):
                raise ValueError("Source resource changed; fresh evidence is required.")
            proof["freshness_verified"] = bool(stamps) and all(
                stamp.get("external") is True for stamp in stamps.values()
            )
            proofs.append(dict(parameter=parameter, **proof))
        return proofs

    def _dependencies(self, actor, refs, exclude_operation=None):
        keys = set()
        for ref in refs:
            stamps = self.store._row(actor, ref)["resources"]
            self.journal.check_conflicts(Footprint(reads=tuple(stamps)).to_document(), exclude_operation)
            if not self.resources.validate(stamps):
                raise ValueError("An action or control dependency changed; fresh evidence is required.")
            keys.update(stamps)
        return keys

    @staticmethod
    def _failed(output):
        return isinstance(output, dict) and (
            bool(output.get("error")) or output.get("ok") is False or output.get("success") is False
        )

    def _replay(self, actor, row):
        if row["result"] is None:
            return dict(already_applied=True, operation_id=row["id"], outcome="committed", result_available=False)
        ref = row["evidence_id"]
        try:
            self.store.grant(actor, [ref])
            result = self.store.read(actor, ref)
        except (KeyError, ValueError, TypeError):
            ref = self.store.add(
                row["result"], tool=row["tool"], arguments=row["arguments"], resources=row["resources"], actor=actor
            )
            result = self.store.read(actor, ref)
        return dict(already_applied=True, operation_id=row["id"], **result)

    def call(self, actor, name, arguments, evidence_ids=(), argument_sources=None):
        arguments = json.loads(canonical(arguments))
        sources = copy.deepcopy(argument_sources or {})
        refs = tuple(evidence_ids)
        event = dict(
            actor=actor, tool=name, arguments=copy.deepcopy(arguments), evidence_ids=list(refs), handler_invoked=False
        )

        def deny(reason):
            event.update(status="blocked", policy_decision="deny", reason=str(reason))
            self.journal.event("blocked", event)
            return dict(error="ACTION_BLOCKED", reason=str(reason))

        with self.lock:
            self.events.append(event)
            operation_id = None
            reserved = False
            if name not in self.permissions.get(actor, set()):
                return deny("Tool is outside this actor's capabilities.")
            try:
                self._validate(name, arguments)
                for ref in refs:
                    self.store.read(actor, ref)
                tool = self.tools[name]
                footprint = self.resources.footprint(tool, arguments)
                if tool["effect"] == "read":
                    dependency_keys = self._dependencies(actor, refs)
                    self.journal.check_conflicts(footprint.to_document())
                    stamps = self.resources.capture((*footprint.reads, *dependency_keys))
                    event["handler_invoked"] = True
                    output = tool["handler"](copy.deepcopy(arguments))
                    ref = self.store.add(output, tool=name, arguments=arguments, resources=stamps, actor=actor)
                    event.update(status="runtime_error" if self._failed(output) else "executed", evidence_id=ref)
                    self.journal.event("read", event)
                    return self.store.read(actor, ref)
                # Reading an already committed receipt creates no new effect,
                # so later source changes must not hide that known outcome.
                for candidate in self.policy.grants:
                    if candidate.tool != name:
                        continue
                    operation_id = hashlib.sha256(canonical([candidate.id, name, arguments]).encode()).hexdigest()
                    existing = self.journal.operation(operation_id)
                    if existing and existing["state"] == "committed":
                        event.update(status="already_applied", operation_id=operation_id)
                        return self._replay(actor, existing)
                dependency_keys = self._dependencies(actor, refs)
                proofs = self._sources(actor, arguments, sources)
                footprint = Footprint(
                    reads=(
                        *footprint.reads,
                        *dependency_keys,
                        *(key for proof in proofs for key in proof.get("resources", {})),
                    ),
                    writes=footprint.writes,
                )
                event["argument_provenance"] = proofs
                event["evidence_ids"] = list(dict.fromkeys((*refs, *(p["evidence_id"] for p in proofs))))
                grant = self.policy.authorize(name, arguments, proofs)
                if grant is None:
                    return deny("No host action grant matches the exact arguments and verified sources.")
                operation_id = hashlib.sha256(canonical([grant.id, name, arguments]).encode()).hexdigest()
                row = self.journal.reserve(operation_id, grant, name, arguments, footprint.to_document())
                if row["state"] != "reserved":
                    return deny("Operation outcome is uncertain; host reconciliation is required.")
                reserved = True
                # Remote atomicity requires an adapter's conditional write/CAS;
                # this local check alone does not close a remote race window.
                self._dependencies(actor, refs, operation_id)
                fresh_proofs = self._sources(actor, arguments, sources, operation_id)
                fresh_grant = self.policy.authorize(name, arguments, fresh_proofs)
                if fresh_grant is None or fresh_grant.id != grant.id:
                    raise PermissionError("Action authorization changed before dispatch.")
                self.journal.dispatched(operation_id)
                reserved = False
            except (ValueError, KeyError, TypeError, PermissionError, ValidationError) as exc:
                if reserved:
                    self.journal.cancel_reserved(operation_id)
                return deny(exc)
            except BaseException:
                if reserved:
                    self.journal.cancel_reserved(operation_id)
                raise
            event.update(
                operation_id=operation_id,
                grant_id=grant.id,
                policy_decision="allow",
                authorization_route="host_action_policy",
            )
            try:
                event["handler_invoked"] = True
                output = tool["handler"](copy.deepcopy(arguments))
                self.resources.bump(footprint.writes)
                stamps = self.resources.capture((*footprint.reads, *footprint.writes))
                ref = self.store.add(output, tool=name, arguments=arguments, resources=stamps, actor=actor)
                normalized = self.store.entries[ref]["value"]
                state = "unknown" if self._failed(normalized) else "committed"
                self.journal.finish(operation_id, state, normalized, ref, stamps)
                event.update(
                    status="runtime_error" if state == "unknown" else "executed", outcome=state, evidence_id=ref
                )
                return self.store.read(actor, ref)
            except BaseException as exc:
                row = self.journal.operation(operation_id)
                if row["state"] == "dispatched":
                    self.resources.bump(footprint.writes)
                    self.journal.finish(operation_id, "unknown")
                event.update(status="handler_or_receipt_exception", outcome="unknown", error_type=type(exc).__name__)
                raise

    def reconcile(self, operation_id, outcome, result=None):
        """Trusted host attestation only; this method is never an agent tool."""
        with self.lock:
            row = self.journal.operation(operation_id)
            if row is None or row["state"] != "unknown":
                raise ValueError("Only unknown operations need host reconciliation.")
            if outcome not in {"committed", "not_applied"}:
                raise ValueError("A verified external outcome is required.")
            if result is not None:
                result = json.loads(json_snapshot(result))
                if outcome != "committed" or self._failed(result):
                    raise ValueError("Only a successful result can attest a committed operation.")
            self.resources.bump(row["footprint"]["writes"])
            stamps = self.resources.capture((*row["footprint"]["reads"], *row["footprint"]["writes"]))
            ref = None
            if outcome == "committed" and result is not None:
                ref = self.store.add(
                    result, tool=row["tool"], arguments=row["arguments"], resources=stamps, actor="agent_0"
                )
                result = self.store.entries[ref]["value"]
            self.journal.reconcile(operation_id, outcome, result, ref, stamps)

    def snapshot(self):
        with self.lock:
            return dict(task_scope=self.task_scope, **self.journal.snapshot(), provenance=self.store.graph.export())
