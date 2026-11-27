# README design references

Reviewed on 2026-11-27. This is a record of actual upstream README observations
and local editorial decisions, not a claim that CoordScope implements those
projects' features. The links below point to the official source READMEs. Their
contents may change after this review.

## Audience and reading path

The primary readers are researchers assessing an execution-boundary method and
developers integrating it with tools or benchmarks. Their first questions are:
what runs, how to try it locally, where authority lives, and what is actually
integrated. The README answers those in that order, then points contributors to
the project map and detailed guides. English is the default; a corresponding
Chinese README uses the same commands, code example and scope statements.

## Upstream observations

| Official README | Visual materials and structure observed | Adopted here | Left out |
|---|---|---|---|
| [Pydantic AI](https://github.com/pydantic/pydantic-ai/blob/main/README.md) | Light/dark SVG wordmarks and SVG badges precede positioning, usage routes, rationale and worked examples; documentation carries the depth | Short opening, direct usage path, a small code example, links to detailed guides | Product/ecosystem breadth and badges for claims we cannot substantiate |
| [LangGraph](https://github.com/langchain-ai/langgraph/blob/main/README.md) | Light/dark SVG logo and badges; precise positioning leads to installation, reasons to use it, ecosystem and documentation | One clear sentence, brief installation, navigation rather than an exhaustive first page | Customer claims, deployment guarantees and social/download counters |
| [Inspect AI](https://github.com/UKGovernmentBEIS/inspect_ai/blob/main/README.md) | SVG institutional logo, compact scope, documentation entry, then concrete development setup | Restrained language and contributor commands that match the checkout | Institutional branding and an unsupported catalog-size claim |
| [ToolFence v2](https://github.com/PolyLiYJ/ToolFence_v2/blob/main/README.md) | A PNG runtime overview introduces authorization and receipts; overview, source-map table, installation, offline examples, benchmarks and concepts follow | One architecture overview, explicit host boundary, code-to-responsibility map and offline/live separation | Copying its diagram, model compiler/judge boxes, capability-cache features that this runtime does not implement |
| [AgentLab](https://github.com/ServiceNow/AgentLab/blob/main/README.md) | SVG badges and a raster overview show the BrowserGym ecosystem; supported benchmarks precede setup, experiment launch, analysis, new-agent integration and reproducibility | Explain shared execution and native benchmark ownership; state shipped adapters separately from extension points | A large supported-benchmark table, leaderboard and scale claims when only one adapter ships |
| [CaMeL](https://github.com/google-research/camel-prompt-injection/blob/main/README.md) | Text-only research entry: paper/authors, artifact scope, prerequisites, AgentDojo evaluation, FAQ and tests | Preserve the distinction between research evidence, local mechanism tests and current capabilities | Leading with a long disclaimer or making the README primarily a paper-reproduction CLI guide |
| [OpenHands / Agent Canvas](https://github.com/All-Hands-AI/OpenHands/blob/main/README.md) | PNG wordmark and UI screenshot, centered positioning and navigation, then deployment routes, architecture and documentation | A clean centered name, lightweight navigation and a visual appropriate to the project | A fake product screenshot, deployment options or a UI that this runtime does not have |

Upstream prose and assets were not copied. The comparison concerns section
ordering, information density and choice of visual, rather than adopting the
projects' marketing language.

## Local decisions

- **Try the mechanism first.** Quick start uses the offline payment demo and
  import/adapter checks. Model-backed benchmark execution appears separately.
- **Draw the execution boundary.** The original
  [`runtime-overview.svg`](../assets/runtime-overview.svg) places the model
  transport, policy, broker and ledger in the host. Separate interpreter workers
  use JSON RPC; the host invokes native tools. It includes no model reviewer or
  policy compiler, because neither may issue grants in this design.
- **Keep the adapter claim visible.** AgentDojo has a solid shipped-adapter box;
  external adapters use a dashed box explicitly marked as not shipped. Both use
  the same runtime. Native environments and judges remain adapter concerns.
- **Use truthful, limited badges.** Python 3.11+ and MIT come directly from
  `pyproject.toml` and `LICENSE`. There are no PyPI, coverage, performance, SOTA or
  production-readiness badges.
- **Keep the data path readable.** One exact host grant illustrates the API;
  full session construction stays in the runnable example. Detailed recovery and
  concurrency boundaries belong in the architecture guide.
- **Retain provenance without a historical preface.** The old research
  repository is linked near the end, with an explicit statement that its scores
  do not describe this revised runtime. Migration details stay in their existing
  documentation directory.

## Asset and verification

`runtime-overview.svg` is editable vector source with a `viewBox`, accessible
`title` and `desc`, embedded styles and local vector shapes only. It uses no
scripts, external images or copied logos. A light background is intentional so
the diagram retains readable contrast on both light and dark repository pages.

The SVG is rendered to a temporary PNG outside the repository for visual review.
README commands and policy snippets are checked against the actual CLI,
configuration files and package metadata. Local file links are checked for
existence. The included Slack run remains accurately described as a live,
read-only-policy plumbing example that cannot authorize the invitation task.
