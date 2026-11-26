# Migration validation

Verified locally on Windows, Python 3.12.13, 2026-11-27 (Asia/Shanghai).

| Check | Observed result |
|---|---|
| Source checkout status | Clean; original checkout unchanged |
| Dependency install | `uv sync --extra benchmark` completed; `uv.lock` generated |
| Ruff static checks | Passed for source, tests and examples |
| Ruff formatting | 52 Python files checked |
| Offline regression suite | **65 passed, 25 subtests passed** |
| Native role coverage | Banking, Slack, Travel, Workspace all matched |
| Benchmark preservation | **112 tracked code/data files byte-identical** |
| Offline payment demo | Two specialists; one Alice/10 handler invocation; one receipt; external text absent from planning requests |
| CLI | `check`, `run --help`, and root help available |
| Package build | Source distribution and wheel built successfully |
| Independent wheel install | Installed in a fresh environment outside the new repository |
| Wheel-only demo | Passed without AgentDojo or MANTA installed/imported |
| Legacy import search | No MAS, agentdojo_manta, AdapterPaths, sys.path injection, FoldedEngine or SelfEvolvedEngine in application source |

Tests include tainted delegation, parameter substitution, forged provenance,
control dependencies, global action deduplication, concurrent proposals, unknown
effects, provider request isolation, invalid provider output, budget reservations,
metric denominators and the official task/runtime/judge interface.

No live model API calls or full benchmark evaluations were performed. Offline
scripted completions are not ASR/utility measurements. CI configuration was added,
but no remote GitHub Actions run is claimed. Existing billing rates and environment
variable names were preserved, not revalidated as current prices.

The detailed file audit is `file-map.csv.gz` (UTF-8 CSV compressed with gzip), not
a deletion script. Git blob IDs allow source recovery at the recorded commit.
