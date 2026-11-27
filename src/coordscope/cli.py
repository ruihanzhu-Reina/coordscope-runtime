"""One configuration-based entry point for installed benchmark adapters."""

import argparse
import json
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(prog="coordscope")
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check", help="Check core imports, or one optional native benchmark")
    check.add_argument("--benchmark")
    commands.add_parser("benchmarks", help="List adapters without importing their native dependencies")
    run = commands.add_parser("run", help="Run one fresh benchmark episode from a JSON configuration")
    run.add_argument("--config", type=Path, required=True)
    run.add_argument("--output-dir", type=Path, default=Path("outputs/runs"))
    run.add_argument("--run-id")
    summary = commands.add_parser("summarize", help="Summarize explicitly selected result files")
    summary.add_argument("results", type=Path, nargs="+")
    args = parser.parse_args(argv)
    try:
        if args.command == "summarize":
            from coordscope.evaluation.metrics import summarize

            rows = [json.loads(path.read_text(encoding="utf-8")) for path in args.results]
            groups = {}
            for row in rows:
                groups.setdefault(row.get("benchmark", "legacy_unspecified"), []).append(row)
            result = (
                summarize(rows)
                if len(groups) == 1
                else dict(by_benchmark={name: summarize(group) for name, group in sorted(groups.items())})
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.command in {"check", "benchmarks"}:
            from coordscope.benchmarks.registry import get_benchmark, list_benchmarks

            if args.command == "benchmarks":
                result = dict(benchmarks=list_benchmarks())
            elif args.benchmark:
                result = get_benchmark(args.benchmark).check()
            else:
                from coordscope.agents.session import IsolatedSession
                from coordscope.security.policy import ActionPolicy

                result = dict(
                    engine=IsolatedSession.__name__, policy=ActionPolicy.__name__, benchmarks=list_benchmarks()
                )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        from coordscope.evaluation.runner import run

        result = run(args.config, args.output_dir, args.run_id)
        print(
            json.dumps(
                dict(
                    result_path=str((args.output_dir / result["run_id"] / "result.json").resolve()),
                    run_status=result["run_status"],
                    evaluation_valid=result["evaluation_valid"],
                ),
                indent=2,
            )
        )
        return 0 if result["evaluation_valid"] else 1
    except (OSError, ValueError, ImportError, TypeError) as exc:
        parser.exit(2, f"coordscope: {exc}\n")
