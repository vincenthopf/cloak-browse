---
name: cloak-browse
description: Launch and control a managed CloakBrowser session through browser-harness.
---

# CloakBrowse

CloakBrowse runs one local managed browser on `127.0.0.1:9333` and one isolated browser-harness daemon named `cloak`.

## Start and inspect

```bash
cloak-browse start
cloak-browse start --headless
cloak-browse status --json
```

`start` stays in the foreground because it owns the browser handle. Leave it running while issuing commands from another shell.

Before starting, inspect `cloak-browse status --json`. Do not start when `state` is `foreign_endpoint`, `orphaned`, or `degraded`. Resolve the reported condition first.

## Run browser work

```bash
cloak-browse run "new_tab('https://example.com')"
cloak-browse run "print(page_info())"
cloak-browse run "print(js('document.body.innerText')[:2000])" --timeout 30
```

The code argument is trusted Python, not a sandbox. Never interpolate untrusted content into it. `--timeout` terminates the runner subprocess and returns `124`.

Supported helpers in the pinned browser-harness release include:

- Navigation and state: `new_tab`, `goto_url`, `page_info`, `js`, `list_tabs`, `switch_tab`
- Interaction: `click_at_xy`, `fill_input`, `type_text`, `press_key`
- Low-level and waits: `cdp`, `capture_screenshot`, `wait_for_load`, `wait_for_element`

## Text entry

Use `type_text()` for text:

```bash
cloak-browse run "click_at_xy(420, 300); type_text('hello@example.com')"
```

`type_text()` uses `Input.insertText`. The direct form is:

```bash
cloak-browse run "cdp('Input.insertText', text='hello@example.com')"
```

Use `press_key()` for discrete keys and shortcuts:

```bash
cloak-browse run "press_key('TAB'); press_key('ENTER')"
```

Do not type text with a per-character `press_key()` loop.

## Stop and recovery

```bash
cloak-browse stop
```

`stop` sends a private request to the live foreground owner, which closes the harness and browser. CloakBrowse does not kill a PID from session state.

If `status --json` reports `orphaned`, close the remaining browser manually, then run `cloak-browse stop` to clean the recorded daemon and state. If it reports `foreign_endpoint`, close the unrelated process using port `9333`. Never terminate either process based only on a stored PID.

## Status contract

`status --json` emits one schema-versioned JSON value on stdout. Diagnostics use stderr. Exit `0` covers `stopped`, `starting`, `running`, and `stopping`; exit `1` covers invalid, stale, orphaned, degraded, and foreign states.

Raw proxy credentials are not persisted or printed. For an authenticated proxy, start with `--backend playwright` because the pinned CloakBrowser Patchright backend does not support proxy authentication.
