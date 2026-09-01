from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from typing import Callable

from ._version import __version__
from .runtime import CloakBrowseRuntime, StartOptions


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cloak-browse",
        description="Stealth browser controlled by browser-harness",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command")

    start = commands.add_parser("start", help="Launch stealth browser + harness")
    start.add_argument("--proxy", help="Proxy URL (http://user:pass@host:port)")
    start.add_argument("--profile", help="Persistent profile directory path")
    start.add_argument(
        "--headless",
        action="store_true",
        help="Run headless (stealth patches still active)",
    )
    start.add_argument(
        "--humanize",
        action="store_true",
        help="Enable human-like mouse/keyboard behavior",
    )
    start.add_argument(
        "--backend",
        choices=["patchright", "playwright"],
        default="patchright",
        help="Playwright backend (default: patchright for max stealth)",
    )

    run = commands.add_parser("run", help="Run trusted Python against the browser")
    run.add_argument("code", help="Trusted Python code to execute")
    run.add_argument(
        "--timeout",
        type=_positive_float,
        default=None,
        help="Maximum execution time in seconds",
    )

    commands.add_parser("stop", help="Stop the managed browser and harness")

    status = commands.add_parser("status", help="Show detailed status")
    status.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="Write exactly one JSON value to stdout",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    runtime_factory: Callable[[], CloakBrowseRuntime] = CloakBrowseRuntime,
) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 2
    runtime = runtime_factory()
    if args.command == "start":
        return runtime.start(
            StartOptions(
                proxy=args.proxy,
                profile=args.profile,
                headless=args.headless,
                humanize=args.humanize,
                backend=args.backend,
            )
        )
    if args.command == "run":
        return runtime.run(args.code, args.timeout)
    if args.command == "stop":
        return runtime.stop()
    if args.command == "status":
        return runtime.status(args.json_output)
    parser.error(f"unknown command {args.command!r}")
    return 2


def _positive_float(value: str) -> float:
    number = float(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("timeout must be greater than zero")
    return number


if __name__ == "__main__":
    raise SystemExit(main())
