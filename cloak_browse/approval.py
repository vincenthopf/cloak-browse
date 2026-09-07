from __future__ import annotations

import json
import subprocess
import sys
from typing import Any

SCRIPT = """on run argv
set answer to display dialog (item 1 of argv) ¬
with title "Computer Use · Access request" ¬
buttons {"Deny", "Allow this session"} ¬
default button "Deny" cancel button "Deny" giving up after 120
if gave up of answer then return "deny"
return button returned of answer
end run"""


def dialog_approval(request: dict[str, Any]) -> dict[str, Any]:
    params = request.get("params", {})
    metadata = params.get("_meta", {})
    schema = params.get("requestedSchema", {})
    denied = {"action": "decline", "content": None}
    if (
        sys.platform != "darwin"
        or request.get("method") != "mcpServer/elicitation/request"
        or params.get("mode") != "form"
        or metadata.get("connector_id") != "computer-use"
        or schema.get("properties") != {}
    ):
        return denied
    text = (
        "Your local computer-use CLI requests app access.\n\n"
        + str(params.get("message", "Allow app access?"))
        + "\n\nRequested operation: "
        + str(metadata.get("tool_name", "unknown"))
        + "\n"
        + json.dumps(metadata.get("tool_params", {}), ensure_ascii=False)
        + "\n\nAllows this running session to read and operate this app. "
        "It may capture screenshots and accessibility text. "
        "This does not change macOS privacy permissions or save an always-allow rule. "
        "Stop the session to end access."
    )
    try:
        result = subprocess.run(
            ["/usr/bin/osascript", "-e", SCRIPT, text],
            capture_output=True,
            text=True,
            timeout=125,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return denied
    if result.returncode == 0 and result.stdout.strip() == "Allow this session":
        return {"action": "accept", "content": {}}
    return denied


class SessionApproval:
    def __init__(self) -> None:
        self.approved: set[tuple[str, str, str, str]] = set()

    def __call__(self, request: dict[str, Any]) -> dict[str, Any]:
        params = request.get("params", {})
        meta = params.get("_meta", {})
        tool_params = meta.get("tool_params", {})
        app = tool_params.get("app")
        thread = params.get("threadId")
        server = params.get("serverName")
        eligible = (
            request.get("method") == "mcpServer/elicitation/request"
            and params.get("mode") == "form"
            and meta.get("connector_id") == "computer-use"
            and meta.get("codex_approval_kind") == "mcp_tool_call"
            and "session" in meta.get("persist", [])
            and params.get("requestedSchema", {}).get("properties") == {}
            and set(tool_params) == {"app"}
            and all(isinstance(v, str) and v for v in (app, thread, server))
            and meta.get("tool_name")
            in {
                "get_app_state",
                "click",
                "drag",
                "paste",
                "press_key",
                "scroll",
                "select_text",
                "set_value",
                "type_text",
                "perform_secondary_action",
            }
        )
        if not eligible:
            return {"action": "decline", "content": None}
        key = (thread, server, app, str(meta.get("riskLevel", "")))
        if key in self.approved and not meta.get("subtitle"):
            return {"action": "accept", "content": {}}
        decision = dialog_approval(request)
        if decision.get("action") == "accept" and not meta.get("subtitle"):
            self.approved.add(key)
        return decision
