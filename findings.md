# CloakBrowse maintenance findings

This document records the architecture and validation conclusions for the maintenance pass anchored at commit `7368fda0296c3e5a6e19c5e1e7cee65e059ce0fd` on 2026-09-01. It replaces the earlier Unix-socket-only description, which no longer matched browser-harness or the cross-platform implementation.

## Inspected change sequence

The maintenance review treated these commits as one sequence:

- `8198234` added Patchright defaults, session metadata, stale cleanup, timeout handling, richer status output, and agent documentation.
- `67ec96d` switched daemon communication to browser-harness cross-platform IPC and added Windows-oriented spawning.
- `7368fda` corrected one text-entry warning but left contradictory examples and decision guidance.

The sequence introduced useful cross-platform behavior but left the ownership, state, output, dependency, and validation contracts incomplete.

## Verified baseline defects

At the inspected head:

- `status --json` printed the human report before JSON, so stdout was not one parseable JSON document.
- Partial and stopped status paths could rely on variables created only in the running path.
- Stale cleanup attempted to terminate `daemonPid` and `browserPid`, but the session writer did not record either field.
- A stale integer PID could be reused by an unrelated process, making signal-based cleanup unsafe.
- Session state used `~/.cache` on every platform, was written in place, and stored the raw proxy URL.
- Any listener on fixed port `9333` could be confused with the managed browser.
- `run --timeout` returned while a daemon thread could continue executing code.
- Broad exception handling hid daemon and cleanup failures.
- `browser-harness` came from a mutable Git branch and `websockets`, which runtime code imported directly, was undeclared.
- CI omitted Windows, downloaded a large browser in every matrix cell, and had not run on the inspected head.
- A release tag could publish artifacts without validating the exact tagged commit or checking metadata agreement.
- Text-entry guidance alternated between `Input.insertText` and per-character `press_key()` loops.

## Current architecture

### Browser ownership

`cloak-browse start` is the sole browser owner. It launches CloakBrowser through its supported Python API and keeps that returned browser or persistent-context object alive in the foreground. Shutdown closes that object directly.

The session record stores the owner PID and a platform-specific process start token. The token is used only to determine whether the same foreground owner is still alive. It is never authority to signal a process.

If the owner disappears while the recorded browser UUID is still visible on CDP, the session is marked `orphaned`. The user must close the browser manually. This is intentionally narrower than a best-effort kill because no portable, durable identity exposed by the current CloakBrowser API is safe enough to terminate a browser after its Python owner has disappeared.

### CDP identity and collisions

CloakBrowse still exposes CDP only on loopback port `9333` to preserve the existing CLI surface. It records the browser UUID parsed from `/json/version`'s `webSocketDebuggerUrl`, probes the WebSocket, and compares that UUID on later operations.

A listener on `9333` before startup is a hard collision. CloakBrowse does not attach to it, stop it, or assume that a valid CDP response proves ownership. A listener that appears after the managed browser exits is reported as foreign and left untouched.

### Harness ownership

The pinned browser-harness release uses an AF_UNIX socket on POSIX and an authenticated loopback TCP endpoint on Windows. CloakBrowse supplies a short, per-session `BH_RUNTIME_DIR` plus private per-session temporary and configuration directories. This prevents the global daemon name `cloak` from colliding across stale runtime files.

Daemon startup and shutdown run through browser-harness's public administration functions. Its shutdown path verifies the daemon over live IPC before any internal escalation. CloakBrowse does not read or signal a harness PID itself.

### Session state

The current session schema is version `1`. The session and stop-request files are atomically replaced, flushed, and user-private where the platform supports POSIX modes. Cache paths come from `platformdirs`, with `CLOAK_BROWSE_CACHE_DIR` available for deterministic automation and tests.

The state file contains only the redacted proxy endpoint. Credentials, query strings, and signed connection data are not persisted.

Corrupt state is reported without being interpreted. A new `start` quarantines the file under a timestamped name before proceeding.

### Stop semantics

`cloak-browse stop` has three explicit outcomes:

