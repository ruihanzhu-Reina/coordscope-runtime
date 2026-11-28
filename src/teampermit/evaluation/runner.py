"""Run the caller's benchmark tools and official judges without alternative engines."""

import hashlib
import json
import time
import uuid
from pathlib import Path

from .metrics import official_outcomes, resource_metrics


def _digest(root):
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*.py")):
        digest.update(str(path.relative_to(root)).replace("\\", "/").encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def run_episode(args):
    from agentdojo.attacks.attack_registry import load_attack
    from agentdojo.benchmark import run_task_with_injection_tasks, run_task_without_injection_tasks
    from agentdojo.logging import OutputLogger
    from agentdojo.task_suite.load_suites import get_suite

    from teampermit.integrations.agentdojo.pipeline import MultiCaMeLGovernedPipeline

    run_id = args.run_id or uuid.uuid4().hex
    if not run_id or run_id in {".", ".."} or any(c in run_id for c in "/\\:"):
        raise ValueError("run-id must be a single directory name")
    directory = args.output_dir / run_id
    directory.mkdir(parents=True, exist_ok=False)
    suite = get_suite(args.benchmark_version, args.suite)
    task = suite.get_user_task_by_id(args.user_task)
    if args.attack and args.injection_task not in suite.injection_tasks:
        raise ValueError("Unknown injection task")
    pipeline = MultiCaMeLGovernedPipeline(model=args.model)
    pipeline.bind_suite(suite)
    logdir = directory / "official_logs"
    utility = security = None
    error_status = error = None
    started = time.perf_counter()
    try:
        with OutputLogger(str(logdir)):
            if args.clean:
                utility, security = run_task_without_injection_tasks(
                    suite, pipeline, task, logdir, force_rerun=True, benchmark_version=args.benchmark_version
                )
            else:
                attacker = load_attack(args.attack, suite, pipeline)
                if attacker.is_dos_attack:
                    raise ValueError("DoS requires a separate evaluation protocol")
                utilities, securities = run_task_with_injection_tasks(
                    suite,
                    pipeline,
                    task,
                    attacker,
                    logdir,
                    force_rerun=True,
                    injection_tasks=[args.injection_task],
                    benchmark_version=args.benchmark_version,
                )
                utility = utilities[(args.user_task, args.injection_task)]
                security = securities[(args.user_task, args.injection_task)]
        traces = list(logdir.rglob("*.json"))
        if not traces:
            error_status, error = "JUDGE_ERROR", "No official trace produced"
        for path in traces:
            trace = json.loads(path.read_text(encoding="utf-8"))
            if trace.get("error"):
                error_status, error = "INFRA_ERROR", str(trace["error"])
    except Exception as exc:
        error_status = "JUDGE_ERROR" if pipeline.execution_completed else "INFRA_ERROR"
        error = f"{type(exc).__name__}: {exc}"
    requests = pipeline.request_records
    completed = [request for request in requests if request["status"] == "completed"]
    if not completed or pipeline.provider_fatal_error or any(not r.get("usage_available") for r in completed):
        error_status = error_status or "INFRA_ERROR"
        error = error or "No validated live usage; not a safety result"
    exposed = [request for request in completed if request["matched_injection_keys"]]
    result = dict(
        system="TeamPermit",
        benchmark="multiagentdojo_partition_adapter",
        benchmark_version=args.benchmark_version,
        suite=args.suite,
        task_id=args.user_task,
        attack=args.attack,
        injection_task=args.injection_task,
        condition="clean" if args.clean else "attack",
        model=pipeline.model,
        run_id=run_id,
        error=error,
        source_digest=_digest(Path(__file__).parents[1]),
        source_migration_commit="f0a3ba02ccaece21491301d7fb8fec950644575f",
        benchmark_base_commit="089ed468cf3ed0322acc66b0211f26d9d90dbf60",
        attack_exposed=None if args.clean else True if exposed else "UNKNOWN",
        latency_s=time.perf_counter() - started,
        mock_used=pipeline.mock_used,
        llm_requests=requests,
        agentdojo_runtime_calls=pipeline.runtime_calls,
        metadata=pipeline.last_run_metadata,
        **official_outcomes(
            utility, security, clean=args.clean, error_status=error_status, mock_used=pipeline.mock_used
        ),
        **resource_metrics(requests, mock_used=pipeline.mock_used),
    )
    target = directory / "result.json"
    pending = target.with_suffix(".json.tmp")
    pending.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    pending.replace(target)
    print(
        json.dumps(
            dict(
                result_path=str(target.resolve()),
                run_status=result["run_status"],
                evaluation_valid=result["evaluation_valid"],
            ),
            indent=2,
        )
    )
    return 0 if result["evaluation_valid"] else 1
