from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from cloak_browse.codex_client import (
    ApprovalRequired,
    CodexClient,
    CodexError,
    CodexProcessExited,
    CodexProtocolError,
    CodexRequestTimeout,
    CodexRpcError,
    JSONObject,
)

SERVER = r"""
import json
import os
import signal
import sys
import time

mode = sys.argv[1]
record = sys.argv[2]

def send(value):
    print(json.dumps(value), flush=True)

def receive():
    line = sys.stdin.readline()
    if not line:
        sys.exit(0)
    value = json.loads(line)
    with open(record, "a") as output:
        output.write(json.dumps(value) + "\n")
    return value

if mode == "ignore_term":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
request = receive()
if mode == "handshake_timeout":
    time.sleep(60)
if mode == "malformed":
    print("token=secret invalid json", flush=True)
    time.sleep(60)
if mode == "bad_version":
    send({"id": request["id"], "jsonrpc": "1.0", "result": {}})
    time.sleep(60)
if mode == "exit":
    sys.stderr.write("authentication-secret")
    sys.stderr.flush()
    sys.exit(7)
send({"id": request["id"], "result": {"userAgent": "fake"}})
assert receive() == {"method": "initialized"}
request = receive()
send({"id": request["id"], "result": {"thread": {"id": "thread-1"}}})
if mode == "blocked_stdin":
    time.sleep(60)
while True:
    request = receive()
    identifier = request["id"]
    if mode in ("timeout", "ignore_term"):
        time.sleep(60)
    if mode == "wrong_id":
        send({"id": identifier + 50, "result": {}})
        continue
    if mode == "rpc_error":
        send({"id": identifier, "error": {
            "code": -32000, "message": "token=secret",
            "data": {"accessToken": "secret"}
        }})
        continue
    if mode == "oversized":
        sys.stdout.write("x" * 8192)
        sys.stdout.flush()
        time.sleep(60)
    if mode == "truncated":
        sys.stdout.write('{"id":')
        sys.stdout.flush()
        sys.exit(0)
    if mode == "flood":
        os.write(2, b"authentication-secret" * 100000)
        for _ in range(2000):
            send({"method": "progress", "params": {"data": "ignored"}})
    if mode in ("approval", "command_approval", "unknown_approval"):
        method = {
            "approval": "mcpServer/elicitation/request",
            "command_approval": "item/commandExecution/requestApproval",
            "unknown_approval": "item/tool/requestUserInput"
        }[mode]
        send({"id": "approval-1", "method": method, "params": {
            "threadId": "thread-1", "mode": "form", "message": "Allow Calculator?",
            "requestedSchema": {"type": "object", "properties": {}},
            "_meta": {"connector_id": "computer-use", "tool_name": "get_app_state",
                      "tool_params": {"app": "Calculator", "accessToken": "secret"}}
        }})
        decision = receive()
        send({"id": identifier, "result": {"decision": decision}})
        continue
    if mode == "reverse":
        other = receive()
        send({"id": other["id"], "result": other["params"]})
        send({"id": identifier, "result": request["params"]})
        continue
    if request["method"] == "mcpServerStatus/list":
        send({"id": identifier, "result": {
            "data": [{"name": "node_repl", "tools": {"js": {"name": "js"}}}],
            "nextCursor": None
        }})
    else:
        send({"id": identifier, "result": {
            "content": [{"type": "text", "text": "ok"}], "echo": request["params"]
        }})
"""


@pytest.fixture
def fake_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Callable[..., tuple[CodexClient, Path]]:
    script = tmp_path / "fake_codex.py"
    script.write_text(SERVER)
    original = subprocess.Popen
    clients: list[CodexClient] = []

    def make(mode: str = "normal", **kwargs: object) -> tuple[CodexClient, Path]:
        record = tmp_path / f"{mode}.jsonl"

        def spawn(command: list[str], **options: object) -> subprocess.Popen[bytes]:
            assert command == ["/custom/codex", "app-server", "--listen", "stdio://"]
            return original([sys.executable, str(script), mode, str(record)], **options)

        monkeypatch.setattr("cloak_browse.codex_client.subprocess.Popen", spawn)
        client = CodexClient(
            cwd=tmp_path,
            cli_path="/custom/codex",
            request_timeout=2,
            shutdown_timeout=0.2,
            **kwargs,
        )
        clients.append(client)
        return client, record

    yield make
    for client in clients:
        client.close()


def messages(record: Path) -> list[JSONObject]:
    return [json.loads(line) for line in record.read_text().splitlines()]


def test_handshake_tools_execute_and_cleanup(fake_client) -> None:
    client, record = fake_client()
    with client:
        assert client.start() is client
        assert client.thread_id == "thread-1"
        assert client.tools() == [
            {"name": "node_repl", "tools": {"js": {"name": "js"}}}
        ]
        result = client.execute(
            "var sky = (await import('@oai/sky')).sky", title="Inspect", timeout=1
        )
        assert result["echo"] == {
            "threadId": "thread-1",
            "server": "node_repl",
            "tool": "js",
            "arguments": {
                "code": "var sky = (await import('@oai/sky')).sky",
                "title": "Inspect",
                "timeout_ms": 1000,
            },
        }
        client.execute("sky", timeout=1)
        assert client.running
    sent = messages(record)
    assert sent[0]["params"] == {
        "clientInfo": {"name": "local_computer_cli", "version": "0.1.0"},
        "capabilities": {"experimentalApi": True},
    }
    assert sent[2]["params"] == {
        "ephemeral": True,
        "approvalPolicy": "on-request",
        "sandbox": "read-only",
        "cwd": str(client.cwd),
    }
    assert sum(item.get("method") == "thread/start" for item in sent) == 1
    assert not client.running
    assert client._process.poll() is not None
    assert all(not worker.is_alive() for worker in client._threads)
    client.close()
    with pytest.raises(CodexError):
        client.start()


