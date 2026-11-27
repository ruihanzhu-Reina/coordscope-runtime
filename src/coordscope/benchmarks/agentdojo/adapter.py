"""Native AgentDojo attacks, environments and official judges."""

import json

from coordscope.benchmarks.base import BenchmarkOutcome
from coordscope.evaluation.metrics import official_outcomes

_SUITES = ("banking", "slack", "travel", "workspace")
_VERSIONS = {"v1", "v1.1", "v1.1.1", "v1.1.2", "v1.2", "v1.2.1", "v1.2.2"}


class AgentDojoAdapter:
    @staticmethod
    def validate_options(options):
        if type(options) is not dict or set(options) - {"suite", "version", "condition", "attack", "injection_task"}:
            raise ValueError("Unsupported AgentDojo options.")
        if options.get("suite") not in _SUITES:
            raise ValueError("AgentDojo requires a known suite.")
        version = options.get("version", "v1.2.2")
        if type(version) is not str or version not in _VERSIONS:
            raise ValueError("Unsupported pinned AgentDojo version.")
        condition = options.get("condition", "clean")
        if type(condition) is not str or condition not in {"clean", "attack"}:
            raise ValueError("AgentDojo condition must be clean or attack.")
        if condition == "clean" and ("attack" in options or "injection_task" in options):
            raise ValueError("Clean episodes cannot configure an attack or injection task.")
        if condition == "attack" and any(
            type(options.get(key)) is not str or not options[key] for key in ("attack", "injection_task")
        ):
            raise ValueError("Attacked episodes require attack and injection_task.")

    def check(self):
        from agentdojo.task_suite.load_suites import get_suite

        from .partitions import match_partition

        coverage = {}
        for name in _SUITES:
            suite = get_suite("v1.2.2", name)
            _, roles = match_partition({tool.name for tool in suite.tools})
            coverage[name] = [role.name for role in roles]
        return dict(benchmark="agentdojo", version="v1.2.2", role_coverage=coverage)

    def run(self, config, method, run_directory):
        self.validate_options(config.options)
        from agentdojo.attacks.attack_registry import load_attack
        from agentdojo.benchmark import run_task_with_injection_tasks, run_task_without_injection_tasks
        from agentdojo.logging import OutputLogger
        from agentdojo.task_suite.load_suites import get_suite

        from .pipeline import CoordScopePipeline

        options = config.options
        version = options.get("version", "v1.2.2")
        condition = options.get("condition", "clean")
        suite = get_suite(version, options["suite"])
        task = suite.get_user_task_by_id(config.task_id)
        if condition == "attack" and options["injection_task"] not in suite.injection_tasks:
            raise ValueError("Unknown AgentDojo injection task.")
        pipeline = CoordScopePipeline(method=method)
        pipeline.bind_suite(suite)
        logdir = run_directory / "official_logs"
        utility = security = None
        error_status = error = None
        try:
            with OutputLogger(str(logdir)):
                if condition == "clean":
                    utility, security = run_task_without_injection_tasks(
                        suite, pipeline, task, logdir, force_rerun=True, benchmark_version=version
                    )
                else:
                    attacker = load_attack(options["attack"], suite, pipeline)
                    if attacker.is_dos_attack:
                        raise ValueError("DoS requires a separate evaluation protocol.")
                    utilities, securities = run_task_with_injection_tasks(
                        suite,
                        pipeline,
                        task,
                        attacker,
                        logdir,
                        force_rerun=True,
                        injection_tasks=[options["injection_task"]],
                        benchmark_version=version,
                    )
                    key = (config.task_id, options["injection_task"])
                    utility, security = utilities[key], securities[key]
            traces = list(logdir.rglob("*.json"))
            if not traces:
                error_status, error = "JUDGE_ERROR", "No official trace produced."
            for path in traces:
                trace = json.loads(path.read_text(encoding="utf-8"))
                if trace.get("error"):
                    error_status, error = "INFRA_ERROR", str(trace["error"])
        except Exception as exc:
            error_status = "JUDGE_ERROR" if method.execution_completed else "INFRA_ERROR"
            error = f"{type(exc).__name__}: {exc}"
        native = official_outcomes(
            utility, security, clean=condition == "clean", error_status=error_status, mock_used=method.mock_used
        )
        completed = [request for request in method.request_records if request.get("status") == "completed"]
        exposure = (
            None
            if condition == "clean"
            else (True if any(request.get("matched_injection_keys") for request in completed) else "UNKNOWN")
        )
        return BenchmarkOutcome(
            task_success=utility,
            condition=condition,
            attack_success=security if condition == "attack" else None,
            attack_exposed=exposure,
            native_metrics={key: native[key] for key in ("official_utility", "official_security")},
            metadata=dict(
                version=version,
                suite=options["suite"],
                options=options,
                benchmark_base_commit="089ed468cf3ed0322acc66b0211f26d9d90dbf60",
                partition_upstream_commit="e71647382155dc6949d6ccf9a9d7ec7cf429b856",
            ),
            artifacts=dict(official_logs="official_logs"),
            error_status=error_status,
            error=error,
        )
