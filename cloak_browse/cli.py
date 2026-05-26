"""cloak-browse: stealth browser + browser-harness in one CLI."""

import argparse
import json
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

CDP_PORT = 9333
CDP_URL = f"http://127.0.0.1:{CDP_PORT}"
BH_NAME = "cloak"
IS_WINDOWS = sys.platform == "win32"
SESSION_DIR = Path.home() / ".cache" / "cloak-browse"
SESSION_FILE = SESSION_DIR / "session.json"


# --- session metadata ---


def _save_session(**fields):
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    existing = _load_session()
    existing.update(fields)
    existing["updatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    SESSION_FILE.write_text(json.dumps(existing, indent=2))


def _load_session() -> dict:
    try:
        return json.loads(SESSION_FILE.read_text())
    except (FileNotFoundError, ValueError):
        return {}


def _clear_session():
    try:
        SESSION_FILE.unlink()
    except FileNotFoundError:
        pass


# --- CDP probes ---


def _cdp_version() -> dict | None:
    try:
        with urllib.request.urlopen(f"{CDP_URL}/json/version", timeout=2) as r:
            return json.loads(r.read())
    except Exception:
        return None


def _cdp_alive() -> bool:
    return _cdp_version() is not None


def _cdp_ws_probe(ws_url: str, timeout: float = 3.0) -> bool:
    try:
        import websockets.sync.client as wsc
        conn = wsc.connect(ws_url, open_timeout=timeout, close_timeout=1)
        conn.close()
        return True
    except Exception:
        return False


def _wait_cdp_ready(timeout: float = 15.0) -> dict | None:
    deadline = time.time() + timeout
    last_err = None
    while time.time() < deadline:
        info = _cdp_version()
        if info:
            ws_url = info.get("webSocketDebuggerUrl")
            if ws_url and _cdp_ws_probe(ws_url):
                return info
            last_err = "CDP HTTP up but WebSocket not ready"
        time.sleep(0.3)
    if last_err:
        print(f"  warning: {last_err}", file=sys.stderr)
    return None


def _cdp_targets() -> list[dict]:
    try:
        with urllib.request.urlopen(f"{CDP_URL}/json/list", timeout=2) as r:
            return json.loads(r.read())
    except Exception:
        return []


# --- daemon management (cross-platform via browser-harness IPC) ---


def _bh_daemon_alive() -> bool:
    try:
        from browser_harness._ipc import ping
        return ping(BH_NAME, timeout=1.0)
    except Exception:
        return False


def _stop_bh_daemon():
    try:
        from browser_harness._ipc import connect, request, identify, cleanup_endpoint
        pid = identify(BH_NAME, timeout=2.0)
        try:
            c, token = connect(BH_NAME, timeout=5.0)
            request(c, token, {"meta": "shutdown"})
            c.close()
        except Exception:
            pass
        if pid:
            for _ in range(50):
                try:
                    os.kill(pid, 0)
                    time.sleep(0.1)
                except (ProcessLookupError, OSError):
                    break
            else:
                try:
                    sig = signal.SIGTERM if not IS_WINDOWS else signal.CTRL_BREAK_EVENT
                    os.kill(pid, sig)
                except (ProcessLookupError, OSError):
                    pass
        cleanup_endpoint(BH_NAME)
    except Exception:
        pass


def _start_bh_daemon():
    _stop_bh_daemon()
    env = {**os.environ, "BU_NAME": BH_NAME, "BU_CDP_URL": CDP_URL}

    spawn_kwargs = {}
    if IS_WINDOWS:
        spawn_kwargs["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        )
    else:
        spawn_kwargs["start_new_session"] = True

    subprocess.Popen(
        [
            sys.executable,
            "-c",
            "from browser_harness.daemon import main; import asyncio; asyncio.run(main())",
        ],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        **spawn_kwargs,
    )
    deadline = time.time() + 15
    while time.time() < deadline:
        if _bh_daemon_alive():
            return True
        time.sleep(0.3)

    from browser_harness._ipc import log_path
    log = log_path(BH_NAME)
    tail = ""
    if log.exists():
        lines = log.read_text().strip().splitlines()
        tail = lines[-1] if lines else ""
    print(f"error: browser-harness daemon didn't start: {tail}", file=sys.stderr)
    return False


# --- stale session cleanup ---


def _kill_pid(pid):
    if pid is None:
        return
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, OSError):
        return
    try:
        os.kill(pid, signal.SIGTERM if not IS_WINDOWS else signal.CTRL_BREAK_EVENT)
        time.sleep(0.5)
        try:
            os.kill(pid, 0)
            if not IS_WINDOWS:
                os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, OSError):
            pass
    except (ProcessLookupError, OSError):
        pass


