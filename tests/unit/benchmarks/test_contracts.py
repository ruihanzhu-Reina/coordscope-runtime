import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from coordscope.benchmarks import registry
from coordscope.benchmarks.agentdojo.adapter import AgentDojoAdapter
from coordscope.benchmarks.base import BenchmarkOutcome, RunConfig
from coordscope.evaluation.runner import run


class ToyAdapter:
    def check(self):
        return dict(benchmark="toy")

    def run(self, config, method, run_directory):
        if config.options.get("raises"):
            raise RuntimeError("native judge failed")
        if config.options.get("missing_usage"):
            method.request_records.clear()
        if config.options.get("unfinished"):
            method.execution_completed = False
        (run_directory / "native.txt").write_text("native artifact", encoding="utf-8")
        return BenchmarkOutcome(
            task_success=None if config.options.get("missing_judgment") else True,
            condition=config.options.get("condition", "clean"),
            attack_success=config.options.get("attack_success"),
            metadata=dict(private_options=config.options),
            artifacts=dict(trace="native.txt"),
            native_metrics=dict(reward=1.0),
        )


def factory(**kwargs):
    return SimpleNamespace(
        model=kwargs["model"] or "controlled-test-model",
        policy=kwargs["policy"],
        request_records=[dict(status="completed", usage_available=True, token_in=10, token_out=2)],
        runtime_calls=[],
        execution_completed=True,
        mock_used=False,
        provider_fatal_error=None,
        last_run_metadata={},
    )


def install(monkeypatch, entries=None):
    def entry(name, adapter):
        return SimpleNamespace(name=name, load=lambda: adapter)

    monkeypatch.setattr(registry.metadata, "entry_points", lambda **_: entries or [entry("toy", ToyAdapter)])


def test_config_policy_paths_are_relative_to_config_and_options_are_private(tmp_path):
    directory = tmp_path / "configs"
    directory.mkdir()
    (directory / "policy.json").write_text('{"version":1,"grants":[]}', encoding="utf-8")
    path = directory / "run.json"
    options = dict(native_backend="anything", seed=7, nested=dict(values=[1, 2]))
    path.write_text(
        json.dumps(
            dict(
                schema_version=1,
                benchmark="toy",
                task_id="native-task",
                policy="policy.json",
                options=options,
            )
        ),
        encoding="utf-8",
    )
    config = RunConfig.from_file(path)
    assert config.policy == (directory / "policy.json").resolve()
    assert config.options == options


@pytest.mark.parametrize(
    "document",
    [
        '{"schema_version":1,"schema_version":1,"benchmark":"toy","task_id":"x"}',
        '{"schema_version":true,"benchmark":"toy","task_id":"x"}',
        '{"schema_version":1,"benchmark":"toy","task_id":"x","unknown":1}',
        '{"schema_version":1,"benchmark":"toy","task_id":"x","options":{"bad":NaN}}',
    ],
)
def test_bad_config_is_rejected_before_running(tmp_path, document):
    path = tmp_path / "bad.json"
    path.write_text(document, encoding="utf-8")
    with pytest.raises(ValueError):
        RunConfig.from_file(path)


def test_registry_discovery_is_lazy_and_only_selected_extension_loads(monkeypatch):
    loaded = []
    entries = [
        SimpleNamespace(name=name, load=lambda name=name: loaded.append(name) or ToyAdapter)
        for name in ("toy", "another")
    ]
    install(monkeypatch, entries)
    assert registry.list_benchmarks() == ["agentdojo", "another", "toy"]
    assert loaded == []
    assert registry.get_benchmark("toy").check() == dict(benchmark="toy")
    assert loaded == ["toy"]


def test_duplicate_benchmark_names_fail_without_loading(monkeypatch):
    def unexpected_load():
        raise AssertionError("Discovery must not load adapters")

    install(monkeypatch, [SimpleNamespace(name="agentdojo", load=unexpected_load)])
    with pytest.raises(ValueError, match="Duplicate"):
        registry.list_benchmarks()


def test_toy_benchmark_uses_generic_runner_without_agentdojo_code(monkeypatch, tmp_path):
    install(monkeypatch)
    config = RunConfig(1, "toy", "arbitrary-task", options=dict(native_backend="private"))
    result = run(config, tmp_path, "toy-run", method_factory=factory)
    assert result["evaluation_valid"] is True and result["task_success"] is True
    assert result["attack_success"] is None and result["native_metrics"] == dict(reward=1.0)
    assert result["benchmark_metadata"]["private_options"] == config.options
    assert result["tokens"] == 12
    saved = json.loads((tmp_path / "toy-run" / "result.json").read_text(encoding="utf-8"))
    assert saved == result
    assert (tmp_path / "toy-run" / "policy.json").is_file()
    assert not list((tmp_path / "toy-run").glob("*.tmp"))
    assert len(result["source_digest"]) == 64
    with pytest.raises(FileExistsError):
        run(config, tmp_path, "toy-run", method_factory=factory)


