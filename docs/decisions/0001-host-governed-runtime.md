# ADR-0001: Host authority, durable dispatch and fixed interpreter workers

## Status

Accepted.

## Date

2026-11-27.

## Context

The extracted runtime combined an in-memory capability ledger, a whole-environment
version, model-generated authorization and an interpreter running in the host
process. Those choices were useful for the original bounded experiment, but they
do not provide durable effect accounting or a deterministic source of authority.
Adding persistence around the same semantic-approval path would preserve that
trust problem.

This decision supersedes the runtime assumptions recorded by the 2026 migration
in [migration decisions](../migration/decisions.md) and
[migration validation](../migration/validation.md). Those documents remain
unchanged historical records of the implementation that was migrated. Their
results do not validate this replacement.

The reviewed sources and their limits are recorded in
[runtime design references](../references/runtime-design.md).

## Decision

### Authority is supplied by the host

`ActionPolicy` is a structured caller input, separate from the model completion
interface. An empty policy grants no effects. Exact bindings constrain a concrete
parameter value; source bindings constrain a named real tool, its complete lookup
arguments and an exact JSON field path. The gateway checks the original value,
visibility, success and resource stamps. Source-bound grants require supported
external validators. Derived model summaries cannot become source authority.

Policy matching, role permissions, schema validation and grant budgets are
deterministic. Overlapping matching grants fail closed. The LLM planner and data
processor cannot create, enlarge or renew grants. Translating a natural-language
request into the correct host contract remains an application responsibility;
the runtime does not claim to prove that translation.

### Effects cross one durable boundary

`GovernedGateway` composes `Journal`, `ResourceTracker`, `ActionPolicy` and
`EvidenceStore`. It does not inherit a second read gateway. A journal requires a
disk path and stable task identity and binds the request, canonical policy and
trusted tool catalog. An exclusive owner lock prevents concurrent local owners;
SQLite WAL with `synchronous=FULL` stores reservations, outcomes and evidence.

```text
new -> reserved -> dispatched -> committed
                     |
                     +---------> unknown

reserved -> not_applied     only when dispatch has not begun
unknown  -> committed       trusted host reconciliation
unknown  -> not_applied     trusted host reconciliation
```

Budget consumption and reservation share a database transaction. Dispatch state is
persisted before calling the handler. A committed operation returns its stored
normalized JSON result on replay. Pending operations found after owner recovery
become unknown; they are not automatically retried. An attested not-applied
outcome releases the reserved budget. Reconciliation is never an agent tool or a
model-provided success flag.

The ledger is not a transaction over a remote service and does not promise
remote exactly-once execution. A provider's idempotency or status-query protocol
must justify any retry. Recovery reopens effect accounting and evidence, not a
saved program counter, old model conversation or native benchmark environment.

### Resource observations replace the global version

Trusted tool definitions declare effects and may provide object-level
`Footprint(reads, writes)` callbacks. Without a precise mapping, a conservative
resource-domain footprint is used. Local resource revisions are persisted;
optional host revision callbacks observe external changes. The AgentDojo adapter
currently hashes native state by domain, not by individual object.

There is no default read cache. Every read executes again. Evidence retains its
original stamps, and all argument and control dependencies are checked even when
a transformation has removed a direct field pointer. Effect reservations include
those dependency keys in their read footprint. Unknown operations block
conflicting access; independent resources can continue.

A matching stamp is a freshness observation, not a remote compare-and-swap. The
gateway checks again before dispatch, excluding its own reservation from conflict
detection. An adapter that needs an atomic precondition must enforce it at the
backend, for example with `If-Match` or a storage transaction.

### The interpreter runs fixed code in separate processes

Each bounded JSON plan runs in a fresh interpreter worker. Model transport, tool
handlers, credentials, policy and the journal remain in the host. Bounded JSON
frames broker permitted operations; actor identity is bound by the host rather
than selected by the worker payload. The worker receives no arbitrary Python or
pickle to execute.

Plan validation uses SSA-style single-assignment names for inputs, outputs and loop
items so reassignment cannot erase a dependency. An instruction selected by
untrusted branch or loop control remains tainted and cannot enter a delegated
planner, even if its text is a literal. External values may be passed as data
variables instead.

The installed worker code is trusted and runs under the same operating-system
user. This is address-space and failure separation, not an OS sandbox for hostile
Python or native extensions. Worker timeouts do not interrupt a synchronous host
tool handler; transports need their own timeout and uncertainty handling.

### Benchmark orchestration is an adapter boundary

The shared CLI runner owns configuration, output layout, method construction,
policy snapshots and result accounting. Native adapters own environments, attacks
and official judges. Installed adapters register through the
`coordscope.benchmarks` entry-point group and load only when selected. Only
AgentDojo is implemented. The extension mechanism is not evidence of results on
other benchmarks. See [benchmark contracts and commands](../benchmarks.md).

## Alternatives considered

| Alternative | Reason rejected or deferred |
|---|---|
| Persist the old capabilities dictionary and keep semantic grants | Preserves model-created authority and does not define dispatch recovery. |
| Treat an LLM verdict as a trusted policy document | Moves the same semantic trust assumption into a different serialization format. |
| Increment one version after every effect | Invalidates unrelated observations while missing external writers. |
| Cache reads without backend validators | Cannot establish when a third party changed the resource. |
| Retry every unknown operation after a timeout | A completed external effect may have lost its receipt. |
| Use a subprocess as a hostile-code sandbox | A same-user process alone does not constrain filesystem, network or OS access. |
| Add Temporal or DBOS as a mandatory service | Their durable-workflow models are useful references, but a service dependency does not remove the external-effect protocol requirement. |
| Add benchmark-specific execution loops to the core | Duplicates the method and mixes authorization with native scoring. |

## Removed paths and consequences

`security/compiler.py` and the model reviewer/semantic-grant route are removed.
`security/read_gateway.py`, the inherited global-version cache and task-local
capability-state implementation are replaced. AgentDojo declarations and bindings
live under `benchmarks/agentdojo`; the generic security core does not classify
tool names from a benchmark manifest. The former `integrations/agentdojo` route
is replaced by the native adapter package and shared method.

Embedding applications now supply explicit task/journal identity, reviewed tool
effects and a host policy. Existing callers and command invocations must migrate;
there is no silent fallback to model-generated authority. Runtime files can
contain task data and need the same access controls as their tool environment.

## Verification

Fault and boundary tests cover process death after a controlled external effect,
committed-result replay, competing owners, contract rebinding, host reconciliation,
source freshness and shared budgets. Resource tests include unrelated writes,
external changes, transformed/control dependencies, same-resource read/write and
validator failure after dispatch. Interpreter and worker tests cover
single-assignment validation, tainted delegation control, process identity,
bounded IPC and worker failure. Adapter tests retain native environments, traces
and judge semantics; extension tests exercise the shared runner without loading
AgentDojo. These checks are implementation evidence, not live model performance
or a proof of remote exactly-once execution.
