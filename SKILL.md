---
name: cloak-browse
description: Stealth browser control via CloakBrowser + browser-harness. Use when an agent needs to navigate, interact with, or extract data from web pages — especially protected sites requiring anti-detection.
---

# cloak-browse

Stealth Chromium (CloakBrowser) + thin CDP control (browser-harness) wired as one CLI. Binary-level fingerprint spoofing, patchright backend for CDP signal suppression.

## Setup

```bash
cloak-browse start                    # headed, patchright, watch it work
cloak-browse start --headless         # headless, same stealth
cloak-browse start --proxy http://user:pass@host:port --humanize
cloak-browse status                   # check browser + daemon health
cloak-browse stop                     # stop daemon (ctrl+c start to close browser)
```

## Running commands

```bash
cloak-browse run "CODE"               # exec Python with helpers pre-imported
cloak-browse run "CODE" --timeout 30  # with wall-clock timeout
```

All `browser_harness.helpers` are available in the namespace: `new_tab`, `goto_url`, `page_info`, `js`, `click_at_xy`, `press_key`, `scroll`, `capture_screenshot`, `wait_for_load`, `wait`, `list_tabs`, `switch_tab`, `cdp`, `http_get`, etc.

## Core loop

Every browser task follows this cycle. Do not skip steps on protected sites.

```
navigate → wait → screenshot → understand → act → screenshot → verify
```

```python
new_tab("https://example.com")
wait_for_load()
wait(1.5)                             # let late JS/overlays settle
capture_screenshot("/tmp/page.png")   # SEE what's there
info = page_info()                    # URL, title, viewport, scroll, dialogs
print(info)
```

## Navigation

### new_tab vs goto_url

- **`new_tab(url)`** — first navigation. Creates a tab, avoids clobbering user's active tab.
- **`goto_url(url)`** — subsequent navigation within a controlled tab. Preserves SPA state, session, referrer.
- **`ensure_real_tab()`** — call before `goto_url()` if the current tab might be stale/internal.

### Waiting

`wait_for_load()` only means `document.readyState == 'complete'`. It does NOT mean the SPA has loaded, XHR is done, or the button you want exists.

**Always pair with a real readiness check:**

```python
# Wait for a specific element
import time
def wait_el(sel, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        if js(f"!!document.querySelector({sel!r})"): return True
        wait(0.3)
    return False

new_tab("https://app.example.com")
wait_for_load()
wait_el("button.submit")
```

```python
# Wait for text to appear (better for SPAs)
def wait_text(text, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        body = js("document.body ? document.body.innerText : ''") or ""
        if text.lower() in body.lower(): return True
        wait(0.3)
    return False
```

### Dialogs

If `page_info()` returns `{"dialog": {...}}`, handle it before anything else — JS thread is frozen:

```python
info = page_info()
if "dialog" in info:
    cdp("Page.handleJavaScriptDialog", accept=True)
```

## Finding elements

Two approaches. Use whichever fits.

### A. Screenshot-driven (default for visible elements)

```python
capture_screenshot("/tmp/page.png")
# Look at the screenshot, identify the target's viewport CSS coordinates
click_at_xy(420, 315)                 # viewport pixels, NOT image pixels
wait(0.5)
capture_screenshot("/tmp/after.png")  # verify
```

If on high-DPI: divide image pixels by `js("window.devicePixelRatio")`.

### B. DOM-driven (for targeted discovery)

```python
# Find all interactive elements
elements = js("""
Array.from(document.querySelectorAll("button,a,[role=button],input,select,textarea"))
  .slice(0, 50)
  .map((e, i) => ({
    i, tag: e.tagName,
    text: (e.innerText || e.value || e.getAttribute("aria-label") || "").trim().slice(0, 60),
    rect: (() => { const r = e.getBoundingClientRect(); return {x:r.x, y:r.y, w:r.width, h:r.height} })()
  }))
""")
print(elements)

# Click the center of element 3
el = elements[3]["rect"]
click_at_xy(el["x"] + el["w"]/2, el["y"] + el["h"]/2)
```

### Scrolling into view

```python
# Scroll element into viewport, get its position, then click
pos = js("""
const el = document.querySelector('button.submit');
el.scrollIntoView({block: 'center'});
const r = el.getBoundingClientRect();
return {x: r.x + r.width/2, y: r.y + r.height/2}
""")
wait(0.3)
click_at_xy(pos["x"], pos["y"])
```

## Forms

### Fill an input

```python
# Focus + clear + type
js("document.querySelector('input[name=email]').focus()")
wait(0.2)
# Select all + delete
press_key("a", modifiers=4)  # Cmd+A (macOS) or use 2 for Ctrl
press_key("Backspace")
# Type character by character for stealth
for ch in "user@example.com":
    press_key(ch)
    wait(0.05)
```

### Native `<select>` dropdown

```python
js("""
const sel = document.querySelector('select[name=country]');
sel.value = 'US';
sel.dispatchEvent(new Event('change', {bubbles: true}));
""")
```

### File upload

```python
upload_file("input[type=file]", "/path/to/file.pdf")
```

### Submit

