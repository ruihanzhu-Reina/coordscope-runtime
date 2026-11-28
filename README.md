# TeamPermit

**Secure Multi-Agent Execution with Task-Scoped Authorization**

TeamPermit combines instruction/data isolation, cross-agent provenance tracking,
and task-scoped authorization to constrain tool execution across an agent team.

**Current implementation:** [TeamPermit](https://github.com/ruihanzhu-Reina/TeamPermit).
**Historical experiments and earlier methods:** [Legacy research repository](https://github.com/ruihanzhu-Reina/CoordScope).
The installable Python package, import paths, and CLI are named `teampermit`.
For renamed interfaces and output identifiers, see the [package rename notes](docs/migration/teampermit-rename.md).

This project extracts the current `multicamel_governed` method from
[the legacy research repository](https://github.com/ruihanzhu-Reina/CoordScope),
commit `f0a3ba02ccaece21491301d7fb8fec950644575f` on
`feat/folded-runtime-governance`. The old repository remains the historical record.

## Quick start

```powershell
git clone https://github.com/ruihanzhu-Reina/TeamPermit.git
cd TeamPermit
uv sync --extra benchmark
uv run pytest
uv run teampermit check
uv run python examples/offline_payment.py
```

The check, test, and example commands are offline after dependencies are installed. Tests use
explicit scripted completions and real benchmark environments where appropriate;
they are not model-performance measurements.

For a live episode, configure credentials and provider settings in your shell
(see `.env.example`; it is not loaded automatically), then run:

```powershell
uv run teampermit run --suite slack --user-task user_task_2 --clean --model deepseek-flash
```

An attacked episode uses `--attack <registered-name> --injection-task <task-id>`
instead of `--clean`. These commands make paid API calls. No live evaluation was
performed during migration. Results go to ignored `outputs/runs/<run-id>/`.
Existing run directories are never overwritten.

## Where the method lives

| Responsibility | Code |
|---|---|
| Initial authorization | `security/compiler.py`, `security/gateway.py` |
| Role delegation | `agents/session.py`, `agents/roles.py` |
| Instruction/data isolation | `agents/interpreter.py`, `agents/prompts.py` |
| Exact argument/source checks | `security/gateway.py`, `evidence/store.py` |
| Shared receipts and unknown outcomes | `security/gateway.py` |

All paths in the table are relative to `src/teampermit/`. Start reading with
`agents/session.py`, then the interpreter, then the gateway.

## Layout

```text
src/teampermit/       Current algorithm and installable CLI
  agents/            Isolated agents, bounded plans, role contracts
  security/          Manifest, compiler, exact capabilities, read cache
  evidence/          Immutable evidence and provenance
  models/            Fresh JSON requests, provider validation and budgets
  integrations/      Benchmark-specific tools, partitions and trace adapters
  evaluation/        Official episode runner and metrics
tests/               Unit and real-environment integration regressions
examples/            Small, explicitly offline runnable demonstrations
docs/                Architecture, attribution, migration and verification
third_party/         Pinned benchmark package and original license
.github/workflows/   CI for lint, tests and package build
```

## Scope

The isolation design is inspired by Multi-CaMeL, implemented here using a bounded
JSON interpreter rather than Sequrity. The exact-action gateway is inspired by
ToolFence; it does not implement its full persistent transaction engine or cache.
The root has no business tools. Specialists keep host-assigned role permissions.
All business calls pass the same task-local gateway; local reads have a reviewed
cache path. Evidence is data, not authority. Semantic compilation/review can err.

The benchmark adapter preserves the caller's task environment and official judges.
It uses pinned MultiAgentDojo role partitions on the bundled AgentDojo tasks; this
is **not** a claim of revision-equivalence to every upstream MultiAgentDojo release.

See [architecture](docs/architecture.md), [migration decisions](docs/migration/decisions.md),
[upstream references](docs/references/repository-layouts.md), and
[third-party notices](THIRD_PARTY_NOTICES.md).
