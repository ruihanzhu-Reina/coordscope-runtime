# Development

Use Python 3.12 and `uv sync --extra benchmark`. Run:

```powershell
uv run ruff check src tests examples
uv run ruff format --check src tests examples
uv run pytest
uv run coordscope check
uv build
```

Put algorithm changes in `src/coordscope`, regressions under the matching
`tests/unit` directory, and benchmark-specific checks under `tests/integration`.
The core imports without the benchmark; install `uv sync` for core-only work and
run `uv run pytest tests/unit`. Treat `third_party/agentdojo` as an immutable pinned
dependency, not a place to fix scores. Update its provenance explicitly when
changing versions. Never commit credentials, execution logs, or model transcripts.
