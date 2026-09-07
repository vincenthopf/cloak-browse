from __future__ import annotations

import contextlib
import json
import math
import os
import queue
import selectors
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from types import TracebackType
from typing import IO, NoReturn, Self, TypeAlias, cast

JSONValue: TypeAlias = (
    bool | int | float | str | list["JSONValue"] | dict[str, "JSONValue"] | None
)
JSONObject: TypeAlias = dict[str, JSONValue]
RequestId: TypeAlias = int | str

DEFAULT_CLI_PATH = "/Applications/ChatGPT.app/Contents/Resources/codex"
_STDERR_LIMIT = 65536
_READ_SIZE = 16384
_POLL_INTERVAL = 0.05


class CodexError(Exception):
    pass


class CodexProtocolError(CodexError):
    pass


class CodexRequestTimeout(CodexError):
    def __init__(self, method: str, request_id: int, timeout: float) -> None:
        self.method = method
        self.request_id = request_id
        self.timeout = timeout
        super().__init__(f"Codex request {request_id} timed out after {timeout:g}s")


class CodexRpcError(CodexError):
    def __init__(self, method: str, request_id: int, code: int) -> None:
        self.method = method
        self.request_id = request_id
        self.code = code
        super().__init__(f"Codex request {request_id} failed with RPC code {code}")


class CodexProcessExited(CodexError):
    def __init__(self, returncode: int | None) -> None:
        self.returncode = returncode
        message = "Codex app-server closed stdout unexpectedly"
        if returncode is not None:
            message = f"Codex app-server exited unexpectedly with status {returncode}"
        super().__init__(message)


@dataclass(frozen=True)
class ApprovalRequest:
    request_id: RequestId
    method: str
    thread_id: str | None
    turn_id: str | None
    item_id: str | None
    server_name: str | None
    mode: str | None
    message: str | None
    tool_name: str | None
    tool_params: JSONObject | None


class ApprovalRequired(CodexError):
    def __init__(self, request: ApprovalRequest) -> None:
        self.request_info = request
        self.request = cast(JSONObject, asdict(request))
        super().__init__(
            "Codex requested approval or user input. The request was denied."
        )


@dataclass(frozen=True)
class McpServerStatus:
    name: str
    tools: JSONObject


