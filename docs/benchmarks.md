# Benchmark adapters and the shared runner

`coordscope run` accepts the same JSON configuration envelope for every adapter.
The runner owns the output directory, host policy snapshot, method construction,
source digest, provider accounting and atomic result file. An adapter owns its
native environment, attacks, tool bindings, task loading and official judges.
It must not derive authorization from expected answers or attacker goals.

```powershell
uv run coordscope benchmarks
uv run coordscope check
uv run coordscope check --benchmark agentdojo
uv run coordscope run --config configs/agentdojo/slack-clean.json --output-dir outputs/runs --run-id slack-001
```

`benchmarks` and the default `check` do not import optional native benchmark
packages. `check --benchmark agentdojo` checks the installed AgentDojo dependency
and four pinned role partitions, without model API calls. A `run` uses the
configured provider and can make paid requests.

## Run configuration

```json
{
  "schema_version": 1,
  "benchmark": "agentdojo",
  "task_id": "user_task_2",
  "model": "deepseek-chat",
  "policy": "../policies/read-only.json",
  "options": {
    "suite": "slack",
    "version": "v1.2.2",
    "condition": "clean"
  }
}
```

`schema_version`, `benchmark` and `task_id` are required. `model` is optional and
uses the configured provider's model when omitted. `policy` is a host-reviewed
structured policy file, resolved relative to the configuration file rather than
the current working directory. Missing/null policy means no effect grants.
Unknown top-level fields, duplicate JSON keys and non-finite numbers are errors.
`options` is a JSON object interpreted only by the selected adapter.

The included read-only policy has no effect grants. The Slack example demonstrates
configuration and result plumbing; it cannot authorize web navigation or inviting
a user and is not a claim that the native task will pass. Supply a reviewed policy
covering the intended effects to evaluate that workflow. The benchmark adapter
never writes a policy from the task's expected answer.

AgentDojo accepts only `suite`, `version`, `condition`, `attack`, and
`injection_task`. Suites are banking/slack/travel/workspace. Supported versions
match the bundled package: v1, v1.1, v1.1.1, v1.1.2, v1.2, v1.2.1 and v1.2.2.
Clean episodes cannot include attack fields. An attacked episode sets
`condition: "attack"` and supplies both a registered attack name and an existing
injection task ID. DoS needs a separate protocol and is rejected here.

## Run files and score meaning

Each invocation creates a new directory; an existing `--run-id` is rejected.
There is no attempt to reconstruct an old native environment from a journal.

```text
outputs/runs/<run-id>/
  config.json       Resolved invocation
  policy.json       Effective structured policy
  journal/          Host method execution journals
  official_logs/    AgentDojo-native logs, when using that adapter
  result.json       Shared result envelope, written by atomic replacement
```

`result.json` records schema version, benchmark/task, model, source digest,
policy fingerprint, run status, resource accounting, method metadata and adapter
artifacts. Native judge values remain under `native_metrics`. The adapter
explicitly maps a native task judgment to `task_success`; an optional
`attack_success` means the attacker's stated goal was achieved. AgentDojo's native
`security=True` means attacker success on attacked episodes; its clean sentinel
never becomes attack success. Other native safety/reward values are not silently
converted into attack success.

Infrastructure errors, judge errors, missing judgments, unfinished execution,
missing provider usage and scripted completions cannot count as valid benchmark
or safety successes. They retain diagnostic status and artifacts. Existing
`summarize` computes episode-level task/attack rates for explicit clean/attack
records and groups different benchmark names instead of merging their rates.
It does not establish that different benchmarks have comparable attacks.

## Add an adapter

Implement `BenchmarkAdapter` from `coordscope.benchmarks.base`:

```python
class ExampleAdapter:
    def check(self) -> dict:
        return {"benchmark": "example"}

    def run(self, config, method, run_directory):
        # Load/reset the native environment; bind host-owned tools and roles.
        # answer = method.execute(user_request, tools, specs, resources=...)
        # Use the native judge and store native artifacts under run_directory.
        return BenchmarkOutcome(task_success=native_result, native_metrics={...})
```

The reusable method is `coordscope.runtime.method.CoordScopeMethod`; it receives
the model, host policy and journal directory from the runner. A native adapter
does not own a second agent algorithm. Register an adapter factory through an
installed package entry point:

```toml
[project.entry-points."coordscope.benchmarks"]
example = "my_package.adapter:ExampleAdapter"
```

Discovery lists names without loading adapters. Selecting a name imports only
that factory. Duplicate names, including a collision with the built-in
`agentdojo`, are rejected. A toy extension test exercises the full shared runner
without AgentDojo imports.

Only AgentDojo is implemented. BrowserGym, AgentLab and Inspect AI are design
references, not integrations shipped by this repository.

## Design references

Reviewed upstream HEADs on 2026-11-27:

- [Inspect AI Task](https://github.com/UKGovernmentBEIS/inspect_ai/blob/a1175d932c8ddd95f5c59ba52f69edd6c079c354/src/inspect_ai/_eval/task/task.py)
  separates dataset, solver, scorer and execution configuration. This repository
  similarly keeps the method separate from native scoring.
- [Inspect AI entry points](https://github.com/UKGovernmentBEIS/inspect_ai/blob/a1175d932c8ddd95f5c59ba52f69edd6c079c354/src/inspect_ai/_util/entrypoints.py)
  supplies a concrete installed-extension discovery reference. Our registry loads
  only the selected adapter and rejects name collisions.
- [AgentLab studies](https://github.com/ServiceNow/AgentLab/blob/8488c564eea0525aaff5dea189bb03a9b529546e/src/agentlab/experiments/study.py)
  separates agent configuration and benchmark orchestration and treats native
  environment dependencies explicitly. Its study-wide scheduling/relaunch system
  is outside this single-episode runner's scope.
- [BrowserGym Benchmark](https://github.com/ServiceNow/BrowserGym/blob/62a678feefaff0f93e9bab03f51c5402a1e1db00/browsergym/experiments/src/browsergym/experiments/benchmark/base.py)
  models task sets, backends and metadata within benchmark code. Our generic core
  likewise does not hard-code every benchmark's native options.
