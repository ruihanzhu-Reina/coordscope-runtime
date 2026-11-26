# Repository layout research

Inspected the actual GitHub directory trees on 2026-11-27 (Asia/Shanghai).
These projects do not share one mandatory "large-project folder order". Their
useful commonality is separation of runtime code, tests, documentation, examples,
and development automation. CoordScope adopts that separation without copying
unneeded services, deployment stacks, or empty layers.

| Repository inspected | Concrete observation | CoordScope decision |
|---|---|---|
| [Inspect AI root](https://github.com/UKGovernmentBEIS/inspect_ai/tree/main), [source](https://github.com/UKGovernmentBEIS/inspect_ai/tree/main/src/inspect_ai), [tests](https://github.com/UKGovernmentBEIS/inspect_ai/tree/main/tests) | `src/inspect_ai` contains domain modules such as `agent`, `model`, `tool`, `scorer`; tests reflect responsibilities; docs/examples/CI live separately | Installable `src/coordscope` package with focused responsibility modules and unit/integration tests |
| [Pydantic AI root](https://github.com/pydantic/pydantic-ai/tree/main), [slim package](https://github.com/pydantic/pydantic-ai/tree/main/pydantic_ai_slim) | Runtime packages, examples, docs, tests and scripts are explicit; the slim package has its own packaging metadata | Keep core algorithm separate from optional benchmark integration; use pyproject/lock rather than sys.path injection |
| [MultiAgentDojo root](https://github.com/james-pete/multiagentdojo/tree/main), [source](https://github.com/james-pete/multiagentdojo/tree/main/src/agentdojo) | Pipeline, attacks, task suites, runtime and data are distinct modules | Keep the complete pinned benchmark as a separate dependency; do not move its attacks/judges into our defense code |

## Method sources, distinct from directory inspiration

- [Multi-CaMeL role/protocol source](https://github.com/james-pete/multiagentdojo/blob/e71647382155dc6949d6ccf9a9d7ec7cf429b856/src/agentdojo/agent_pipeline/multi_agent.py): role partition directly reused; protocol locally reimplemented.
- [ToolFence guarded boundary](https://github.com/PolyLiYJ/ToolFence_v2/blob/e49c1ba746d0a13e48787a5660a5cf5424e33cf7/ToolFence_anonymous%203/src/toolfence/guarded_net.py): conceptual reference for authorization/reservation. Its engine is not vendored or claimed as our invention.

Root files are conventional metadata. File browsers may sort names alphabetically;
numeric folder prefixes would complicate imports without improving architecture.