class CodexClient:
    def __init__(
        self,
        *,
        cwd: str | os.PathLike[str],
        cli_path: str | os.PathLike[str] = DEFAULT_CLI_PATH,
        approval_handler: Callable[[JSONObject], JSONObject] | None = None,
        request_timeout: float = 30.0,
        shutdown_timeout: float = 1.0,
        max_message_bytes: int = 8 * 1024 * 1024,
        max_pending_requests: int = 16,
    ) -> None:
        directory = Path(cwd).expanduser()
        if not directory.is_absolute() or not directory.is_dir():
            raise ValueError("cwd must be an existing absolute directory")
        executable = os.fspath(cli_path)
        if not executable or "\x00" in executable:
            raise ValueError("cli_path must name an executable")
        _validate_timeout(request_timeout)
        _validate_timeout(shutdown_timeout)
        for value in (max_message_bytes, max_pending_requests):
            if type(value) is not int or value <= 0:
                raise ValueError("Buffer and request limits must be positive integers")
        self.cwd = directory
        self.cli_path = executable
        self.approval_handler = approval_handler
        self.request_timeout = request_timeout
        self.shutdown_timeout = shutdown_timeout
        self.max_message_bytes = max_message_bytes
        self.max_pending_requests = max_pending_requests
        self._process: subprocess.Popen[bytes] | None = None
        self._threads: list[threading.Thread] = []
        self._pending: dict[int, queue.Queue[JSONObject | CodexError]] = {}
        self._state_lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._approval_lock = threading.Lock()
        self._lifecycle_lock = threading.RLock()
        self._stop = threading.Event()
        self._approval_sent = threading.Event()
        self._approval_sent.set()
        self._failure: CodexError | None = None
        self._thread_id: str | None = None
        self._next_id = 1
        self._closed = False
        self._stderr_bytes_discarded = 0

    def __enter__(self) -> Self:
        return self.start()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    @property
    def thread_id(self) -> str:
        if self._thread_id is None:
            raise CodexError("Codex client has not started a thread")
        return self._thread_id

    @property
    def pid(self) -> int | None:
        return self._process.pid if self._process is not None else None

    @property
    def running(self) -> bool:
        return (
            not self._closed
            and self._process is not None
            and self._process.poll() is None
            and self._failure is None
        )

    @property
    def stderr_bytes_discarded(self) -> int:
        return self._stderr_bytes_discarded

    def start(self) -> Self:
        with self._lifecycle_lock:
            if self._closed:
                raise CodexError("A closed Codex client cannot be restarted")
            if self._process is not None:
                if self._failure is not None:
                    raise self._failure
                return self
            try:
                try:
                    process = subprocess.Popen(
                        [self.cli_path, "app-server", "--listen", "stdio://"],
                        cwd=self.cwd,
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        bufsize=0,
                    )
                except OSError:
                    raise CodexError(
                        "Unable to start the Codex app-server executable"
                    ) from None
                self._process = process
                if (
                    process.stdin is None
                    or process.stdout is None
                    or process.stderr is None
                ):
                    raise CodexError("Codex app-server pipes are unavailable")
                for stream in (process.stdin, process.stdout, process.stderr):
                    os.set_blocking(stream.fileno(), False)
                for stream, is_stdout in (
                    (process.stdout, True),
                    (process.stderr, False),
                ):
                    thread = threading.Thread(
                        target=self._read_stream,
                        args=(stream, is_stdout),
                        name=f"codex-{process.pid}-{is_stdout}",
                        daemon=True,
                    )
                    thread.start()
                    self._threads.append(thread)
                self._object(
                    self._request(
                        "initialize",
                        {
                            "clientInfo": {
                                "name": "local_computer_cli",
                                "version": "0.1.0",
                            },
                            "capabilities": {"experimentalApi": True},
                        },
                    ),
                    "initialize result must be an object",
                )
                self._send(
                    {"method": "initialized"},
                    time.monotonic() + self.request_timeout,
                )
                result = self._object(
                    self._request(
                        "thread/start",
                        {
                            "ephemeral": True,
                            "approvalPolicy": "on-request",
                            "sandbox": "read-only",
                            "cwd": str(self.cwd),
                        },
                    ),
                    "thread/start result must be an object",
                )
                thread_result = self._object(
                    result.get("thread"), "thread/start result must contain a thread"
                )
                thread_id = thread_result.get("id")
                if not isinstance(thread_id, str) or not thread_id:
                    self._protocol_error("thread/start result must contain a thread id")
                self._thread_id = thread_id
                return self
            except BaseException:
                self.close()
                raise

    def close(self) -> None:
        with self._lifecycle_lock:
            if self._closed:
                return
            self._approval_sent.wait(self.shutdown_timeout)
            self._closed = True
            self._stop.set()
            self._fail(CodexError("Codex client is closed"))
            process = self._process
            if process is not None:
                with self._write_lock:
                    if process.stdin is not None:
                        with contextlib.suppress(OSError):
                            process.stdin.close()
                if process.poll() is None:
                    with contextlib.suppress(ProcessLookupError):
                        process.terminate()
                try:
                    process.wait(timeout=self.shutdown_timeout)
                except subprocess.TimeoutExpired:
                    with contextlib.suppress(ProcessLookupError):
                        process.kill()
                    process.wait(timeout=self.shutdown_timeout)
            deadline = time.monotonic() + self.shutdown_timeout
            for thread in self._threads:
                thread.join(timeout=max(0.0, deadline - time.monotonic()))
            if process is not None:
                for stream in (process.stdout, process.stderr):
                    if stream is not None and not any(
                        t.is_alive() for t in self._threads
                    ):
                        stream.close()

    def request(
        self,
        method: str,
        params: JSONObject | None = None,
        timeout: float | None = None,
    ) -> JSONValue:
        if self._thread_id is None:
            raise CodexError("Start the Codex client before making requests")
        return self._request(method, params, timeout=timeout)

    def list_mcp_servers(
        self, *, timeout: float | None = None
    ) -> tuple[McpServerStatus, ...]:
        duration = self.request_timeout if timeout is None else timeout
        _validate_timeout(duration)
        deadline = time.monotonic() + duration
        servers: list[McpServerStatus] = []
        cursors: set[str] = set()
        cursor: str | None = None
        for _ in range(100):
            params: JSONObject = {
                "threadId": self.thread_id,
                "detail": "toolsAndAuthOnly",
            }
            if cursor is not None:
                params["cursor"] = cursor
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                error = CodexRequestTimeout(
                    "mcpServerStatus/list", self._next_id, duration
                )
                self._fail(error)
                self.close()
                raise error
            result = self._object(
                self.request("mcpServerStatus/list", params, timeout=remaining),
                "mcpServerStatus/list result must be an object",
            )
            data = result.get("data")
            if not isinstance(data, list):
                self._protocol_error(
                    "mcpServerStatus/list result.data must be an array"
                )
            for value in data:
                server = self._object(value, "MCP server status must be an object")
                name = server.get("name")
                tools = server.get("tools")
                if not isinstance(name, str) or not name or not isinstance(tools, dict):
                    self._protocol_error(
                        "MCP server status requires a name and tools object"
                    )
                servers.append(McpServerStatus(name=name, tools=tools))
            next_cursor = result.get("nextCursor")
            if next_cursor is None:
                return tuple(servers)
            if (
                not isinstance(next_cursor, str)
                or not next_cursor
                or next_cursor in cursors
            ):
                self._protocol_error("MCP server pagination returned an invalid cursor")
            cursors.add(next_cursor)
            cursor = next_cursor
        self._protocol_error("MCP server pagination exceeded 100 pages")

    def tools(self) -> list[JSONObject]:
        self.start()
        return [
            {"name": server.name, "tools": server.tools}
            for server in self.list_mcp_servers()
        ]

    def execute(
        self, code: str, title: str = "Local computer", timeout: float = 30.0
    ) -> JSONObject:
        _validate_timeout(timeout)
        self.start()
        return self.call_js(
            code,
            title=title,
            timeout_ms=max(1, math.ceil(timeout * 1000)),
            timeout=timeout,
        )

    def call_js(
        self,
        code: str,
        *,
        title: str = "Local computer",
        timeout_ms: int = 10000,
        timeout: float | None = None,
    ) -> JSONObject:
        if not isinstance(code, str) or not code.strip():
            raise ValueError("code must be a nonempty string")
        if not isinstance(title, str) or not title.strip():
            raise ValueError("title must be a nonempty string")
        if type(timeout_ms) is not int or timeout_ms <= 0:
            raise ValueError("timeout_ms must be a positive integer")
        return self._object(
            self.request(
                "mcpServer/tool/call",
                {
                    "threadId": self.thread_id,
                    "server": "node_repl",
                    "tool": "js",
                    "arguments": {
                        "code": code,
                        "title": title,
                        "timeout_ms": timeout_ms,
                    },
                },
                timeout=timeout,
            ),
            "mcpServer/tool/call result must be an object",
        )

    def _request(
        self,
        method: str,
        params: JSONObject | None = None,
        *,
        timeout: float | None = None,
    ) -> JSONValue:
        if not isinstance(method, str) or not method:
            raise ValueError("method must be a nonempty string")
        if params is not None and not isinstance(params, dict):
            raise ValueError("params must be an object")
        duration = self.request_timeout if timeout is None else timeout
        _validate_timeout(duration)
        deadline = time.monotonic() + duration
        inbox: queue.Queue[JSONObject | CodexError] = queue.Queue(maxsize=1)
        with self._state_lock:
            if self._failure is not None:
                raise self._failure
            if len(self._pending) >= self.max_pending_requests:
                raise CodexError("Codex pending request limit reached")
            request_id = self._next_id
            self._next_id += 1
            self._pending[request_id] = inbox
        try:
            self._send(
                {"id": request_id, "method": method, "params": params or {}}, deadline
            )
            try:
                response = inbox.get(timeout=max(0.0, deadline - time.monotonic()))
            except queue.Empty:
                raise TimeoutError from None
            if isinstance(response, CodexError):
                raise response
            if "error" in response:
                error = cast(JSONObject, response["error"])
                raise CodexRpcError(method, request_id, cast(int, error["code"]))
            return response["result"]
        except TimeoutError:
            with self._state_lock:
                failure = self._failure
            failure = failure or CodexRequestTimeout(method, request_id, duration)
            self._fail(failure)
            self.close()
            raise failure from None
        except CodexRpcError:
            raise
        except CodexError as error:
            self._fail(error)
            self.close()
            raise
        except BaseException:
            self.close()
            raise
        finally:
            with self._state_lock:
                self._pending.pop(request_id, None)

    def _send(self, message: JSONObject, deadline: float) -> None:
        try:
            payload = (
                json.dumps(
                    message, ensure_ascii=False, allow_nan=False, separators=(",", ":")
                ).encode("utf-8")
                + b"\n"
            )
        except (TypeError, ValueError, UnicodeError, RecursionError):
            raise ValueError("Codex request must contain valid JSON values") from None
        if len(payload) - 1 > self.max_message_bytes:
            raise ValueError("Codex request exceeds the message size limit")
        if not self._write_lock.acquire(timeout=max(0.0, deadline - time.monotonic())):
            raise TimeoutError
        try:
            process = self._process
            if process is None or process.stdin is None:
                raise CodexError("Codex app-server is not running")
            descriptor = process.stdin.fileno()
            with selectors.DefaultSelector() as selector:
                selector.register(descriptor, selectors.EVENT_WRITE)
                position = 0
                while position < len(payload):
                    if self._stop.is_set():
                        raise CodexError("Codex client is closed")
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError
                    if not selector.select(min(remaining, _POLL_INTERVAL)):
                        continue
                    try:
                        position += os.write(descriptor, memoryview(payload)[position:])
                    except BlockingIOError:
                        continue
        except TimeoutError:
            raise
        except (OSError, ValueError):
            raise CodexError("Codex app-server input pipe is unavailable") from None
        finally:
            self._write_lock.release()

    def _read_stream(self, stream: IO[bytes], is_stdout: bool) -> None:
        buffer = bytearray()
        try:
            descriptor = stream.fileno()
            with selectors.DefaultSelector() as selector:
                selector.register(descriptor, selectors.EVENT_READ)
                while not self._stop.is_set():
                    if not selector.select(_POLL_INTERVAL):
                        continue
                    try:
                        chunk = os.read(descriptor, _READ_SIZE)
                    except BlockingIOError:
                        continue
                    if not chunk:
                        if is_stdout and not self._stop.is_set():
                            if buffer:
                                raise CodexProtocolError(
                                    "Codex stdout ended mid-message"
                                )
                            process = self._process
                            raise CodexProcessExited(
                                process.poll() if process is not None else None
                            )
                        return
                    if not is_stdout:
                        self._stderr_bytes_discarded = min(
                            _STDERR_LIMIT, self._stderr_bytes_discarded + len(chunk)
                        )
                        continue
                    buffer.extend(chunk)
                    while (end := buffer.find(b"\n")) != -1:
                        if end > self.max_message_bytes:
                            raise CodexProtocolError(
                                "Codex stdout message exceeds size limit"
                            )
                        line = bytes(buffer[:end])
                        del buffer[: end + 1]
                        self._dispatch(_decode_message(line))
                    if len(buffer) > self.max_message_bytes:
                        raise CodexProtocolError(
                            "Codex stdout message exceeds size limit"
                        )
        except CodexError as error:
            if not self._stop.is_set():
                self._fail(error)
        except (OSError, ValueError):
            if not self._stop.is_set():
                self._fail(CodexError("Codex app-server output pipe is unavailable"))
        finally:
            stream.close()

    def _dispatch(self, message: JSONObject) -> None:
        if "jsonrpc" in message and message["jsonrpc"] != "2.0":
            raise CodexProtocolError("Codex returned an unsupported JSON-RPC version")
        if "method" in message:
            method = message["method"]
            params = message.get("params")
            if (
                not isinstance(method, str)
                or not method
                or (params is not None and not isinstance(params, dict))
                or "result" in message
                or "error" in message
            ):
                raise CodexProtocolError("Codex returned an invalid server message")
            if "id" in message:
                request_id = message["id"]
                if type(request_id) not in (int, str):
                    raise CodexProtocolError(
                        "Codex returned an invalid server request id"
                    )
                if self.approval_handler is None:
                    self._reject_server_request(
                        cast(RequestId, request_id), method, params or {}
                    )
                elif self._approval_lock.acquire(blocking=False):
                    worker = threading.Thread(
                        target=self._handle_approval,
                        args=(message,),
                        name="codex-approval",
                        daemon=True,
                    )
                    worker.start()
                    self._threads = [t for t in self._threads if t.is_alive()]
                    self._threads.append(worker)
                else:
                    self._reject_server_request(
                        cast(RequestId, request_id), method, params or {}
                    )
            return
        request_id = message.get("id")
        if type(request_id) is not int or (
            ("result" in message) == ("error" in message)
        ):
            raise CodexProtocolError("Codex returned an invalid RPC response")
        if "error" in message:
            error = message["error"]
            if (
                not isinstance(error, dict)
                or type(error.get("code")) is not int
                or not isinstance(error.get("message"), str)
            ):
                raise CodexProtocolError("Codex returned an invalid RPC error")
        with self._state_lock:
            inbox = self._pending.get(request_id)
            if inbox is None:
                raise CodexProtocolError("Codex returned an unrecognized response id")
            try:
                inbox.put_nowait(message)
            except queue.Full:
                raise CodexProtocolError(
                    "Codex returned a duplicate RPC response"
                ) from None

    def _handle_approval(self, message: JSONObject) -> None:
        request_id = cast(RequestId, message["id"])
        method = cast(str, message["method"])
        params = cast(JSONObject, message.get("params") or {})
        try:
            handler = self.approval_handler
            if handler is None:
                return
            try:
                result = handler(message)
            except Exception:
                result = {}
            accepted = False
            if isinstance(result, dict):
                if method == "mcpServer/elicitation/request":
                    accepted = result.get("action") == "accept" and isinstance(
                        result.get("content"), dict
                    )
                elif method in {
                    "item/commandExecution/requestApproval",
                    "item/fileChange/requestApproval",
                }:
                    accepted = result.get("decision") in ("accept", "acceptForSession")
                elif method in {"execCommandApproval", "applyPatchApproval"}:
                    accepted = result.get("decision") in (
                        "approved",
                        "approved_for_session",
                    )
            if self._stop.is_set():
                return
            if accepted:
                self._send(
                    {"id": request_id, "result": result},
                    time.monotonic() + self.shutdown_timeout,
                )
            else:
                self._reject_server_request(request_id, method, params)
        except (CodexError, TimeoutError, ValueError):
            self._fail(CodexError("Unable to respond to the Codex approval request"))
        finally:
            self._approval_lock.release()

    def _reject_server_request(
        self, request_id: RequestId, method: str, params: JSONObject
    ) -> None:
        request = ApprovalRequest(
            request_id=request_id,
            method=method,
            thread_id=_optional_string(params.get("threadId")),
            turn_id=_optional_string(params.get("turnId")),
            item_id=_optional_string(params.get("itemId")),
            server_name=_optional_string(params.get("serverName")),
            mode=_optional_string(params.get("mode")),
            message=_optional_string(params.get("message")),
            tool_name=_optional_string(
                cast(JSONObject, params.get("_meta") or {}).get("tool_name")
            )
            if isinstance(params.get("_meta"), dict)
            else None,
            tool_params=_approval_tool_params(params),
        )
        response: JSONObject = {"id": request_id}
        if method == "mcpServer/elicitation/request":
            response["result"] = {"action": "decline", "content": None}
        elif method in {
            "item/commandExecution/requestApproval",
            "item/fileChange/requestApproval",
        }:
            response["result"] = {"decision": "decline"}
        elif method in {"execCommandApproval", "applyPatchApproval"}:
            response["result"] = {"decision": "denied"}
        elif method == "item/permissions/requestApproval":
            response["result"] = {"permissions": {}, "scope": "turn"}
        else:
            response["error"] = {
                "code": -32601,
                "message": "Client does not support interactive server requests",
            }
        self._approval_sent.clear()
        self._fail(ApprovalRequired(request))
        try:
            self._send(response, time.monotonic() + self.shutdown_timeout)
        except (CodexError, TimeoutError):
            pass
        finally:
            self._approval_sent.set()

    def _fail(self, error: CodexError) -> None:
        with self._state_lock:
            if self._failure is None:
                self._failure = error
            for inbox in self._pending.values():
                with contextlib.suppress(queue.Full):
                    inbox.put_nowait(self._failure)

    def _object(self, value: JSONValue, message: str) -> JSONObject:
        if not isinstance(value, dict):
            self._protocol_error(message)
        return value

    def _protocol_error(self, message: str) -> NoReturn:
        error = CodexProtocolError(message)
        self._fail(error)
        self.close()
        raise error


