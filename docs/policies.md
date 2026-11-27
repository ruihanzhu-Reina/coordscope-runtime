# Host policy contracts

The caller supplies a structured `ActionPolicy` before execution. It is not
produced by a model or by a benchmark's expected answer. The monitor checks
conformance to that contract; the host remains responsible for deciding which
actions the user authorized.

## Exact arguments

```python
from coordscope.security.policy import ActionPolicy

policy = ActionPolicy.exact([
    {"tool": "send_money", "arguments": {"recipient": "Alice", "amount": 10}}
])
```

Each row becomes a stable single-use grant. A repeated invocation with the same
grant and arguments returns the stored result after commit. It does not spend
another use or call the handler again. An empty list permits no effects.

The JSON equivalent is:

```json
{
  "version": 1,
  "grants": [
    {
      "id": "invoice-payment",
      "tool": "send_money",
      "arguments": {
        "recipient": {"exact": "Alice"},
        "amount": {"exact": 10}
      },
      "max_uses": 1
    }
  ]
}
```

Every supplied argument must have a rule, including body text, attachments and
optional fields supplied at dispatch. Required parameters must be covered.
Unknown tools, malformed policies, conflicting grants and type-invalid calls fail
closed. The host tool catalog declares the JSON Schema and reviewed effect.

## A value resolved from an authorized source

Suppose the host authorizes paying 10 to the account returned by one particular
lookup. It can bind the recipient to that source rather than guessing its value:

```json
{
  "version": 1,
  "grants": [
    {
      "id": "resolved-account-payment",
      "tool": "send_money",
      "arguments": {
        "recipient": {
          "source": {
            "tool": "lookup_account",
            "arguments": {"customer_id": "alice"},
            "path": "/account_number"
          }
        },
        "amount": {"exact": 10}
      },
      "max_uses": 1
    }
  ]
}
```

This example assumes those two host tools are registered with appropriate schemas
and effects. The source must be a successful original tool field with matching
lookup arguments and an exact JSON Pointer. It must be visible to the actor and
fresh according to externally observed resource stamps. No revision observer
means no field-bound authorization. The host can instead provide exact values
when it has verified them independently.

An LLM-extracted email, summary or invented `verified: true` label does not meet
this rule. Parsing a page into the correct person is a semantic resolution
problem; the host must implement a trusted resolver, provide an exact grant, or
leave the action blocked. The runtime does not silently use a Reviewer to bridge
that gap.

## Tool and resource registration

```python
from coordscope.security.resources import Footprint

tool = {
    "name": "lookup_account",
    "description": "Read one customer's account",
    "effect": "read",
    "parameters": {
        "type": "object",
        "properties": {"customer_id": {"type": "string"}},
        "required": ["customer_id"]
    },
    "handler": lookup_account,
    "resources": lambda args: Footprint(reads=("customer:" + args["customer_id"],))
}

def revision(resource_key):
    return authoritative_version(resource_key)
```

`lookup_account` and `authoritative_version` above are host implementation hooks,
not shipped functions. Pass `resources=revision` when creating a session or
executing the method. Mutating tools declare their write resources. Accurate
footprints and authoritative observers are trusted integration responsibilities.
An observer detects changes; a remote conditional write is still needed to close
the race between observation and commit.

## Scope of the contract

Grant use limits persist across process restarts for a stable task identity.
Changing a task's request, policy or catalog requires a new task or an explicit
host migration; reopening an incompatible journal is rejected. Changing a grant
ID is a host policy change, not an agent retry mechanism.

Read tools are governed by host role permissions. Source proofs establish value
identity and freshness, not truth or user intent. Authorized alternatives can
still form data-dependent choices; the contract is not a complete information-flow
noninterference proof. The final user-facing answer is also untrusted model data.