def _cleanup_stale_session():
    session = _load_session()
    if not session:
        return
    for key in ("daemonPid", "browserPid"):
        _kill_pid(session.get(key))
    _stop_bh_daemon()
    _clear_session()


# --- commands ---


def cmd_start(args):
    from cloakbrowser import launch, launch_persistent_context
    from cloakbrowser.download import ensure_binary

    if _cdp_alive() or _load_session().get("browserPid"):
        _cleanup_stale_session()

    # Ensure stealth binary is downloaded
    print("checking stealth chromium binary...")
    binary_path = ensure_binary()
    print(f"  binary: {binary_path}")

    extra_args = [f"--remote-debugging-port={CDP_PORT}"]
    proxy = args.proxy or None
    headless = args.headless
    backend = args.backend
    mode = "headless" if headless else "headed"

    print(f"launching stealth chromium ({mode}, {backend} backend, CDP on :{CDP_PORT})...")

    launch_kwargs = dict(
        headless=headless,
        proxy=proxy,
        args=extra_args,
        humanize=args.humanize,
        backend=backend,
    )

    if args.profile:
        ctx = launch_persistent_context(
            user_data_dir=os.path.expanduser(args.profile),
            **launch_kwargs,
        )
        cleanup = ctx.close
    else:
        browser = launch(**launch_kwargs)
        cleanup = browser.close

    info = _wait_cdp_ready(timeout=15.0)
    if not info:
        print("error: CDP endpoint didn't become ready", file=sys.stderr)
        cleanup()
        sys.exit(1)

    browser_version = info.get("Browser", "?")
    print(f"  browser: {browser_version}")
    print(f"  backend: {backend}")
    print(f"  CDP:     {CDP_URL}")
    print(f"  mode:    {mode}")

    _save_session(
        browserVersion=browser_version,
        backend=backend,
        mode=mode,
        cdpPort=CDP_PORT,
        profile=args.profile or "(temp)",
        proxy=args.proxy or None,
        humanize=args.humanize,
        startedAt=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    )

    print("starting browser-harness daemon...")
    if _start_bh_daemon():
        print(f"  harness: ready (BU_NAME={BH_NAME})")
        print()
        print("usage:")
        print(f"  cloak-browse run \"new_tab('https://example.com')\"")
        print(f'  cloak-browse run "print(page_info())"')
        print(f'  cloak-browse run "print(visible_text()[:2000])"')
    else:
        print("  harness: failed (browser still running, you can retry manually)")

    print()
    print("ctrl+c to stop")

    _is_closing = False
    stop = False

    def handle_sig(*_):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, handle_sig)
    if not IS_WINDOWS:
        signal.signal(signal.SIGTERM, handle_sig)

    while not stop:
        time.sleep(0.5)

    if _is_closing:
        return
    _is_closing = True

    print("\nshutting down...")
    _stop_bh_daemon()
    try:
        cleanup()
    except Exception:
        pass
    _clear_session()
    print("done.")


