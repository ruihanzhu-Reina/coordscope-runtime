# Current execution architecture

The five presentation modules are responsibilities, not five independent agents.

| Stage | Input | Implementation | Output |
|---|---|---|---|
| Initialize authority | Root request, pinned tool schemas | `security/compiler.py`, `agents/session.py:initialize`, `security/gateway.py:initialize` | Exact, complete, single-use capabilities |
| Delegate | Trusted instruction, role, opaque variables | `agents/session.py:plan/delegate`, `agents/roles.py` | A fresh child context and bounded JSON plan |
| Isolate data | External values and fixed extraction instructions | `agents/interpreter.py:Value/PlanInterpreter`, `agents/session.py:extract`, `evidence/` | Data that retains dependencies and source fields |
| Authorize | Actor, tool, arguments, evidence | `agents/session.py:tool`, `security/gateway.py:call`, `evidence/store.py:resolve` | Denial or a task/version-bound authorization |
| Execute and record | Exact authorization and current state | `security/gateway.py:call/reconcile` | Actual tool result, receipt, committed/unknown state |

```text
CLI -> evaluation.runner -> integrations.agentdojo.pipeline.query
  -> agents.session.IsolatedSession.run
     -> initialize -> security.compiler -> security.gateway.initialize
     -> plan -> agents.interpreter.PlanInterpreter.run
        -> agent -> session.delegate -> fresh child plan/interpreter
        -> extract -> quarantined no-tool completion -> evidence.store
        -> tool -> session.tool -> security.gateway -> caller's real handler
     -> evidence and execution snapshots
  -> official benchmark utility/security checks
```

## Dependency direction

The core `agents`, `security`, and `evidence` packages do not import AgentDojo,
MANTA, LangGraph, a model SDK, or filesystem path hacks. A completion callback and
tool handlers are injected into the session. `integrations/agentdojo` depends on
the core and the optional benchmark package. `models` supplies the real completion
transport. `evaluation` supplies the official episode runner and reports.

## Preserved boundaries

- Planners see trusted tasks and variable names, not external variable values.
- Child/data/tool results retain host-owned dependencies.
- Every child task instruction passes `Value.instruction()`.
- Branches/loops propagate control dependencies; no arbitrary Python execution.
- Root has no business tools; specialists have a fixed partition.
- A single root-task gateway holds exact grants and receipts for all specialists.
- Parameter mismatch against an initial blueprint cannot be overridden by review.
- A source proof establishes value equality/provenance, not truth or user authority.
- State/permission/source checks run again after semantic review.
- `unknown` outcomes block more effects until host reconciliation.

## Deliberate limitations

This is a local bounded JSON interpreter, not the upstream Sequrity backend. The
task graph has one orchestrator level and serial execution. Planner and reviewer
mistakes remain possible. There is no automatic replanning after tool output.
The ledger is in-memory and does not promise distributed exactly-once execution
or crash recovery. Identical effect calls are deduplicated within one task.

## Artifacts and privacy

`outputs/runs/<run-id>/result.json` contains execution metadata and evidence;
`official_logs/` contains the benchmark's own logs. Both can contain task data.
They are ignored by Git. Optional provider journals contain request metadata,
not API keys. `.env` files and budget SQLite files are also ignored.