@pytest.mark.parametrize(
    "mode,error",
    [
        ("malformed", CodexProtocolError),
        ("bad_version", CodexProtocolError),
        ("exit", CodexProcessExited),
        ("handshake_timeout", CodexRequestTimeout),
    ],
)
def test_start_failure_is_clean(fake_client, mode, error) -> None:
    client, _ = fake_client(mode)
    client.request_timeout = 0.2
    with pytest.raises(error) as caught:
        client.start()
    assert "secret" not in str(caught.value)
    assert client._process.poll() is not None


@pytest.mark.parametrize(
    "mode,error",
    [
        ("timeout", CodexRequestTimeout),
        ("wrong_id", CodexProtocolError),
        ("oversized", CodexProtocolError),
        ("truncated", CodexProtocolError),
        ("ignore_term", CodexRequestTimeout),
    ],
)
def test_request_failure_is_bounded_and_clean(fake_client, mode, error) -> None:
    client, _ = fake_client(mode, max_message_bytes=4096)
    client.start()
    started = time.monotonic()
    with pytest.raises(error):
        client.execute("inspect", timeout=0.2)
    assert time.monotonic() - started < 2
    assert client._process.poll() is not None


def test_rpc_error_does_not_expose_server_details(fake_client) -> None:
    client, _ = fake_client("rpc_error")
    with client, pytest.raises(CodexRpcError) as caught:
        client.execute("inspect")
    assert caught.value.code == -32000
    assert "secret" not in str(caught.value)
    assert "secret" not in repr(vars(caught.value))


def test_large_stderr_and_notifications_are_drained(fake_client, capsys) -> None:
    client, _ = fake_client("flood")
    with client:
        assert client.execute("inspect")["content"]
        assert client.stderr_bytes_discarded == 65536
    captured = capsys.readouterr()
    assert not captured.out
    assert not captured.err


@pytest.mark.parametrize("mode", ["approval", "command_approval", "unknown_approval"])
def test_server_requests_fail_closed_with_structured_error(fake_client, mode) -> None:
    client, _ = fake_client(mode)
    with client, pytest.raises(ApprovalRequired) as caught:
        client.execute("inspect", timeout=1)
    assert caught.value.request["request_id"] == "approval-1"
    assert caught.value.request["message"] == "Allow Calculator?"
    assert caught.value.request["tool_params"] == {"app": "Calculator"}
    assert "secret" not in json.dumps(caught.value.request)


def test_explicit_handler_receives_exact_request_and_response_is_sent(
    fake_client,
) -> None:
    observed: list[JSONObject] = []

    def approve(request: JSONObject) -> JSONObject:
        observed.append(request)
        return {"action": "accept", "content": {}}

    client, _ = fake_client("approval", approval_handler=approve)
    with client:
        result = client.execute("inspect")
        assert result["decision"] == {
            "id": "approval-1",
            "result": {"action": "accept", "content": {}},
        }
    assert observed[0]["method"] == "mcpServer/elicitation/request"
    assert observed[0]["params"]["_meta"]["tool_params"]["app"] == "Calculator"


def test_handler_exception_declines(fake_client) -> None:
    def fail(request: JSONObject) -> JSONObject:
        raise RuntimeError("secret")

    client, _ = fake_client("approval", approval_handler=fail)
    with client, pytest.raises(ApprovalRequired):
        client.execute("inspect")


def test_blocked_handler_does_not_block_reader_or_timeout(fake_client) -> None:
    release = threading.Event()

    def block(request: JSONObject) -> JSONObject:
        release.wait(3)
        return {"action": "accept", "content": {}}

    client, _ = fake_client("approval", approval_handler=block)
    try:
        with client, pytest.raises(CodexRequestTimeout):
            client.execute("inspect", timeout=0.2)
        assert client._process.poll() is not None
    finally:
        release.set()


def test_request_ids_correlate_out_of_order(fake_client) -> None:
    client, _ = fake_client("reverse")
    results: dict[int, object] = {}
    with client:

        def run(number: int) -> None:
            results[number] = client.request("echo", {"number": number}, 1)

        workers = [threading.Thread(target=run, args=(number,)) for number in (1, 2)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(2)
    assert results == {1: {"number": 1}, 2: {"number": 2}}


def test_blocked_stdin_respects_request_timeout(fake_client) -> None:
    client, _ = fake_client("blocked_stdin")
    with client, pytest.raises(CodexRequestTimeout):
        client.execute("x" * 1000000, timeout=0.2)
    assert client._process.poll() is not None


def test_cwd_and_timeout_validation(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        CodexClient(cwd="relative")
    for timeout in (0, -1, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            CodexClient(cwd=tmp_path, request_timeout=timeout)
