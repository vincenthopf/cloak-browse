<p align="center">
  <img src="assets/hero.png" alt="cloak-browse" width="700">
</p>

<h1 align="center">cloak-browse</h1>

<p align="center">A small CLI that launches CloakBrowser and exposes it through browser-harness.</p>

Current package version: `0.2.1` (unreleased patch).

## Supported environment

CloakBrowse requires Python 3.11 through 3.13. The fast test and package smoke suite runs on Linux, macOS, and Windows. A separate Linux integration job downloads the CloakBrowser Chromium build and exercises the real browser path once, rather than downloading the large binary in every matrix job.

The first browser launch downloads roughly 150–200 MB. The package does not bundle Chromium.

## Install

```bash
uv tool install git+https://github.com/vincenthopf/cloak-browse.git
cloak-browse --version
```

For repository development:

```bash
uv sync --frozen
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv build
uv run python scripts/check_dist.py
```

## Commands

Start one managed browser session in the foreground:

```bash
cloak-browse start
cloak-browse start --headless
cloak-browse start --profile ~/.local/share/cloak-profile
cloak-browse start --proxy http://user:pass@proxy.example:8080
```

Run trusted Python through browser-harness:

```bash
cloak-browse run "new_tab('https://example.com')"
cloak-browse run "print(page_info())"
cloak-browse run "print(js('document.body.innerText')[:2000])" --timeout 30
```

Inspect or stop the managed session:

```bash
cloak-browse status
cloak-browse status --json
cloak-browse stop
```

`run` executes the supplied Python with your user permissions. It is not a sandbox. Do not pass untrusted text as code. A timeout terminates the runner subprocess and exits with code `124`; it does not leave a Python thread executing in the caller.

## Lifecycle and ownership

CloakBrowse supports one local managed session. It binds CDP to `127.0.0.1:9333` and uses the browser-harness daemon name `cloak` inside a per-session private runtime directory.

The `start` process owns the live CloakBrowser object and remains in the foreground. Session state records the owner process identity, a session UUID, and the browser UUID exposed by the CDP WebSocket URL. `stop` writes a private, session-scoped shutdown request. The foreground owner receives that request and closes the daemon and browser through their supported APIs.

CloakBrowse never sends a signal to a PID read from a stale file. If the `start` process crashes and its browser remains alive, the state becomes `orphaned`; close that browser manually. This narrower contract prevents PID reuse from terminating an unrelated process.

CloakBrowse refuses to start when any listener already owns port `9333`. It does not assume that an arbitrary CDP-compatible endpoint is its browser. Close the other process before starting CloakBrowse.

The session file is atomically replaced and private to the current user. Its native cache location is selected by `platformdirs`:

- Linux: `~/.cache/cloak-browse`
- macOS: `~/Library/Caches/cloak-browse`
- Windows: `%LOCALAPPDATA%\cloak-browse\Cache`

Set `CLOAK_BROWSE_CACHE_DIR` to override that directory. Raw proxy URLs are never stored. Status output contains only a redacted scheme, host, and port.

## Status JSON contract

`cloak-browse status --json` writes exactly one JSON object followed by one newline to stdout. Diagnostics are written to stderr. The current schema version is `1`:

```json
{
  "browser": {
    "cdp_url": "http://127.0.0.1:9333",
    "owned": null,
    "state": "stopped",
    "tabs": null,
    "version": null,
    "websocket": false
  },
  "daemon": {
    "name": null,
    "state": "stopped"
  },
  "diagnostics": [],
  "healthy": false,
  "schema_version": 1,
  "session": {
    "backend": null,
    "humanize": null,
    "id": null,
    "mode": null,
    "owner_alive": null,
    "phase": null,
    "present": false,
    "profile": null,
    "proxy": null,
    "started_at": null,
    "valid": false
  },
  "state": "stopped"
}
```

Status exits `0` for `stopped`, `starting`, `running`, and `stopping`. It exits `1` for an invalid session, a stale or orphaned session, a degraded session, or a foreign endpoint on port `9333`.

Other command exit behavior:

- `0`: command completed successfully
- `1`: operational or lifecycle failure
- `2`: command-line usage error
- `124`: `run --timeout` expired
- other `run` codes: the browser-harness runner's exit code

## Browser helpers

The pinned browser-harness release provides these supported helpers:

`new_tab`, `goto_url`, `page_info`, `js`, `click_at_xy`, `fill_input`, `type_text`, `press_key`, `capture_screenshot`, `wait_for_load`, `wait_for_element`, `list_tabs`, and `switch_tab`.

Use `type_text("text")` for normal text entry. It uses CDP `Input.insertText`. Direct CDP is also available:

```bash
cloak-browse run "cdp('Input.insertText', text='hello@example.com')"
```

Use `press_key()` for Enter, Tab, Escape, arrows, and shortcuts. Do not implement text entry with a per-character `press_key()` loop.

CloakBrowser uses stock Playwright and supports authenticated proxies directly. The deprecated `--backend` option remains accepted for command compatibility, but `patchright` is mapped to Playwright with a diagnostic because CloakBrowser removed Patchright support in 0.4.0.

## Dependency and release policy

Runtime dependencies are exact pins in `pyproject.toml`; `uv.lock` is the complete cross-platform resolution. CloakBrowser and Playwright are kept on their current compatible releases. Browser-harness currently requires websockets 15.0.1, so that package remains pinned until browser-harness supports a newer release. Regenerate the lockfile and run all platform and browser integration jobs whenever the tested set changes.

`cloak_browse/_version.py` is the package version source. `scripts/check_release.py` verifies the Hatch version path, changelog, README, and release tag. Before creating `vX.Y.Z`, replace `Unreleased` in the matching changelog heading with an ISO date. The release workflow validates the exact tagged commit before publishing its wheel and sdist.

## Troubleshooting

**Port 9333 is already in use**

Close the process using that port. CloakBrowse will not attach to or terminate it.

**State is `orphaned`**

The foreground owner died while its browser still answered on the recorded CDP browser UUID. Close the browser manually, then run `cloak-browse stop` to clear the stale daemon and session state.

**Daemon startup failed**

The stderr message includes the end of the per-session browser-harness log. Confirm the browser CDP endpoint is WebSocket-ready and retry.

**Session file is corrupt**

`start` moves it to a timestamped `session.corrupt.*.json` file and reports the path. `status --json` reports `invalid_session` without mixing diagnostics into stdout.

## License

MIT
