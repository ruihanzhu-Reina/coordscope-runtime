# Execution architecture

CoordScope runs a fixed, bounded plan interpreter in separate processes. The
host owns the task, policy, model transport, tools, evidence and effect ledger.
Benchmark adapters supply native environments and native judges; they do not
change the execution method or infer authority from task answers.

## Responsibilities and dependencies

| Package | Owns | May depend on |
|---|---|---|
| `agents` | Trusted planner requests, bounded JSON plans, worker RPC, delegation | `security`, `evidence` |
| `security` | Structured grants, JSON Schema validation, durable effects, resource checks | `evidence`, SQLite, JSON Schema |
| `evidence` | Immutable JSON snapshots, field proofs, access and lineage | Python standard library; injected journal |
| `models` | Provider transport, validated usage, request budgets | Model SDK |
| `runtime` | Reusable method composing sessions and model transport | Core packages above |
| `benchmarks` | Adapter contract, lazy registry, native integrations | `runtime`; optional native packages inside adapters |
| `evaluation` | Run artifacts, provenance, score validity, aggregation | Adapter contract and registry; reusable method |
| `cli` | Configuration-based command entry point | Public runner and registry |

Only `benchmarks/agentdojo` imports AgentDojo. The reviewed tool manifest and
MultiAgentDojo role partitions live there, rather than in the core security
package. A new adapter declares its own host tool effects and resource bindings.
The pinned dependency under `third_party/agentdojo` is not modified to change a
judge or hide a failed task.

## One execution

1. The runner reads a versioned JSON config and a host-reviewed policy. It creates
   a fresh run directory and snapshots both inputs.
2. An adapter loads the native task/environment. It binds JSON tool schemas,
   trusted handlers, explicit effects, role partitions and resource observers.
3. `CoordScopeMethod.execute` creates a session with a disk journal. The journal
   binds a stable task ID to the user request, effective policy and tool catalog.
4. A planner receives the trusted task and catalog, plus variable names. External
   variable values, previous tool errors and extraction results are absent.
5. A fresh interpreter process validates the complete plan before execution. It
   sends bounded JSON RPC requests to host-bound `tick/tool/delegate/extract`
   callbacks. RPC has no actor-selection or permission-granting operation.
6. The host gateway checks role permissions, schema, exact grants, source fields,
   dependency freshness, resource conflicts and the durable use budget. It writes
   a reservation and dispatch marker before invoking a side-effecting handler.
7. The actual handler runs in the host, retaining the caller's native mutable
   environment. Evidence and terminal operation state are persisted. The worker
   receives a detached JSON result.
8. The adapter uses native judges and real tool traces. The generic runner writes
   one result envelope, retaining native metrics separately from normalized task
   and attacker-success fields.

The root has no business tools. Only the root delegates; specialists have fixed
host-assigned tool sets and cannot delegate further. The current task graph has
one orchestrator level and serial interpretation.

## Authority is an input

`ActionPolicy` is supplied by the host. Every dispatched argument of an effect
must match an exact value or an explicitly named source field. A source rule pins
the real lookup tool, its complete arguments and a JSON Pointer. The gateway
verifies visibility, successful evidence, exact field equality and resource
freshness. Quarantined model output and agent summaries cannot satisfy a source
rule. Missing or ambiguous grants deny execution.

The LLM Compiler and Reviewer paths were removed. Models can propose plans or
process data; their `allow`, `trusted`, or `origin` labels do not create grants.
An empty policy permits no effects. Reviewed reads still depend on the role's
tool permissions; this is not a per-object read ACL or proof that the host
translated natural-language intent correctly.

See [policy contracts](policies.md) for exact and dynamic examples.

## Evidence and resource consistency

`Value` keeps JSON data, source dependencies and an optional original field
reference. Tool results, model data processing and agent answers remain data.
Handoffs retain the original field reference and stamps. Derived records inherit
their parents' resources, including conflicting stamps; wrapping stale data does
not make it fresh.

