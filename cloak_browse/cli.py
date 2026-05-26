"""cloak-browse: stealth browser + browser-harness in one CLI."""

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request

CDP_PORT = 9333
CDP_URL = f"http://127.0.0.1:{CDP_PORT}"
BH_NAME = "cloak"


def _cdp_alive() -> bool:
    try:
        with urllib.request.urlopen(f"{CDP_URL}/json/version", timeout=2) as r:
            json.loads(r.read())
            return True
    except Exception:
        return False


def _bh_sock():
    return f"/tmp/bu-{BH_NAME}.sock"


def _bh_pid_file():
    return f"/tmp/bu-{BH_NAME}.pid"


def _bh_daemon_alive() -> bool:
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(1)
        s.connect(_bh_sock())
        s.close()
        return True
    except (FileNotFoundError, ConnectionRefusedError, socket.timeout):
        return False


def _stop_bh_daemon():
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(5)
        s.connect(_bh_sock())
        s.sendall(b'{"meta":"shutdown"}\n')
        s.recv(1024)
        s.close()
    except Exception:
        pass
    try:
        pid = int(open(_bh_pid_file()).read())
        for _ in range(50):
            try:
                os.kill(pid, 0)
                time.sleep(0.1)
            except ProcessLookupError:
                break
    except (FileNotFoundError, ValueError):
        pass
    for f in (_bh_sock(), _bh_pid_file()):
        try:
            os.unlink(f)
        except FileNotFoundError:
            pass


def _start_bh_daemon():
    """Start browser-harness daemon pointed at the CloakBrowser CDP endpoint."""
    _stop_bh_daemon()

    env = {
        **os.environ,
        "BU_NAME": BH_NAME,
        "BU_CDP_URL": CDP_URL,
    }

    subprocess.Popen(
        [
            sys.executable,
            "-c",
            "from browser_harness.daemon import main; import asyncio; asyncio.run(main())",
        ],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    deadline = time.time() + 15
    while time.time() < deadline:
        if _bh_daemon_alive():
            return True
        time.sleep(0.3)

    from pathlib import Path

    log = Path(f"/tmp/bu-{BH_NAME}.log")
    tail = ""
    if log.exists():
        lines = log.read_text().strip().splitlines()
        tail = lines[-1] if lines else ""
    print(f"error: browser-harness daemon didn't start: {tail}", file=sys.stderr)
    return False


def cmd_start(args):
    """Launch stealth Chromium and wire browser-harness to it."""
    from cloakbrowser import launch, launch_persistent_context

    extra_args = [f"--remote-debugging-port={CDP_PORT}"]
    proxy = args.proxy or None
    headless = args.headless
    mode = "headless" if headless else "headed"

    print(f"launching stealth chromium ({mode}, CDP on :{CDP_PORT})...")

    if args.profile:
        ctx = launch_persistent_context(
            user_data_dir=os.path.expanduser(args.profile),
            headless=headless,
            proxy=proxy,
            args=extra_args,
            humanize=args.humanize,
        )
        cleanup = ctx.close
    else:
        browser = launch(
            headless=headless,
            proxy=proxy,
            args=extra_args,
            humanize=args.humanize,
        )
        cleanup = browser.close

    deadline = time.time() + 10
    while time.time() < deadline:
        if _cdp_alive():
            break
        time.sleep(0.3)
    else:
        print("error: CDP endpoint didn't come up", file=sys.stderr)
        cleanup()
        sys.exit(1)

    version_info = json.loads(
        urllib.request.urlopen(f"{CDP_URL}/json/version", timeout=2).read()
    )
    print(f"  browser: {version_info.get('Browser', '?')}")
    print(f"  CDP:     {CDP_URL}")
    print(f"  mode:    {mode}")

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

    stop = False

    def handle_sig(*_):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, handle_sig)
    signal.signal(signal.SIGTERM, handle_sig)

    while not stop:
        time.sleep(0.5)

    print("\nshutting down...")
    _stop_bh_daemon()
    try:
        cleanup()
    except Exception:
        pass
    print("done.")


def cmd_run(args):
    """Run a command against the stealth browser via browser-harness."""
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
    exec(args.code, ns)


def cmd_stop(args):
    """Stop harness daemon."""
    _stop_bh_daemon()
    print("harness daemon stopped.")
    if _cdp_alive():
        print(
            "note: stealth browser still running (ctrl+c the `start` process to close it)"
        )


def cmd_status(args):
    """Show status of stealth browser and harness."""
    cdp_up = _cdp_alive()
    bh_up = _bh_daemon_alive()
    print(f"stealth browser:  {'running' if cdp_up else 'not running'}")
    if cdp_up:
        try:
            info = json.loads(
                urllib.request.urlopen(f"{CDP_URL}/json/version", timeout=2).read()
            )
            print(f"  browser: {info.get('Browser', '?')}")
        except Exception:
            pass
    print(f"harness daemon:   {'running' if bh_up else 'not running'} (BU_NAME={BH_NAME})")


def main():
    p = argparse.ArgumentParser(
        prog="cloak-browse",
        description="Stealth browser controlled by browser-harness",
    )
    sub = p.add_subparsers(dest="command")

    sp = sub.add_parser("start", help="Launch stealth browser + harness")
    sp.add_argument("--proxy", help="Proxy URL (http://user:pass@host:port)")
    sp.add_argument("--profile", help="Persistent profile directory path")
    sp.add_argument(
        "--headless",
        action="store_true",
        help="Run headless (stealth patches still active)",
    )
    sp.add_argument(
        "--humanize",
        action="store_true",
        help="Enable human-like mouse/keyboard behavior",
    )
    sp.set_defaults(func=cmd_start)

    sp = sub.add_parser("run", help="Run code against the stealth browser")
    sp.add_argument("code", help="Python code to execute")
    sp.set_defaults(func=cmd_run)

    sub.add_parser("stop", help="Stop harness daemon").set_defaults(func=cmd_stop)
    sub.add_parser("status", help="Show status").set_defaults(func=cmd_status)

    args = p.parse_args()
    if not args.command:
        p.print_help()
        sys.exit(1)
    args.func(args)


if __name__ == "__main__":
    main()
