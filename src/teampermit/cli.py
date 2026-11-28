"""Small CLI: offline inspection, official episodes, and metric summaries."""

import argparse
import json
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(prog="teampermit")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check", help="Check package imports and native role coverage without API calls")
    run = commands.add_parser("run", help="Run one real benchmark episode (uses the configured provider)")
    run.add_argument("--suite", choices=["banking", "slack", "travel", "workspace"], required=True)
    run.add_argument("--user-task", required=True)
    run.add_argument("--benchmark-version", default="v1.2.2")
    condition = run.add_mutually_exclusive_group(required=True)
    condition.add_argument("--clean", action="store_true")
    condition.add_argument("--attack")
    run.add_argument("--injection-task")
    run.add_argument("--model")
    run.add_argument("--run-id")
    run.add_argument("--output-dir", type=Path, default=Path("outputs/runs"))
    summary = commands.add_parser("summarize", help="Summarize explicitly selected episode results")
    summary.add_argument("results", type=Path, nargs="+")
    args = parser.parse_args(argv)
    if args.command == "summarize":
        from teampermit.evaluation.metrics import summarize

        rows = [json.loads(path.read_text(encoding="utf-8")) for path in args.results]
        print(json.dumps(summarize(rows), ensure_ascii=False, indent=2))
        return 0
    if args.command == "check":
        from agentdojo.task_suite.load_suites import get_suite

        from teampermit.agents.session import IsolatedSession
        from teampermit.integrations.agentdojo.partitions import match_partition

        coverage = {}
        for name in ("banking", "slack", "travel", "workspace"):
            suite = get_suite("v1.2.2", name)
            _, roles = match_partition({tool.name for tool in suite.tools})
            coverage[name] = [role.name for role in roles]
        print(json.dumps(dict(engine=IsolatedSession.__name__, role_coverage=coverage), indent=2))
        return 0
    if (args.clean and args.injection_task) or (args.attack and not args.injection_task):
        parser.error("Use --clean alone, or --attack together with --injection-task")
    from teampermit.evaluation.runner import run_episode

    return run_episode(args)
