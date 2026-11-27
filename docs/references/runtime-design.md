# Runtime design references

Reviewed on 2026-11-27. These sources informed
[ADR-0001](../decisions/0001-host-governed-runtime.md). The implementation is a
local replacement tailored to this repository, not a claim of equivalence to any
upstream system. Links below identify the mechanism actually inspected.

## Durable work and external effects

[Temporal Activity Definition](https://docs.temporal.io/activity-definition)
describes a worker completing an external operation and crashing before reporting
completion. Such work may be retried; the receiver must enforce an idempotency
key. We adopt the distinction between durable local state and external effect
deduplication, but choose conservative unknown outcomes instead of automatic
effect retries.

[DBOS Workflows](https://docs.dbos.dev/python/tutorials/workflow-tutorial) separates
at-least-once step attempts from exactly-once transaction commits.
[DBOS Steps](https://docs.dbos.dev/python/tutorials/step-tutorial) places external
and nondeterministic operations behind step boundaries. Our journal records
effect operations and evidence; it does not implement a durable workflow replay
engine or checkpoint the interpreter's execution cursor.

[Stripe's idempotency protocol](https://docs.stripe.com/api/idempotent_requests)
binds a receiver-side key to the request parameters and saved response. Retention
and retry semantics are provider-specific. The gateway's stable local operation
identity is not a substitute for such a receiver-side contract.

## Capability and transaction accounting

The relevant ToolFence is the authors' repository,
[PolyLiYJ/ToolFence_v2](https://github.com/PolyLiYJ/ToolFence_v2), at commit
`e49c1ba746d0a13e48787a5660a5cf5424e33cf7`.
[transaction_net.py](https://github.com/PolyLiYJ/ToolFence_v2/blob/e49c1ba746d0a13e48787a5660a5cf5424e33cf7/ToolFence_anonymous%203/src/toolfence/transaction_net.py)
uses atomic budget reservations, a persisted dispatched state, operation-bound
receipts and reconciliation. Its typed object references identify instances and
versions. We use those boundary principles; a carried version alone does not
establish external freshness or CAS. No ToolFence code is imported or vendored
by this redesign.

The host-owned structured contract is a deliberate change from the previous
model compiler and concrete-action reviewer. Exact grants and constrained real
source fields are enforced in code. Whether the host chose a contract that
matches the user's intent remains outside that deterministic guarantee.

## Local durability and ownership

[SQLite WAL](https://www.sqlite.org/wal.html) documents commit syncing under
`synchronous=FULL` and WAL's single-host requirement.
[SQLite Atomic Commit](https://www.sqlite.org/atomiccommit.html) describes atomic
local transactions. We use WAL/FULL for local operation accounting and an owner
lock for this single-host runtime. Neither mechanism makes the handler and its
remote service part of the same database transaction; network filesystems and
multi-host coordination are outside this design.

## Resource revisions

[RFC 9110, section 13.1.1](https://www.rfc-editor.org/rfc/rfc9110.html#section-13.1.1)
defines server-evaluated `If-Match` preconditions. A client-side observation
followed by an unconditional write leaves a race. Our stamps retain local
revisions and optional host validators, and our conflict checks cover read/write
dependencies. Production adapters that require atomic resource freshness must
enforce a condition at their backend. Reads have no default cache.

## Data/control isolation and worker processes

[CaMeL: Defeating Prompt Injections by Design](https://arxiv.org/abs/2503.18813)
separates control/data flow and applies capability checks to data use. The
existing bounded JSON interpreter retains that general separation; it is not the
upstream CaMeL or Sequrity implementation. Single-assignment static bindings and
control-tainted delegation checks close two concrete dependency-loss routes in
this interpreter.

[Python isolated mode](https://docs.python.org/3.12/using/cmdline.html#cmdoption-I)
ignores Python environment settings and excludes user site packages. Our fixed
worker also receives a restricted environment and bounded JSON IPC. These
startup controls and process separation do not create an OS security sandbox.
The installed interpreter is trusted code; hostile code needs a separately
designed OS/container boundary. Host tool execution remains outside workers.

## Benchmark architecture

The CLI loads selected benchmark adapters through one configuration-based
runner. Native environments and judge semantics stay with their adapters; host
policy is supplied separately from task answers and attacker goals. Only
AgentDojo is implemented. Source-pinned Inspect AI, AgentLab and BrowserGym
references and the installed-plugin contract are documented in
[benchmark adapters](../benchmarks.md#design-references).

## Evidence and scope

The replacement's fault tests target actual interruption and state transitions,
not simulated LLM success rates. In particular they verify receipt replay,
unknown recovery, owner exclusion, source and control freshness, same-resource
reservation checks and normalization of native tool results. Reopening a task
requires the same real external environment. The CLI starts fresh native
episodes and does not restore benchmark environments from a journal. Historical
migration reports are preserved as historical evidence, not retroactively
rewritten as validation of this design.
