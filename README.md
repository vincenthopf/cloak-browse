<p align="center">
  <img src="assets/hero.png" alt="cloak-browse" width="700">
</p>

<h1 align="center">cloak-browse</h1>

<p align="center">
  Stealth browser CLI — <a href="https://github.com/CloakHQ/CloakBrowser">CloakBrowser</a> + <a href="https://github.com/browser-use/browser-harness">browser-harness</a> wired together.
</p>

<p align="center">
  Launch a fingerprint-patched Chromium and control it from the terminal.<br>
  Headed or headless. Stealth in both modes.
</p>

---

## What this does

CloakBrowser ships a **patched Chromium binary** with anti-detection built into the C++ source — not injected via JavaScript. Fingerprint seeds randomize canvas, WebGL, audio, and fonts per launch. `navigator.webdriver` is suppressed at the binary level.

browser-harness gives you **CDP control from the command line** — navigate, click, screenshot, extract text, run arbitrary JS.

cloak-browse wires them together: one command launches the stealth browser with a CDP port exposed, starts the harness daemon, and you're ready to go.

## Install

One command. Works on macOS, Linux, and Windows. The stealth Chromium binary downloads automatically on first run (~150MB).

```bash
# macOS / Linux
uv tool install git+https://github.com/vincenthopf/cloak-browse.git

# Windows (PowerShell)
uv tool install git+https://github.com/vincenthopf/cloak-browse.git

# pipx (any platform)
pipx install git+https://github.com/vincenthopf/cloak-browse.git
```

That's it. Run `cloak-browse start` and the browser launches.

> **Need uv?** `curl -LsSf https://astral.sh/uv/install.sh | sh` (macOS/Linux) or `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"` (Windows)

## Usage

**Start the stealth browser** (new terminal, stays running):

```bash
cloak-browse start              # headed — watch it work
cloak-browse start --headless   # headless — stealth patches still active
```

**Run commands against it** (from any other terminal):

```bash
cloak-browse run "new_tab('https://bot.incolumitas.com')"
cloak-browse run "print(page_info())"
cloak-browse run "print(visible_text()[:2000])"
cloak-browse run "capture_screenshot('/tmp/shot.png')"
```

**Check status / stop:**

```bash
cloak-browse status
cloak-browse stop       # stops harness daemon
                        # ctrl+c the start process to close the browser
```

## Options

| Flag | What it does |
|---|---|
| `--headless` | No visible window. Same stealth patches. |
| `--proxy URL` | Route through a proxy (`http://user:pass@host:port`) |
| `--profile DIR` | Persist cookies/localStorage across sessions |
| `--humanize` | Human-like mouse movement and keyboard timing |

## How it works

```
cloak-browse start
  │
  ├─ cloakbrowser.launch(headless=False, args=["--remote-debugging-port=9333"])
  │    └─ Downloads + launches patched Chromium with --fingerprint=<random>
  │
  └─ browser-harness daemon connects via BU_CDP_URL=http://127.0.0.1:9333
       └─ CDP session attached, helpers ready

cloak-browse run "..."
  │
  └─ Loads browser_harness.helpers into namespace, exec's your code
       └─ new_tab, goto_url, click_at_xy, js, visible_text, capture_screenshot, ...
```

## Available helpers

Everything from [browser-harness](https://github.com/browser-use/browser-harness) is available in `run` commands:

| Helper | What it does |
|---|---|
| `new_tab(url)` | Open URL in a new tab |
| `goto_url(url)` | Navigate current tab |
| `page_info()` | URL, title, viewport, scroll position |
| `visible_text()` | Extracted page text |
| `js(expression)` | Run JavaScript, return result |
| `click_at_xy(x, y)` | Click at coordinates |
| `fill_input(selector, text)` | Type into an input |
| `press_key(key)` | Keyboard input |
| `capture_screenshot(path)` | Save PNG screenshot |
| `wait_for_load()` | Wait for page load |
| `wait_for_element(sel)` | Wait for CSS selector |
| `list_tabs()` | All open tabs |
| `switch_tab(id)` | Switch to a tab |

## Stealth details

CloakBrowser's patched Chromium applies at the binary level:

- `--fingerprint=<seed>` — randomizes canvas, WebGL, audio, font fingerprints
- `--fingerprint-platform=<os>` — platform spoofing (native on macOS)
- `--fingerprint-timezone` / `--lang` — set via binary flags, not detectable CDP emulation
- Strips `--enable-automation` — no `navigator.webdriver = true`
- Strips `--enable-unsafe-swiftshader` — no detectable software WebGL renderer
- WebRTC IP spoofing via `--fingerprint-webrtc-ip`

These work identically in headed and headless mode.

## License

MIT
