# TeamPermit package and command names

The public package, Python imports, and CLI use `teampermit`. The project display
name is **TeamPermit**. Update existing environments and scripts to use:

```powershell
uv sync --frozen --extra benchmark
uv run teampermit check
uv run python -m teampermit --help
uv run python examples/offline_payment.py
```

Python integrations import from `teampermit`, for example:

```python
from teampermit.agents.session import IsolatedSession
```

The wheel is named `teampermit-0.2.0-py3-none-any.whl`. Runtime results identify
the system as `TeamPermit`; the AgentDojo pipeline identifier is
`teampermit-multicamel-governed`, extra pipeline metadata is under
`teampermit_metadata`, and generated fallback call IDs begin with
`teampermit-call-`. Update downstream result consumers to those names. Previously
written execution records are historical evidence and are not rewritten.

The rename covers source paths, imports, package metadata, console scripts,
examples, tests, CI, the lockfile, and documentation. The packaged benchmark's
display description is updated; its Python code, task data, and judges are
unchanged. Historical source URLs and commit identities retain their actual
values so the original implementation and evidence remain traceable.

## Validation

Checked on Windows with Python 3.12.13 on 2026-11-28:

- Fresh installation with `uv sync --frozen --extra benchmark`.
- Full regression suite: 67 tests passed, including module and console entrypoints.
- Ruff lint and formatting checks: passed, 52 Python files checked.
- `teampermit check`: all four benchmark suites matched their specialist roles.
- Offline payment example: two specialists, one authorized payment, one receipt,
  and no external instruction text exposed to planning requests.
- Source distribution and wheel built successfully.
- Wheel installed in a separate environment: package import, console help,
  module help, and payment example passed without the benchmark installed.
- Active source, tests, examples, package metadata, lockfile, and CI contain no
  previous project identifiers; pinned benchmark code and data are unchanged.

No live model API calls or new benchmark performance measurements were made.