1. With a live owner, it writes a session-scoped stop request and waits for the owner to close both components.
2. With no owner and no managed browser, it stops a verified recorded daemon if present and clears stale state.
3. With no owner but an apparently managed browser, it stops the verified daemon, marks the browser orphaned, and requires manual browser closure.

No branch kills a process based on a stored PID.

### Runner timeout

`cloak-browse run` invokes `python -m browser_harness.run` as a subprocess and supplies code on stdin. The timeout is enforced by the subprocess API. Expiry terminates the runner and returns `124`, so no in-process thread continues after the CLI exits.

The command remains an arbitrary-code boundary. Input is trusted Python with the user's permissions.

## Machine output

Status schema version `1` always contains `healthy`, `state`, `browser`, `daemon`, `session`, and `diagnostics`. JSON mode writes exactly one compact object and one newline to stdout. Diagnostics are repeated on stderr for operators and log collection.

Stopped and partial states use explicit `null` values rather than missing locals. Healthy running and normal transitional states exit `0`; invalid, stale, orphaned, degraded, and foreign states exit `1`.

## Dependency decision

The maintenance release pins a tested set:

- `browser-harness==0.1.10`
- `cloakbrowser==0.3.25`
- `patchright==1.58.2`
- `playwright==1.58.0`
- `platformdirs==4.11.3`
- `websockets==15.0.1`

CloakBrowser 0.3.25 is intentional. Later CloakBrowser releases removed the `backend` parameter, while CloakBrowse currently exposes `--backend patchright|playwright`. Moving to that newer API would be a compatibility change rather than maintenance.

`browser-harness` is now a released package instead of a mutable Git branch. Every directly imported runtime dependency is declared. `uv.lock` is the complete resolution and must be updated with the direct pins as one compatibility set.

## Text entry decision

The supported default is `type_text()`, whose pinned implementation dispatches CDP `Input.insertText`. Direct `cdp("Input.insertText", text=...)` is equivalent. `press_key()` is reserved for Enter, Tab, Escape, arrows, and shortcuts. Documentation no longer recommends per-character key loops for ordinary text.

## Validation model

Fast tests avoid browser downloads, real ports, and real daemons. They inject filesystem paths, process identity functions, clocks, HTTP/WebSocket probes, browser launchers, and subprocess runners. Coverage includes:

- parser behavior and exit codes
- exact JSON stdout and diagnostic stderr
- missing, corrupt, partial, stale, foreign, and orphaned state
- atomic file replacement and permissions
- CDP HTTP, WebSocket, timeout, malformed JSON, and wrong-browser behavior
- daemon success, timeout, log-tail reporting, isolation, and cleanup
- Linux, macOS, and Windows process identity branches
- proxy redaction
- startup interruption, shutdown, and timeout behavior
- direct dependency and helper contracts
- wheel, sdist, entry point, and release metadata contracts

CI runs the fast suite and package smoke checks on Windows, macOS, and Linux for Python 3.11 through 3.13. Quality and package jobs run once on Linux. A limited Linux browser job performs the binary download and real start/status/run/stop path.

The release workflow repeats validation against the exact tag, checks that `vX.Y.Z` matches package metadata and a dated changelog entry, builds from that commit, verifies package contents, installs the wheel in a clean environment, and only then creates the GitHub release.

## Version decision

No repository tag or release established `0.2.1`, while the inspected package still declared `0.2.0` and recent work described itself as `v0.2.1`. This maintenance branch treats `0.2.1` as the unreleased patch that includes the recent feature sequence and its stabilization. `_version.py` is the single package source; Hatch reads it dynamically. The changelog remains `Unreleased` until the release commit supplies a date.

## Remaining deliberate limits

- The public CLI still uses one fixed CDP port and one local session. Dynamic multi-session ports would be a product change.
- A browser left after owner failure requires manual closure because safe cross-process browser identity is unavailable.
- Real binary validation runs on one supported Linux configuration. The cross-platform matrix proves parsing, lifecycle logic, packaging, and platform branches without multiplying large downloads.
