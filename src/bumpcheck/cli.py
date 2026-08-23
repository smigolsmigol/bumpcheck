"""Command-line interface for Bumpcheck."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from .capture import CaptureError, Watch, capture, capture_requirements
from .compare import compare, describe_outcome

DEFAULT_WATCHES: tuple[Watch, ...] = (
    ("pydantic", "pydantic"),
    ("pydantic-core", "pydantic_core"),
)
DEFAULT_PYTHON_VERSION = f"{sys.version_info.major}.{sys.version_info.minor}"


def _watch(value: str) -> Watch:
    distribution, separator, module = value.partition(":")
    if not distribution:
        raise argparse.ArgumentTypeError("watch must name a distribution")
    return distribution, module if separator else distribution.replace("-", "_")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bumpcheck",
        description="Catch Pydantic runtime behavior changes before a dependency bump.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    check = subparsers.add_parser("check", help="capture and compare one contract case")
    check.add_argument("case", type=Path)
    check.add_argument(
        "--inputs",
        type=Path,
        help="replay JSON, .jsonl/.ndjson, or Pydantic Evals inputs through run(value)",
    )
    baseline = check.add_mutually_exclusive_group(required=True)
    baseline.add_argument("--baseline", metavar="REQUIREMENT")
    baseline.add_argument("--baseline-python")
    candidate = check.add_mutually_exclusive_group(required=True)
    candidate.add_argument("--candidate", metavar="REQUIREMENT")
    candidate.add_argument("--candidate-python")
    check.add_argument("--exact", action="store_true")
    check.add_argument("--json", action="store_true", dest="as_json")
    check.add_argument(
        "--no-watch",
        action="store_true",
        help="record interpreter provenance without requiring a distribution",
    )
    check.add_argument("--timeout", type=float, default=30.0)
    check.add_argument("--uv", default="uv", help="uv executable used for requirement targets")
    check.add_argument(
        "--python-version",
        default=DEFAULT_PYTHON_VERSION,
        help=f"Python version used for requirement targets (default: {DEFAULT_PYTHON_VERSION})",
    )
    check.add_argument(
        "--with",
        action="append",
        default=[],
        dest="extra_requirements",
        metavar="REQUIREMENT",
        help="install the same requirement or local project in both targets; repeat for more",
    )
    check.add_argument(
        "--watch",
        action="append",
        default=None,
        type=_watch,
        metavar="DIST[:MODULE]",
        help="add to the default Pydantic watches; repeat for more distributions",
    )
    check.add_argument(
        "--only-watch",
        action="append",
        default=None,
        type=_watch,
        metavar="DIST[:MODULE]",
        help="replace the default Pydantic watches; repeat for more distributions",
    )
    return parser


def _environment_line(label: str, artifact: dict[str, object]) -> str:
    environment = artifact["environment"]
    distributions = environment["distributions"]
    if not distributions:
        return f"{label} python={environment['python_version']} @ {environment['executable']}"
    packages = ", ".join(
        f"{package['distribution']}={package['version']}" for package in distributions
    )
    return f"{label} {packages} @ {environment['executable']}"


def _check(args: argparse.Namespace) -> int:
    if args.no_watch and (args.watch is not None or args.only_watch is not None):
        print("ERROR --no-watch cannot be combined with another watch option", file=sys.stderr)
        return 2
    if args.watch is not None and args.only_watch is not None:
        print("ERROR --watch cannot be combined with --only-watch", file=sys.stderr)
        return 2
    if args.no_watch:
        watches = ()
    elif args.only_watch is not None:
        watches = tuple(args.only_watch)
    else:
        watches = (*DEFAULT_WATCHES, *(args.watch or ()))
    try:
        if args.baseline is None:
            baseline = capture(
                args.baseline_python,
                args.case,
                inputs=args.inputs,
                watches=watches,
                timeout=args.timeout,
            )
        else:
            baseline = capture_requirements(
                (args.baseline, *args.extra_requirements),
                args.case,
                inputs=args.inputs,
                watches=watches,
                timeout=args.timeout,
                uv=args.uv,
                python_version=args.python_version,
            )
        if args.candidate is None:
            candidate = capture(
                args.candidate_python,
                args.case,
                inputs=args.inputs,
                watches=watches,
                timeout=args.timeout,
            )
        else:
            candidate = capture_requirements(
                (args.candidate, *args.extra_requirements),
                args.case,
                inputs=args.inputs,
                watches=watches,
                timeout=args.timeout,
                uv=args.uv,
                python_version=args.python_version,
            )
        report = compare(baseline, candidate, exact=args.exact)
    except (CaptureError, ValueError) as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 2

    if args.as_json:
        print(json.dumps(report, ensure_ascii=True, sort_keys=True, separators=(",", ":")))
    else:
        print(_environment_line("BASELINE", baseline))
        print(_environment_line("CANDIDATE", candidate))
        case_name = baseline["case"]["name"]
        if report["changed"]:
            batch = report["batch"]
            if batch is not None and batch["changes"]:
                first = batch["changes"][0]
                before = describe_outcome(first["baseline"])
                after = describe_outcome(first["candidate"])
                print(
                    f"CHANGED {case_name}: {len(batch['changes'])}/{batch['total']} inputs; "
                    f"first {first['name']}: {before} -> {after}"
                )
            elif batch is not None:
                print(f"CHANGED {case_name}: batch-level warnings or captured output changed")
            else:
                before = describe_outcome(report["baseline_view"]["outcome"])
                after = describe_outcome(report["candidate_view"]["outcome"])
                print(f"CHANGED {case_name}: {before} -> {after}")
        else:
            batch = report["batch"]
            suffix = "" if batch is None else f" ({batch['total']} inputs)"
            print(f"UNCHANGED {case_name}{suffix}")
    return 1 if report["changed"] else 0


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "check":
        return _check(args)
    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
