# Migration decisions

Source: `ruihanzhu-Reina/CoordScope`, branch `feat/folded-runtime-governance`,
commit `f0a3ba02ccaece21491301d7fb8fec950644575f`.
The remote `main` observed during migration was `7aac638192c8428b0e53096fb4ac5a036b63ff59`;
using main would have lost the user's latest isolated-agent implementation.
The old checkout and GitHub repository were not modified or deleted.

## Selection criterion

Keep code reachable from the current isolated pipeline, its configuration and
regressions, source attribution, and the pinned benchmark dependency. Exclusion
means "not needed in this new current-method project", not "has no research value".

| Source category | Decision and reason |
|---|---|
| `src/agentdojo_manta/multicamel` | Move into agents and AgentDojo integration modules; remove path injection |
| Current gateway/compiler/evidence/manifest under `upstreams/manta/MAS/self_evolved` | Move into owned security/evidence packages |
| `adapter.py` | Extract real runtime binding/trace projection; replace legacy transport wrappers with one isolated transport |
| `tool_gateway.py` | Retain permissions, locking and reviewed-read cache; remove unreachable old effect/review executor branches |
| `RoleContract` and old `TaskContract` | Keep current role-based semantics directly in one TaskContract; remove unused old agent_0-only policy |
| `providers.py`, `budget.py` | Keep provider checks and cost reservation behavior; historical environment names remain compatible |
| `deepseek_pro.py` | Keep used Pro response validation; remove conversation-history reconstruction from the fresh-request path |
| `metrics.py` | Keep official outcomes, costs/tokens and aggregation; remove topology-specific measurement code |
| `scripts/manta/run_agentdojo_manta.py` | Replace multi-profile script with packaged current-method CLI; no old profile switches |
| `src/agentdojo` | Preserve all tracked code/data byte-for-byte in `third_party/agentdojo`; install separately |
| Historical topology/Folded engines and launch scripts | Exclude from new project; original repository preserves baseline reproducibility |
| `runs`, `reports`, `archive` and old demo assets | Exclude from runtime project; retain original evidence at source commit |
| Cached bytecode, virtual environments, private environment files | Never copy |

## Behavior changes made explicit

- Import paths/package identity become `teampermit`; old compatibility shims and
  `AdapterPaths` are removed, not kept as unused alternate routes.
- The current fresh no-tool provider path is extracted from the old MANTA wrapper.
  There is no mock fallback or hidden retry. Invalid usage/content/tool calls fail
  before they can be treated as successful model calls. Usage validation is stricter.
- Existing provider defaults/sampling environment variables and budget ledgers are
  retained. Historical hardcoded billing rates are not a claim of current prices;
  confirm them before cost-sensitive paid evaluation. No API keys were copied.
- Provider journals record metadata rather than raw prompt/response bodies.
- The role policy now lives directly in `security.policy.TaskContract`; gateway
  permissions still establish which specialist may execute a tool.
- Run metadata uses `teampermit_metadata`, replacing the legacy `manta_run_metadata` key.
- The runner refuses an existing run directory; failed/incomplete runs never count
  as security wins. Task/attack/security judges remain in the unmodified benchmark.

## What is not claimed

No new benchmark score, algorithm improvement, exact equivalence of provider SDK
versions, persistent/distributed ledger, or equivalence to upstream Sequrity.
The new lockfile records this environment. Compare with the old environment before
using results in a controlled experiment.

See `file-map.csv.gz` for every tracked source file's disposition and stable Git blob
identifier, `source-map.json` for migrated paths, and `validation.md` for actual checks.
