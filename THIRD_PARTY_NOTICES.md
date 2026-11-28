# Third-party notices

## AgentDojo benchmark

The source under `third_party/agentdojo` is preserved from the TeamPermit checkout
at `f0a3ba02ccaece21491301d7fb8fec950644575f`. Its MIT license and original copyright
holders are retained in `third_party/agentdojo/LICENSE`. The original root MIT
license is also retained; migration does not replace the original copyright.

## MultiAgentDojo role partitions

`src/teampermit/integrations/agentdojo/partitions.py` derives its role/tool data from
`james-pete/multiagentdojo` commit `e71647382155dc6949d6ccf9a9d7ec7cf429b856`.
The full notice is in `docs/references/multiagentdojo-license.md`.

## Methodological references

Multi-CaMeL's communication isolation and ToolFence's authorization boundaries
informed this implementation. Their complete backends are not embedded here.
Consult `docs/references/repository-layouts.md` for pinned source links and the
distinction between direct reuse and independent implementation.
