"""Shared permissions and versioned cache for reviewed local reads only."""

import json
import threading

from .manifest import effect


class ToolGateway:
    def __init__(self, tools, store, contract, review):
        self.tools = {tool["name"]: tool for tool in tools}
        self.store, self.contract, self.review = store, contract, review
        self.version = 0
        self.cache, self.events, self.permissions = {}, [], {}
        self.lock = threading.RLock()

    def permit(self, actor, names):
        self.permissions[actor] = set(names)

    def call(self, actor, name, arguments, evidence_ids=()):
        with self.lock:
            event = dict(
                actor=actor, tool=name, arguments=arguments, environment_version=self.version, handler_invoked=False
            )
            self.events.append(event)
            if name not in self.permissions.get(actor, set()) or name not in self.tools or effect(name) != "read":
                event.update(status="blocked", policy_decision="deny", reason="Not a reviewed local read")
                return {"error": "ACTION_BLOCKED", "reason": event["reason"]}
            decision, reason = self.contract.initial_decision(name, arguments, actor)
            event.update(policy_decision=decision, policy_reason=reason)
            if decision != "allow":
                event["status"] = "blocked"
                return {"error": "ACTION_BLOCKED", "reason": reason}
            signature = (name, json.dumps(arguments, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
            key = (signature, self.version)
            if key in self.cache:
                ref = self.cache[key]
                self.store.grant(actor, [ref])
                event.update(status="cache_hit", evidence_id=ref)
                return dict(cache_hit=True, **self.store.read(actor, ref))
            try:
                event["handler_invoked"] = True
                output = self.tools[name]["handler"](arguments)
            except Exception as exc:
                event.update(status="handler_exception", error=type(exc).__name__)
                raise
            failed = isinstance(output, dict) and bool(output.get("error"))
            ref = self.store.add(output, tool=name, arguments=arguments, version=self.version, actor=actor)
            event.update(status="runtime_error" if failed else "executed", evidence_id=ref)
            if not failed:
                self.cache[key] = ref
            return self.store.read(actor, ref)
