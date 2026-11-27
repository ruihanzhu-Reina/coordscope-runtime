"""Benchmark-independent run lifecycle, provenance, accounting and result files."""

import hashlib
import json
import time
import uuid
from pathlib import Path

from coordscope.benchmarks.base import BenchmarkOutcome, RunConfig, read_json
from coordscope.benchmarks.registry import get_benchmark
from coordscope.security.policy import ActionPolicy

from .metrics import resource_metrics


def _digest(root):
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*.py")):
        digest.update(str(path.relative_to(root)).replace("\\", "/").encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _save(path, document):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def _make_method(**kwargs):
    from coordscope.runtime.method import CoordScopeMethod

    return CoordScopeMethod(**kwargs)


def run(config, output_dir, run_id=None, *, method_factory=None):
    """Run a fresh native episode; existing run directories are never resumed."""
    config = config if isinstance(config, RunConfig) else RunConfig.from_file(config)
    run_id = uuid.uuid4().hex if run_id is None else run_id
    if type(run_id) is not str or not run_id or run_id in {".", ".."} or any(c in run_id for c in "/\\:"):
        raise ValueError("run-id must be a single directory name.")
    directory = Path(output_dir).resolve() / run_id
    directory.mkdir(parents=True, exist_ok=False)
    _save(directory / "config.json", config.to_document())
    method = None
    policy = None
    outcome = BenchmarkOutcome(None, error_status="INFRA_ERROR", error="Run did not start.")
    started = time.perf_counter()
    try:
        policy = ActionPolicy.from_document(read_json(config.policy)) if config.policy else ActionPolicy.exact([])
        _save(directory / "policy.json", policy.to_document())
        adapter = get_benchmark(config.benchmark)
        method = (method_factory or _make_method)(model=config.model, policy=policy, journal_dir=directory / "journal")
        outcome = adapter.run(config, method, directory)
        if not isinstance(outcome, BenchmarkOutcome):
            raise TypeError("Adapter must return BenchmarkOutcome.")
    except Exception as exc:
        outcome = BenchmarkOutcome(
            None,
            error_status="JUDGE_ERROR" if getattr(method, "execution_completed", False) else "INFRA_ERROR",
            error=f"{type(exc).__name__}: {exc}",
        )
    requests = list(getattr(method, "request_records", []))
    mock_used = bool(getattr(method, "mock_used", False))
    completed = [row for row in requests if row.get("status") == "completed"]
    usage_valid = bool(completed) and all(
        row.get("status") == "completed"
        and row.get("usage_available") is True
        and type(row.get("token_in")) is int
        and row["token_in"] >= 0
        and type(row.get("token_out")) is int
        and row["token_out"] >= 0
        for row in requests
    )
    error_status, error = outcome.error_status, outcome.error
    if not mock_used and (
        not usage_valid
        or getattr(method, "provider_fatal_error", None)
        or not getattr(method, "execution_completed", False)
    ):
        error_status = error_status or "INFRA_ERROR"
        error = error or "Missing validated provider usage; this run is not an evaluation result."
    if error is not None and error_status is None:
        error_status = "INFRA_ERROR"
    if outcome.task_success is None and error_status is None:
        error_status, error = "JUDGE_ERROR", "Native judge did not report task success."
    valid = error_status is None and not mock_used and outcome.task_success is not None
    if outcome.condition == "attack" and outcome.attack_success is None:
        valid = False
        error_status = error_status or "JUDGE_ERROR"
        error = error or "Attacked episode did not report a native attacker-success judgment."
    result = dict(
        schema_version=1,
        system="CoordScope Runtime",
        benchmark=config.benchmark,
        task_id=config.task_id,
        model=getattr(method, "model", config.model),
        run_id=run_id,
        condition=outcome.condition,
        config=config.to_document(),
        policy_fingerprint=policy.fingerprint if policy else None,
        source_digest=_digest(Path(__file__).parents[1]),
        latency_s=time.perf_counter() - started,
        evaluation_valid=valid,
        mock_used=mock_used,
        run_status=error_status
        or ("MOCK_SMOKE" if mock_used else "SUCCESS" if outcome.task_success else "TASK_FAILED"),
        error=error,
        task_success=outcome.task_success if valid else None,
        attack_success=outcome.attack_success if valid else None,
        attack_exposed=outcome.attack_exposed,
        attack_status="NOT_APPLICABLE"
        if outcome.condition == "clean"
        else "INVALID_EVALUATION"
        if not valid
        else "NOT_REPORTED"
        if outcome.attack_success is None
        else "ATTACK_SUCCEEDED"
        if outcome.attack_success
        else "ATTACK_FAILED",
        native_metrics=outcome.native_metrics,
        benchmark_metadata=outcome.metadata,
        artifacts=outcome.artifacts,
        llm_requests=requests,
        runtime_calls=list(getattr(method, "runtime_calls", [])),
        metadata=getattr(method, "last_run_metadata", {}),
        **resource_metrics(requests, mock_used=mock_used),
    )
    _save(directory / "result.json", result)
    return result
