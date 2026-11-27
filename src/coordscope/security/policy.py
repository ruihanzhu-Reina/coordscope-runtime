"""Host-owned structured authority; model outputs can never create grants.

Conformance to this contract does not prove that the host correctly translated
natural-language intent. Source proofs come from the host gateway, never an LLM.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from math import isfinite

from coordscope.evidence.provenance import pointer_tokens

_EFFECTS = frozenset({"read", "navigate", "send", "mutate", "consume"})


def _json(value):
    def check(item):
        if item is None or type(item) in {str, bool, int}:
            return
        if type(item) is float and isfinite(item):
            return
        if type(item) is list:
            for child in item:
                check(child)
            return
        if type(item) is dict and all(type(key) is str for key in item):
            for child in item.values():
                check(child)
            return
        raise ValueError("Policy values must be finite JSON values with string object keys.")

    check(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _object(value, required, optional=()):
    if type(value) is not dict or set(value) - set(required) - set(optional) or not set(required) <= set(value):
        raise ValueError("Policy object contains missing or unsupported fields.")


def _name(value):
    if type(value) is not str or not value or value.startswith("__"):
        raise ValueError("Policy identifiers must be nonempty host identifiers, not synthetic evidence names.")
    return value


def _bindings(arguments):
    if type(arguments) is not dict or any(type(key) is not str or not key for key in arguments):
        raise ValueError("Grant arguments must map parameter names to explicit bindings.")
    for binding in arguments.values():
        if type(binding) is not dict or len(binding) != 1:
            raise ValueError("Each parameter needs exactly one exact or source binding.")
        if set(binding) == {"exact"}:
            _json(binding["exact"])
        elif set(binding) == {"source"}:
            source = binding["source"]
            _object(source, {"tool", "arguments", "path"})
            _name(source["tool"])
            if type(source["arguments"]) is not dict:
                raise ValueError("Source lookup arguments must be a JSON object.")
            _json(source["arguments"])
            pointer_tokens(source["path"])
        else:
            raise ValueError("Only exact and source parameter bindings are supported.")
    return _json(arguments)


@dataclass(frozen=True)
class ActionGrant:
    """Immutable bounded host grant; the durable gateway reserves its uses."""

    id: str
    tool: str
    bindings_json: str
    max_uses: int = 1

    def __post_init__(self):
        _name(self.id)
        _name(self.tool)
        if type(self.max_uses) is not int or self.max_uses < 1:
            raise ValueError("Grant max_uses must be a positive integer.")
        if type(self.bindings_json) is not str:
            raise ValueError("Grant bindings must use immutable JSON storage.")
        try:
            canonical = _bindings(json.loads(self.bindings_json))
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("Invalid grant bindings JSON.") from exc
        if canonical != self.bindings_json:
            raise ValueError("Grant bindings must use canonical JSON.")

    @property
    def arguments(self):
        return json.loads(self.bindings_json)

    def to_document(self):
        return dict(id=self.id, tool=self.tool, arguments=self.arguments, max_uses=self.max_uses)


@dataclass(frozen=True)
class ActionPolicy:
    """A host-supplied contract. An empty policy grants no effects.

    Source bindings authorize named real tool fields, not arbitrary model
    derivations. Overlapping grants fail closed instead of using policy order.
    """

    grants: tuple[ActionGrant, ...] = ()

    def __post_init__(self):
        if type(self.grants) is not tuple or any(type(grant) is not ActionGrant for grant in self.grants):
            raise ValueError("Policy grants must be an immutable tuple of ActionGrant objects.")
        if len({grant.id for grant in self.grants}) != len(self.grants):
            raise ValueError("Grant IDs must be unique within the policy.")
        if len({(grant.tool, grant.bindings_json) for grant in self.grants}) != len(self.grants):
            raise ValueError("Duplicate action bindings create ambiguous authority.")

    @classmethod
    def from_document(cls, document):
        _object(document, {"version", "grants"})
        if type(document["version"]) is not int or document["version"] != 1:
            raise ValueError("Only policy version 1 is supported.")
        if type(document["grants"]) is not list:
            raise ValueError("Policy grants must be an array.")
        grants = []
        for row in document["grants"]:
            _object(row, {"id", "tool", "arguments"}, {"max_uses"})
            grants.append(ActionGrant(row["id"], row["tool"], _bindings(row["arguments"]), row.get("max_uses", 1)))
        return cls(tuple(grants))

    @classmethod
    def exact(cls, actions):
        """Create single-use exact grants from host-owned tool/arguments rows."""
        if type(actions) not in {list, tuple}:
            raise ValueError("Exact host actions must be a list or tuple.")
        rows = []
        for action in actions:
            _object(action, {"tool", "arguments"})
            if type(action["arguments"]) is not dict:
                raise ValueError("Exact action arguments must be a JSON object.")
            signature = _json(action)
            rows.append(
                dict(
                    id="exact-" + hashlib.sha256(signature.encode()).hexdigest(),
                    tool=action["tool"],
                    arguments={key: {"exact": value} for key, value in action["arguments"].items()},
                    max_uses=1,
                )
            )
        return cls.from_document(dict(version=1, grants=rows))

    def to_document(self):
        return dict(version=1, grants=[grant.to_document() for grant in self.grants])

    @property
    def fingerprint(self):
        # Grant ordering carries no authority semantics.
        document = dict(version=1, grants=[grant.to_document() for grant in sorted(self.grants, key=lambda g: g.id)])
        return hashlib.sha256(_json(document).encode()).hexdigest()

    def validate(self, tools):
        """Check the contract against a trusted catalog before registration."""
        catalog = {}
        for tool in tools:
            name = _name(tool["name"])
            if name in catalog or tool.get("effect") not in _EFFECTS:
                raise ValueError("Catalog names must be unique with explicit reviewed effects.")
            catalog[name] = tool

        def parameters(name, arguments):
            if name not in catalog:
                raise ValueError("Policy names a tool outside the host catalog.")
            schema = catalog[name]["parameters"]
            declared = set(schema.get("properties", {}))
            required = set(schema.get("required", ()))
            if set(arguments) - declared or not required <= set(arguments):
                raise ValueError("Policy must cover required parameters and cannot name undeclared parameters.")

        for grant in self.grants:
            parameters(grant.tool, grant.arguments)
            for binding in grant.arguments.values():
                if "source" in binding:
                    source = binding["source"]
                    parameters(source["tool"], source["arguments"])
        return self

    def authorize(self, tool, arguments, proofs=()):
        """Return one matching grant without consuming its durable use budget.

        Proof flags are host inputs, not cryptographic attestations. Never copy
        them from model-supplied labels. The gateway validates the actual source.
        """
        if type(arguments) is not dict or type(proofs) not in {list, tuple}:
            return None
        try:
            _json(arguments)
        except ValueError:
            return None
        by_parameter = {}
        for proof in proofs:
            if (
                type(proof) is not dict
                or type(proof.get("parameter")) is not str
                or proof["parameter"] not in arguments
            ):
                return None
            parameter = proof["parameter"]
            if parameter in by_parameter:
                return None
            by_parameter[parameter] = proof
        matches = []
        for grant in self.grants:
            bindings = grant.arguments
            if grant.tool != tool or set(arguments) != set(bindings):
                continue
            permitted = True
            for parameter, binding in bindings.items():
                value = arguments[parameter]
                if "exact" in binding:
                    permitted = _json(value) == _json(binding["exact"])
                else:
                    source = binding["source"]
                    proof = by_parameter.get(parameter, {})
                    try:
                        permitted = (
                            proof.get("verified") is True
                            and proof.get("freshness_verified") is True
                            and proof.get("origin") == "external_tool_result"
                            and proof.get("tool") == source["tool"]
                            and proof.get("path") == source["path"]
                            and "arguments" in proof
                            and _json(proof["arguments"]) == _json(source["arguments"])
                            and "value" in proof
                            and _json(proof["value"]) == _json(value)
                        )
                    except ValueError:
                        permitted = False
                if not permitted:
                    break
            if permitted:
                matches.append(grant)
        return matches[0] if len(matches) == 1 else None
