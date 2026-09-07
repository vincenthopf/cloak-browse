from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

METHODS: dict[str, set[str]] = {
    "state": {"app", "disableDiff"},
    "click": {"app", "element_index", "x", "y", "mouse_button", "click_count"},
    "drag": {"app", "from_x", "from_y", "to_x", "to_y"},
    "paste": {"app", "text", "format"},
    "press_key": {"app", "key"},
    "scroll": {"app", "element_index", "x", "y", "direction", "pages"},
    "select_text": {
        "app",
        "element_index",
        "text",
        "prefix",
        "suffix",
        "selection_type",
    },
    "set_value": {"app", "element_index", "value"},
    "type_text": {"app", "text"},
    "perform_secondary_action": {"app", "element_index", "action"},
}
REQUIRED: dict[str, set[str]] = {
    "state": {"app"},
    "click": {"app"},
    "drag": {"app", "from_x", "from_y", "to_x", "to_y"},
    "paste": {"app", "text", "format"},
    "press_key": {"app", "key"},
    "scroll": {"app", "direction"},
    "select_text": {"app", "element_index", "text"},
    "set_value": {"app", "element_index", "value"},
    "type_text": {"app", "text"},
    "perform_secondary_action": {"app", "element_index", "action"},
}


def action_code(method: str, args: dict[str, Any]) -> str:
    if method not in METHODS:
        raise ValueError(f"Unknown desktop operation: {method}")
    if set(args) - METHODS[method] or REQUIRED[method] - set(args):
        raise ValueError(
            f"Invalid arguments for {method}; required: {sorted(REQUIRED[method])}"
        )
    for key, value in args.items():
        if key == "disableDiff":
            if not isinstance(value, bool):
                raise ValueError("disableDiff must be a boolean")
        elif key in {"element_index", "click_count"}:
            if type(value) is not int or value < 0:
                raise ValueError(f"{key} must be a nonnegative integer")
        elif key in {"x", "y", "from_x", "from_y", "to_x", "to_y", "pages"}:
            if type(value) not in {int, float} or not math.isfinite(value):
                raise ValueError(f"{key} must be a finite number")
        elif not isinstance(value, str):
            raise ValueError(f"{key} must be a string")
    if not args["app"].strip():
        raise ValueError("app must not be empty")
    if method == "click" and not ("element_index" in args or {"x", "y"} <= set(args)):
        raise ValueError("click requires element_index or both x and y")
    if method == "paste" and args["format"] not in {"text", "md", "html"}:
        raise ValueError("paste format must be text, md or html")
    native_method = "get_app_state" if method == "state" else method
    encoded = json.dumps(args, ensure_ascii=True, allow_nan=False)
    return (
        'var sky = (await import("@oai/sky")).sky; '
        f"var result = await sky.{native_method}({encoded}); "
        "nodeRepl.write(JSON.stringify(result === undefined ? {ok:true} : result));"
    )


def human_approval(request: dict[str, Any]) -> dict[str, Any]:
    params = request.get("params", {})
    metadata = params.get("_meta", {})
    schema = params.get("requestedSchema", {})
    eligible = (
        request.get("method") == "mcpServer/elicitation/request"
        and params.get("mode") == "form"
        and metadata.get("connector_id") == "computer-use"
        and schema.get("properties") == {}
    )
    if not eligible or not sys.stdin.isatty() or not sys.stderr.isatty():
        return {"action": "decline", "content": None}
    print(str(params.get("message", "Computer Use requests access")), file=sys.stderr)
    print(json.dumps(metadata.get("tool_params", {})), file=sys.stderr)
    print("Allow this request? Type allow: ", end="", file=sys.stderr, flush=True)
    if sys.stdin.readline().strip() == "allow":
        return {"action": "accept", "content": {}}
    return {"action": "decline", "content": None}


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        prog="computer-use",
        description="Local browser and Mac app control; JSON output",
    )
    sub = result.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="Inspect Codex installation and host connectivity")
    sub.add_parser("tools", help="List desktop command schemas; no desktop access")
    desktop = sub.add_parser("desktop", help="Run one native operation")
    desktop.add_argument("operation", choices=["state"])
    desktop.add_argument("--args", required=True, help="JSON object")
    desktop.add_argument(
        "--interactive", action="store_true", help="Human TTY approvals"
    )
    desktop.add_argument("--timeout", type=float, default=30)

    session = sub.add_parser(
        "session", help="Persistent JSON-lines CLI session, not MCP"
    )
    session.add_argument("--timeout", type=float, default=30)
    browser = sub.add_parser("browser", help="Delegate browser commands to CloakBrowse")
    browser.add_argument("arguments", nargs=argparse.REMAINDER)
    result.add_argument("--codex-bin", type=Path, default=None)
    return result


