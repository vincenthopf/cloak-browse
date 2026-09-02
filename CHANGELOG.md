# Changelog

All notable changes to this project are documented in this file.

## [0.2.1] - Unreleased

### Added

- Deterministic unit and contract coverage for CLI output, session state, CDP probing, daemon control, process identity, browser launching, package contents, and release metadata.
- Windows fast-suite coverage and a limited browser integration job.

### Changed

- Session state now uses a versioned schema, atomic private writes, native cache locations, and redacted proxy metadata.
- Dependencies are pinned as a tested set and resolved through `uv.lock`, including CloakBrowser 0.5.10 and Playwright 1.62.0.
- CloakBrowser now uses its current stock-Playwright API. The deprecated `--backend` option remains accepted for command compatibility.
- `stop` now requests shutdown from the foreground browser owner and never signals an unverified PID.

### Fixed

- `status --json` now writes exactly one stable JSON document to stdout.
- Stale, partial, corrupt, foreign, and orphaned lifecycle states now produce explicit diagnostics and exit codes.
- `run --timeout` now terminates a subprocess instead of abandoning an executing daemon thread.
- Text-entry documentation now consistently uses `type_text()` or `Input.insertText` for text and reserves `press_key()` for keys and shortcuts.
- Browser startup no longer passes the removed `backend` argument to current CloakBrowser releases.
- POSIX-only session permission calls no longer break static validation on Windows.
- Browser-harness shutdown and session cleanup now retry transient Windows file locks and preserve state when files remain, instead of timing out or silently leaking harness data.
- Session phase remains `starting` until the harness daemon is verified, preventing concurrent commands from spawning duplicate daemons.
