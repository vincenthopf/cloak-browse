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
