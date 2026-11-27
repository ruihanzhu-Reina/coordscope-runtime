# Development

Use Python 3.11 or later and `uv sync --extra agentdojo`. Run:

```powershell
uv run ruff check src tests examples
uv run ruff format --check src tests examples
uv run pytest
uv run coordscope check
uv run coordscope check --benchmark agentdojo
uv run python examples/offline_payment.py
uv build
```

Put method changes in `agents`, `security`, `evidence`, or `runtime`, regressions
under matching `tests/unit` directories, and native benchmark code under
`benchmarks/<name>`. Put native checks under `tests/integration/<name>`. Keep CLI
and the evaluation runner independent of optional benchmark imports. See the
[adapter contract](docs/benchmarks.md) before adding another benchmark.
The core imports without the benchmark; install `uv sync` for core-only work and
run `uv run pytest tests/unit`. Treat `third_party/agentdojo` as an immutable pinned
dependency, not a place to fix scores. Update its provenance explicitly when
changing versions. Never commit credentials, execution logs, or model transcripts.

Use temporary paths for fault-injection tests and never call live providers from
tests. Exercise crash-after-dispatch, replay, stale sources, denied authority and
native judge trace fidelity when changing execution boundaries. Lint, the full
offline suite, native adapter checks, the demo and package build are CI checks.
New architectural decisions belong in `docs/decisions`; historical migration
manifests describe an earlier snapshot and must not be rewritten as current facts.