def emit(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=True, default=str), flush=True)


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.command == "browser":
        from .cli import main as browser_main
        from .paths import app_paths
        from .runtime import CloakBrowseRuntime

        cache = app_paths().cache_dir.parent / "computer-use-browser"
        paths = app_paths({"CLOAK_BROWSE_CACHE_DIR": str(cache)})
        return browser_main(
            args.arguments,
            runtime_factory=lambda: CloakBrowseRuntime(paths=paths, cdp_port=9334),
        )
    if args.command == "tools":
        emit(
            {
                "operations": {
                    k: {"allowed": sorted(v), "required": sorted(REQUIRED[k])}
                    for k, v in METHODS.items()
                },
                "state_first": True,
                "approval": "host-managed",
                "session": "JSON lines; approvals fail closed",
            }
        )
        return 0
    from .codex_client import CodexClient

    options: dict[str, Any] = {"cwd": Path.cwd()}
    if args.codex_bin:
        options["cli_path"] = args.codex_bin
    if getattr(args, "interactive", False):
        options["approval_handler"] = human_approval
    try:
        if args.command == "desktop":
            payload = json.loads(args.args)
            if not isinstance(payload, dict):
                raise ValueError("--args must be a JSON object")
            code = action_code(args.operation, payload)

        with CodexClient(**options) as client:
            if args.command == "doctor":
                emit(
                    {
                        "ok": True,
                        "tools": client.tools(),
                        "native_control": "not tested",
                        "approval": "fail closed",
                    }
                )
            elif args.command == "desktop":
                result = client.execute(
                    code, title=f"Computer Use: {args.operation}", timeout=args.timeout
                )
                emit({"ok": not result.get("isError", False), "result": result})
                if result.get("isError"):
                    return 1
            elif args.command == "session":
                run_session(client, args.timeout)
        return 0
    except Exception as exc:
        emit(
            {
                "ok": False,
                "error": type(exc).__name__,
                "message": str(exc),
                "request": getattr(exc, "request", None),
            }
        )
        return 1


def run_session(client: Any, timeout: float) -> None:
    observed: set[str] = set()
    for raw in sys.stdin:
        identifier: Any = None
        try:
            request = json.loads(raw)
            if not isinstance(request, dict):
                raise ValueError("Session request must be an object")
            identifier = request.get("id")
            method = request.get("operation")
            payload = request.get("args", {})
            if not isinstance(method, str) or not isinstance(payload, dict):
                raise ValueError("operation and args are required")
            code = action_code(method, payload)
            app = payload["app"]
            if method == "state":
                observed.discard(app)
            if method != "state":
                if app not in observed:
                    raise ValueError(
                        "Read state for this app in this session before acting"
                    )
                if request.get("acknowledge_side_effects") is not True:
                    raise ValueError(
                        "Action requires acknowledge_side_effects "
                        "after user authorization"
                    )
                observed.discard(app)
            result = client.execute(
                code, title=f"Computer Use: {method}", timeout=timeout
            )
            if method == "state" and not result.get("isError"):
                observed.add(app)
            emit(
                {
                    "id": identifier,
                    "ok": not result.get("isError", False),
                    "result": result,
                }
            )
        except Exception as exc:
            emit(
                {
                    "id": identifier,
                    "ok": False,
                    "error": type(exc).__name__,
                    "message": str(exc),
                    "request": getattr(exc, "request", None),
                }
            )


if __name__ == "__main__":
    raise SystemExit(main())