Plans use single-assignment names: inputs, outputs and loop items cannot be
overwritten, even in an untaken branch. A delegation instruction may not depend
on external data or external control flow. For a data-dependent batch, delegate
once with a fixed instruction and opaque list variable, then loop over that list
inside the specialist's fixed tool plan. No-tool extraction can still process
data under fixed instructions.

Host tools may provide `resources(arguments) -> Footprint(reads, writes)`.
Resource revisions are stored per key. A host revision observer can add an ETag,
version or state digest that detects modifications outside the gateway. The
AgentDojo adapter currently observes native environment domains conservatively;
the core can use object-specific keys when a host declares accurate footprints.

There is no default read cache. Unknown footprints use a conservative host domain
or tool key. A field-bound grant requires externally observed freshness; a local
revision counter alone is insufficient. All source and control dependencies are
checked before a new effect. Unknown effects block conflicting reads/writes,
while independent resources can proceed.

A revision observation does not make a remote read/write atomic. An integration
needing that guarantee must enforce an expected revision at the external commit
point, for example with `If-Match`, a conditional update or a transaction. The
generic broker does not claim that all native tools support these protocols.

## Durable effect states

```text
not present -> reserved -> dispatched -> committed
                  |            |
                  |            +-----> unknown
                  v
              not_applied

reopen reserved/dispatched -> unknown
host attestation: unknown -> committed | not_applied
```

SQLite uses WAL, `synchronous=FULL` and immediate transactions. An operating-system
file lock permits one live owner per journal. Reservation and budget consumption
are atomic. A known committed invocation replays its stored receipt without
calling the handler; the same grant and arguments identify the same operation.
Different values under a source grant share its persistent `max_uses` budget.

Any ambiguous dispatched result remains `unknown`. Reopening a journal never
automatically retries an uncertain effect. A trusted host must verify the actual
external outcome before calling `gateway.reconcile`; that hook is absent from
the model tool catalog. An attested commit without the original result prevents
re-execution and explicitly reports that no result is available.

Reuse `CoordScopeMethod.execute(..., task_id="stable-id")` with the same host
environment and contract to reopen a ledger. Session-level embedding also accepts
explicit `journal_path` and `task_id`. This restores the effect ledger and
evidence; it does not checkpoint the Python stack, replay paid model calls or
restore an external service. Replanning can occur after restart, but grants and
known outcomes retain their durable budgets.

The benchmark CLI creates fresh native episodes and refuses existing run
directories. It does not pair an old ledger with a newly reset benchmark
environment. See [benchmark adapters](benchmarks.md).

## Process boundary and its limits

Workers run installed, trusted interpreter code with `-I`, a filtered environment,
a temporary working directory and JSON-only IPC. Credentials, handlers, the
journal and policy objects stay in the host. Frame size, plan size, model calls,
steps, delegation and loop sizes are bounded. Worker exceptions, malformed frames
and wall-clock timeouts terminate and reap the process.

This is address-space and failure isolation, not a same-user hostile-code sandbox.
It does not confine arbitrary malicious Python, native code, host tool handlers or
the filesystem permissions of that user. Stronger confinement needs a deployment
backend such as AppContainer or a suitably restricted container. A worker timeout
also cannot safely interrupt a synchronous host handler; transports need their
own timeouts. The fixed interpreter and host broker remain trusted code.

## Artifacts and evaluation

Run configs, effective policies, native logs, provider metadata and runtime
journals stay under the ignored run directory. Evidence can contain task data;
SQLite durability is not encryption. Do not publish execution artifacts without
review. Provider request journals record metadata rather than credentials or full
prompt bodies.

Scripted tests validate enforcement and faults, not LLM performance. Missing
provider usage, missing judgments, incomplete execution and infrastructure errors
cannot count as valid task or safety success. Only AgentDojo is implemented today;
other frameworks are references or future adapters.

## Design record

- [Replacement decisions](decisions/0001-host-governed-runtime.md)
- [Runtime source review](references/runtime-design.md)
- [Benchmark source review and extension contract](benchmarks.md)
- [README source review](references/readme-design.md)
- [Historical migration decisions](migration/decisions.md)