```python
press_key("Enter")
wait_for_load()
capture_screenshot("/tmp/result.png")
```

## Data extraction

### Use the cheapest source

1. **Known API / static HTML** → `http_get(url)` — no browser overhead
2. **Page state JSON** → `js("JSON.stringify(window.__NEXT_DATA__)")` or JSON-LD
3. **Targeted DOM** → `js("document.querySelector('.price').innerText")`
4. **Broad text** → `js("document.body.innerText")`
5. **Screenshots** → when layout/visual state matters

### Extract structured data

```python
data = js("""
Array.from(document.querySelectorAll('.product-card')).map(c => ({
  name: c.querySelector('.name')?.innerText?.trim(),
  price: c.querySelector('.price')?.innerText?.trim(),
  url: c.querySelector('a')?.href
}))
""")
print(data)
```

### Extract table data

```python
rows = js("""
Array.from(document.querySelectorAll('table tbody tr')).map(r =>
  Array.from(r.querySelectorAll('td')).map(c => c.innerText.trim())
)
""")
print(rows)
```

### Pagination

```python
results = []
while True:
    page_data = js("...extract current page...")
    results.extend(page_data)
    has_next = js("!!document.querySelector('a.next-page:not([disabled])')")
    if not has_next:
        break
    pos = js("""
    const a = document.querySelector('a.next-page');
    const r = a.getBoundingClientRect();
    return {x: r.x + r.width/2, y: r.y + r.height/2}
    """)
    click_at_xy(pos["x"], pos["y"])
    wait_for_load()
    wait(1.0)
```

## Tabs

```python
list_tabs()                           # all open tabs
current_tab()                         # active tab info
new_tab("https://other.com")          # open in new tab
switch_tab(target_id)                 # switch to a tab by ID
close_tab()                           # close current tab
```

## Stealth behavior

CloakBrowser handles fingerprint spoofing at the binary level. Patchright suppresses CDP/Playwright detection signals. **The remaining detection surface is agent behavior.**

### Timing (protected sites)

| After what | Wait |
|---|---|
| Navigation complete | 1–3s before first action |
| Before clicking a button | 0.5–2s |
| Between form fields | 0.8–1.5s |
| Before submit/confirm | 1–3s |
| After submit | 2–5s (watch for errors) |

Use `wait(random.uniform(a, b))` — never fixed delays.

### Anti-patterns to avoid

- **Instant teleport clicks** — `click_at_xy` with no prior mouse movement or delay
- **Whole-string form fills** — use per-character typing on protected forms
- **Huge scroll jumps** — `scroll(x, y, dy=-3000)` is bot-like
- **DOM bypasses** — `js("form.submit()")` instead of clicking the button
- **Removing overlays** — `js("banner.remove()")` instead of clicking Accept
- **Zero observation** — acting without screenshots between steps
- **Fixed-interval loops** — same delay between every action

### CAPTCHAs

Stop. Screenshot. Report to user. Do not retry, hack around, or continue blindly. After user solves it, wait 2–5s, screenshot, then proceed slowly.

### Cookie consent

Click the visible Accept/Reject button like a human. Don't remove the banner with JS. Wait 1–3s before clicking. Screenshot to verify it's gone.

### Proxy consistency

When using `--proxy`, timezone/locale/WebRTC IP should match the proxy's exit location. CloakBrowser's `geoip=True` handles this automatically. Without it, a German proxy with US timezone is a detection signal.

## Error recovery

```python
# Navigation failed — retry once
try:
    goto_url("https://example.com")
    if not wait_for_load(timeout=15):
        raise RuntimeError("page didn't load")
except Exception as e:
    print(f"retry: {e}")
    wait(2)
    goto_url("https://example.com")
    wait_for_load()

# Element not found — screenshot and reassess
if not js("!!document.querySelector('.target')"):
    capture_screenshot("/tmp/debug.png")
    print("element not found — check screenshot")

# Tab went stale — recover
ensure_real_tab()
print(page_info())
```

## Raw CDP

For anything helpers don't cover:

```python
# Get cookies
cookies = cdp("Network.getCookies")
print(cookies)

# Set geolocation
cdp("Emulation.setGeolocationOverride", latitude=37.7749, longitude=-122.4194, accuracy=100)

# Intercept network
cdp("Fetch.enable", patterns=[{"urlPattern": "*api*"}])
```

## Decision table

| Task | Approach |
|---|---|
| Click visible button | Screenshot → `click_at_xy()` |
| Click specific item among many | `js()` to find rect → `click_at_xy()` |
| Fill text input | Focus → per-char `press_key()` |
| Set hidden/file input | `upload_file()` or `js()` |
| Native `<select>` | `js()` set value + dispatch change |
| Custom dropdown | Click trigger → wait → click option |
| Extract text | `js("el.innerText")` |
| Extract structured data | `js()` with map/filter |
| Check page state | `page_info()` + `capture_screenshot()` |
| Handle dialog | `cdp("Page.handleJavaScriptDialog", accept=True)` |
| Static page / API | `http_get(url)` — skip the browser |
| Debug layout | `capture_screenshot(path, full=True)` |