@pytest.mark.parametrize(
    "options",
    [
        dict(raises=True),
        dict(missing_usage=True),
        dict(condition="attack"),
        dict(unfinished=True),
        dict(missing_judgment=True),
    ],
)
def test_infra_judge_and_missing_attack_metrics_are_never_safety_success(monkeypatch, tmp_path, options):
    install(monkeypatch)
    result = run(RunConfig(1, "toy", "x", options=options), tmp_path, method_factory=factory)
    assert result["evaluation_valid"] is False
    assert result["task_success"] is result["attack_success"] is None
    assert result["run_status"] in {"INFRA_ERROR", "JUDGE_ERROR"}
    assert result["error"]


def test_mock_runs_are_kept_separate_from_evaluation(monkeypatch, tmp_path):
    install(monkeypatch)

    def mock_factory(**kwargs):
        method = factory(**kwargs)
        method.mock_used = True
        return method

    result = run(RunConfig(1, "toy", "x"), tmp_path, method_factory=mock_factory)
    assert result["run_status"] == "MOCK_SMOKE"
    assert result["evaluation_valid"] is False and result["task_success"] is None


@pytest.mark.parametrize(
    "options",
    [
        {},
        dict(suite="unknown"),
        dict(suite="slack", version="newest"),
        dict(suite="slack", extra=1),
        dict(suite="slack", condition="attack"),
        dict(suite="slack", condition="clean", attack="x"),
    ],
)
def test_agentdojo_rejects_unknown_or_inconsistent_native_options(options):
    with pytest.raises(ValueError):
        AgentDojoAdapter.validate_options(options)


def test_core_check_and_listing_work_when_native_benchmark_import_is_blocked():
    source = Path(__file__).resolve().parents[4] / "src"
    code = (
        "import sys; sys.path.insert(0, sys.argv[1]); import importlib.abc; "
        'exec("class Block(importlib.abc.MetaPathFinder):\\n'
        " def find_spec(self, fullname, path=None, target=None):\\n"
        "  if fullname == 'agentdojo' or fullname.startswith('agentdojo.'): raise ImportError('native blocked')\\n\"); "
        "sys.meta_path.insert(0, Block()); from coordscope.cli import main; "
        "assert main(['benchmarks']) == 0; assert main(['check']) == 0; "
        "assert not any(name == 'agentdojo' or name.startswith('agentdojo.') for name in sys.modules)"
    )
    result = subprocess.run([sys.executable, "-I", "-c", code, str(source)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


def test_unknown_adapter_does_not_construct_a_provider(monkeypatch, tmp_path):
    install(monkeypatch)

    def forbidden_factory(**kwargs):
        raise AssertionError("Unknown adapters must fail before creating a provider")

    result = run(RunConfig(1, "unknown", "x"), tmp_path, method_factory=forbidden_factory)
    assert result["run_status"] == "INFRA_ERROR" and "Unknown benchmark" in result["error"]


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(task_success=True, native_metrics=dict(score=float("nan"))),
        dict(task_success=True, attack_success=True),
        dict(task_success=True, artifacts=dict(trace="../outside.txt")),
    ],
)
def test_adapter_outcomes_reject_ambiguous_or_unserializable_results(kwargs):
    with pytest.raises(ValueError):
        BenchmarkOutcome(**kwargs)


def test_cli_summarizes_different_benchmarks_separately(tmp_path, capsys):
    from coordscope.cli import main

    paths = []
    for name in ("toy", "other"):
        path = tmp_path / f"{name}.json"
        path.write_text(
            json.dumps(
                dict(
                    benchmark=name,
                    evaluation_valid=True,
                    condition="clean",
                    task_success=True,
                )
            ),
            encoding="utf-8",
        )
        paths.append(str(path))
    assert main(["summarize", *paths]) == 0
    result = json.loads(capsys.readouterr().out)
    assert set(result["by_benchmark"]) == {"toy", "other"}
    assert all(row["clean_n"] == 1 for row in result["by_benchmark"].values())


def test_agentdojo_adapter_runs_native_judges_with_shared_method(tmp_path):
    pytest.importorskip("agentdojo")
    from coordscope.runtime.method import CoordScopeMethod
    from tests.integration.agentdojo.test_pipeline import dora_policy, dora_script

    policy_path = tmp_path / "policy.json"
    policy_path.write_text(json.dumps(dora_policy().to_document()), encoding="utf-8")

    def scripted_method(**kwargs):
        return CoordScopeMethod(**kwargs, completion=dora_script())

    result = run(
        RunConfig(1, "agentdojo", "user_task_2", policy=policy_path, options=dict(suite="slack")),
        tmp_path,
        "native",
        method_factory=scripted_method,
    )
    assert result["run_status"] == "MOCK_SMOKE" and result["evaluation_valid"] is False
    assert result["native_metrics"]["official_utility"] is True
    assert result["attack_success"] is None
    assert [row["tool_name"] for row in result["runtime_calls"]] == ["get_webpage", "invite_user_to_slack"]
    assert list((tmp_path / "native" / "official_logs").rglob("*.json"))
