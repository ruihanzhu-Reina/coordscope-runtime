"""Host coordinator: model transport, authority and tools stay outside workers."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from coordscope.evidence.store import EvidenceStore
from coordscope.security.gateway import GovernedGateway
from coordscope.security.policy import ActionPolicy

from .interpreter import IsolationError, Value, freeze
from .prompts import EXTRACT_SYSTEM, PLAN_SYSTEM
from .worker import run_in_worker, value_from_wire


@dataclass(frozen=True)
class Limits:
    max_model_calls: int = 64
    max_tokens: int = 250000
    max_steps: int = 256
    max_delegations: int = 24
    max_loop_items: int = 24
    max_json_chars: int = 1000000
    worker_timeout_s: int = 120

    def __post_init__(self):
        if any(type(v) is not int or v < 1 for v in vars(self).values()):
            raise ValueError("All isolation limits must be positive integers.")


@dataclass(frozen=True)
class Context:
    actor: str
    role: str
    task: str
    tools: frozenset[str]
    dependencies: frozenset[str] = frozenset()


class IsolatedSession:
    def __init__(
        self,
        user_request,
        tools,
        specs,
        completion,
        limits=None,
        *,
        policy=None,
        journal_path,
        task_id,
        resources=None,
    ):
        self.user_request, self.completion = user_request, completion
        self.limits = limits or Limits()
        self.roles = {spec.name: spec for spec in specs}
        self.catalog = {
            tool["name"]: {
                k: v for k, v in tool.items() if k in {"name", "description", "parameters", "returns", "effect"}
            }
            for tool in tools
        }
        assigned = [tool for spec in specs for tool in spec.tool_names]
        if len(self.roles) != len(specs) or len(assigned) != len(set(assigned)) or set(assigned) != set(self.catalog):
            raise ValueError("Roles must uniquely partition the complete tool catalog.")
        self.store = EvidenceStore()
        self.gateway = GovernedGateway(
            tools,
            self.store,
            policy if policy is not None else ActionPolicy.exact([]),
            journal_path=journal_path,
            task_id=task_id,
            user_request=user_request,
            resources=resources,
        )
        self.model_calls = self.tokens = self.steps = 0
        self.contexts = {}
        self.delegations, self.model_events, self.worker_events = [], [], []
        self.stop_reason = "not_started"

    def tick(self):
        self.steps += 1
        if self.steps > self.limits.max_steps:
            raise IsolationError("Execution step budget exhausted.")

    def complete(self, kind, actor, messages):
        if self.model_calls >= self.limits.max_model_calls or self.tokens >= self.limits.max_tokens:
            raise IsolationError("Model budget exhausted.")
        if len(freeze(messages)) > self.limits.max_json_chars:
            raise IsolationError("Model input exceeds its bound.")
        self.model_calls += 1
        event = dict(kind=kind, actor=actor, status="pending")
        self.model_events.append(event)
        try:
            result, tokens = self.completion(kind, actor, messages, self.limits.max_tokens - self.tokens)
            if type(tokens) is not int or tokens < 0:
                raise IsolationError("Completion token accounting must be a nonnegative integer.")
            self.tokens += tokens
            if self.tokens > self.limits.max_tokens:
                raise IsolationError("Model response exceeded the episode token budget.")
            if isinstance(result, str):
                if len(result) > self.limits.max_json_chars:
                    raise IsolationError("Model output exceeds its bound.")
                result = json.loads(result)
            result = json.loads(freeze(result))
            event.update(status="completed", tokens=tokens)
            return result
        except BaseException:
            event["status"] = "error"
            raise

    def plan(self, context, variables):
        packet = dict(
            root_request=self.user_request,
            task=context.task,
            role=context.role,
            input_variables=sorted(variables),
            tools=[self.catalog[n] for n in sorted(context.tools)],
        )
        if context.role == "orchestrator":
            packet["agents"] = [
                dict(name=spec.name, description=spec.description, tools=[self.catalog[n] for n in spec.tool_names])
                for spec in self.roles.values()
            ]
        # No tool outputs, variable values, errors, audit verdicts or previous
        # conversation are ever included in a planner request.
        return self.complete(
            "planner",
            context.actor,
            [dict(role="system", content=PLAN_SYSTEM), dict(role="user", content=freeze(packet))],
        )

    def _validate_context(self, context):
        if self.contexts.get(context.actor) is not context:
            raise IsolationError("Actor context was not issued by this task's host.")

    def _execute_plan(self, context, variables):
        """Run the fixed interpreter in a fresh process with host-bound RPC."""
        plan = self.plan(context, variables)

        def dispatch(operation, payload):
            if operation == "tick":
                return self.tick()
            if operation == "tool":
                values = {key: value_from_wire(value) for key, value in payload["values"].items()}
                return self.tool(context, payload["name"], values, payload.get("control", ()))
            if operation == "delegate":
                values = {key: value_from_wire(value) for key, value in payload["variables"].items()}
                return self.delegate(
                    context, payload["role"], payload["instruction"], values, payload.get("control", ())
                )
            if operation == "extract":
                return self.extract(context, payload["instruction"], value_from_wire(payload["value"]))
            raise IsolationError("Unsupported worker request.")

        event = dict(actor=context.actor, status="starting")
        self.worker_events.append(event)
        try:
            result = run_in_worker(
                plan=plan,
                context=asdict(context),
                variables=variables,
                roles=tuple(self.roles),
                limits=asdict(self.limits),
                dispatch=dispatch,
                timeout_s=self.limits.worker_timeout_s,
                max_frame_bytes=self.limits.max_json_chars * 4 + 65536,
                on_start=lambda pid: event.update(pid=pid, status="running"),
            )
            event["status"] = "completed"
            return result
        except BaseException:
            event["status"] = "failed"
            raise

    def delegate(self, parent, role, instruction, variables, control=()):
        self._validate_context(parent)
        if parent.role != "orchestrator" or role not in self.roles or not isinstance(instruction, str):
            raise IsolationError("Invalid delegation boundary.")
        if len(self.delegations) >= self.limits.max_delegations:
            raise IsolationError("Delegation budget exhausted.")
        actor = f"{role}_{len(self.delegations) + 1}"
        dependencies = parent.dependencies | frozenset(control)
        context = Context(actor, role, instruction, frozenset(self.roles[role].tool_names), dependencies)
        self.contexts[actor] = context
        self.gateway.permit(actor, context.tools)
        refs = set(dependencies).union(*(v.dependencies for v in variables.values()))
        self.store.grant(actor, refs, source_actor=parent.actor)
        record = dict(
            actor=actor,
            role=role,
            parent=parent.actor,
            task_scope=self.gateway.task_scope,
            message=instruction,
            variables=sorted(variables),
            evidence_ids=sorted(refs),
            status="started",
        )
        self.delegations.append(record)
        try:
            result = self._execute_plan(context, variables)
            # Child answers are data even when the child returned a literal.
            value = self.record(context, "__agent_result__", result.data, result.dependencies)
            self.store.grant(parent.actor, value.dependencies, source_actor=actor)
            record["status"] = "completed"
            # Preserve the original field proof across a handoff; wrapping it
            # must not replace its resource stamps with a newer observation.
            return Value.of(result.data, value.dependencies, result.field)
        except BaseException:
            record["status"] = "failed"
            raise
        finally:
            self.gateway.permit(actor, [])

    def record(self, context, source, data, parents):
        if len(freeze(data)) > self.limits.max_json_chars:
            raise IsolationError("Data value exceeds its bound.")
        ref = self.store.add(
            data,
            tool=source,
            arguments={},
            actor=context.actor,
            parents=sorted(parents),
            resources=self._dependency_resources(context.actor, parents),
        )
        return Value.of(data, frozenset(parents) | {ref}, (ref, ""))

    def _dependency_resources(self, actor, refs):
        stamps = {}
        for ref in refs:
            for key, stamp in self.store._row(actor, ref)["resources"].items():
                if key in stamps and stamps[key] != stamp:
                    # Conflicting observations cannot be made fresh by merging.
                    stamps[key] = dict(revision=-1, validator=None, external=False)
                else:
                    stamps[key] = stamp
        return stamps

    def extract(self, context, instruction, value):
        self._validate_context(context)
        for ref in value.dependencies:
            self.store.read(context.actor, ref)
        result = self.complete(
            "quarantined",
            context.actor + "_data",
            [
                dict(role="system", content=EXTRACT_SYSTEM),
                dict(role="user", content=freeze(dict(instruction=instruction, data=value.data))),
            ],
        )
        # Even a response that looks like a plan remains a data value. Preserve
        # all input dependencies, not just fields the data model claims it used.
        return self.record(context, "__quarantined_result__", result, value.dependencies)

    def tool(self, context, tool, values, control=()):
        self._validate_context(context)
        if tool not in context.tools:
            raise IsolationError("Tool is outside the specialist role.")
        refs = frozenset(control).union(*(v.dependencies for v in values.values()))
        for ref in refs:
            self.store.read(context.actor, ref)
        arguments = {key: value.data for key, value in values.items()}
        sources = {
            key: dict(evidence_id=value.field[0], path=value.field[1]) for key, value in values.items() if value.field
        }
        receipt = self.gateway.call(context.actor, tool, arguments, sorted(refs), sources)
        if "evidence_id" not in receipt:
            # Raw guard reasons may include external content; keep them data.
            return self.record(context, "__blocked_call__", receipt, refs)
        ref = receipt["evidence_id"]
        row = self.store._row(context.actor, ref)
        return Value.of(row["value"], refs | {ref}, (ref, ""))

    def run(self):
        context = Context("orchestrator", "orchestrator", self.user_request, frozenset())
        self.contexts[context.actor] = context
        self.gateway.permit(context.actor, [])
        self.stop_reason = "running"
        try:
            result = self._execute_plan(context, {})
            self.stop_reason = "completed"
            return result.data if isinstance(result.data, str) else freeze(result.data)
        except BaseException:
            self.stop_reason = "failed_closed"
            raise

    def snapshot(self):
        return dict(
            profile="host_policy_governed",
            implementation="process_json_plan_interpreter",
            stop_reason=self.stop_reason,
            model_calls=self.model_calls,
            tokens=self.tokens,
            executed_steps=self.steps,
            delegations=self.delegations,
            model_events=self.model_events,
            workers=self.worker_events,
            gateway_events=self.gateway.events,
            runtime_governance=self.gateway.snapshot(),
            actual_specialist_count=len({r["role"] for r in self.delegations}),
            specialist_invocations=len(self.delegations),
        )

    def close(self):
        self.gateway.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