def _approval_tool_params(params: JSONObject) -> JSONObject | None:
    metadata = params.get("_meta")
    if not isinstance(metadata, dict):
        return None
    tool_params = metadata.get("tool_params")
    if not isinstance(tool_params, dict):
        return None
    safe_keys = {"app", "element_index", "x", "y", "direction", "pages", "disableDiff"}
    return {key: value for key, value in tool_params.items() if key in safe_keys}


def _optional_string(value: JSONValue) -> str | None:
    return value if isinstance(value, str) else None


def _validate_timeout(timeout: float) -> None:
    if isinstance(timeout, bool) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Timeouts must be finite positive seconds")


def _invalid_constant(value: str) -> NoReturn:
    raise ValueError("Non-finite JSON number")


def _unique_object(pairs: list[tuple[str, JSONValue]]) -> JSONObject:
    result: JSONObject = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _decode_message(line: bytes) -> JSONObject:
    try:
        value = cast(
            JSONValue,
            json.loads(
                line.decode("utf-8"),
                parse_constant=_invalid_constant,
                object_pairs_hook=_unique_object,
            ),
        )
    except (ValueError, UnicodeError, RecursionError):
        raise CodexProtocolError("Codex stdout contains malformed JSON") from None
    if not isinstance(value, dict):
        raise CodexProtocolError("Codex stdout message must be an object")
    return value