def cmd_run(args):
    if not _cdp_alive():
        print(
            "error: no stealth browser running — run `cloak-browse start` first",
            file=sys.stderr,
        )
        sys.exit(1)

    if not _bh_daemon_alive():
        print("harness daemon not running, starting...", file=sys.stderr)
        if not _start_bh_daemon():
            sys.exit(1)

    os.environ["BU_NAME"] = BH_NAME
    import browser_harness.helpers as _h
    ns = {k: getattr(_h, k) for k in dir(_h) if not k.startswith("_")}

    timeout = args.timeout
    if timeout:
        def _run():
            exec(args.code, ns)
        t = threading.Thread(target=_run, daemon=True)
        t.start()
        t.join(timeout=timeout)
        if t.is_alive():
            print(f"error: run timed out after {timeout}s", file=sys.stderr)
            sys.exit(124)
    else:
        exec(args.code, ns)


def cmd_stop(args):
    _stop_bh_daemon()
    _clear_session()
    print("harness daemon stopped.")
    if _cdp_alive():
        print("note: stealth browser still running (ctrl+c the `start` process to close it)")


def cmd_status(args):
    cdp_up = _cdp_alive()
    bh_up = _bh_daemon_alive()
    session = _load_session()

    print(f"stealth browser:  {'running' if cdp_up else 'not running'}")
    if cdp_up:
        info = _cdp_version()
        if info:
            print(f"  browser:  {info.get('Browser', '?')}")
            ws_url = info.get("webSocketDebuggerUrl", "")
            ws_ok = _cdp_ws_probe(ws_url) if ws_url else False
            print(f"  CDP WS:   {'ok' if ws_ok else 'unreachable'}")
        targets = _cdp_targets()
        pages = [t for t in targets if t.get("type") == "page"]
        print(f"  tabs:     {len(pages)}")
        for t in pages[:5]:
            title = t.get("title", "")[:40]
            url = t.get("url", "")[:60]
            print(f"    - {title or '(untitled)'} | {url}")

    print(f"harness daemon:   {'running' if bh_up else 'not running'} (BU_NAME={BH_NAME})")

    if session:
        print("session:")
        print(f"  backend:  {session.get('backend', '?')}")
        print(f"  mode:     {session.get('mode', '?')}")
        print(f"  profile:  {session.get('profile', '?')}")
        print(f"  started:  {session.get('startedAt', '?')}")
        if session.get("proxy"):
            proxy = session["proxy"]
            if "@" in proxy:
                proxy = proxy.split("@")[-1]
            print(f"  proxy:    {proxy}")

    if args.json_output:
        result = {
            "browser": "running" if cdp_up else "stopped",
            "daemon": "running" if bh_up else "stopped",
            "cdpPort": CDP_PORT,
            **session,
        }
        if cdp_up:
            result["tabs"] = len(pages)
        print(json.dumps(result, indent=2))


def main():
    p = argparse.ArgumentParser(
        prog="cloak-browse",
        description="Stealth browser controlled by browser-harness",
    )
    sub = p.add_subparsers(dest="command")

    sp = sub.add_parser("start", help="Launch stealth browser + harness")
    sp.add_argument("--proxy", help="Proxy URL (http://user:pass@host:port)")
    sp.add_argument("--profile", help="Persistent profile directory path")
    sp.add_argument("--headless", action="store_true", help="Run headless (stealth patches still active)")
    sp.add_argument("--humanize", action="store_true", help="Enable human-like mouse/keyboard behavior")
    sp.add_argument("--backend", choices=["patchright", "playwright"], default="patchright",
                    help="Playwright backend (default: patchright for max stealth)")
    sp.set_defaults(func=cmd_start)

    sp = sub.add_parser("run", help="Run code against the stealth browser")
    sp.add_argument("code", help="Python code to execute")
    sp.add_argument("--timeout", type=float, default=None, help="Max execution time in seconds")
    sp.set_defaults(func=cmd_run)

    sub.add_parser("stop", help="Stop harness daemon").set_defaults(func=cmd_stop)

    sp = sub.add_parser("status", help="Show detailed status")
    sp.add_argument("--json", dest="json_output", action="store_true", help="JSON output")
    sp.set_defaults(func=cmd_status)

    args = p.parse_args()
    if not args.command:
        p.print_help()
        sys.exit(1)
    args.func(args)


if __name__ == "__main__":
    main()
