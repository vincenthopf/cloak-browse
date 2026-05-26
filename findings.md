# Findings: AI Browser Harness Architectures

A factual survey of the major AI browser harness projects, the architectural choices each one makes, and where browser-harness (the upstream dependency of cloak-browse) sits in that landscape. Sources are each project's public README at the time of survey.

---

## 1. Projects surveyed

| Project | Language | What it is | License |
|---|---|---|---|
| Lightpanda | Zig | New browser written from scratch, not a Chromium fork | (open source, beta) |
| Browserbase Stagehand | TypeScript / Python | SDK on top of Playwright with AI verbs (`act`, `extract`, `agent`) | MIT |
| browser-use | Python | Agent framework with CLI and persistent browser daemon | (open source) |
| Microsoft Playwright MCP | Node.js | MCP server wrapping Playwright; accessibility-snapshot driven | (Microsoft OSS) |
| Skyvern | Python / TypeScript | Playwright extension adding AI verbs; swarm-of-agents planner; vision LLMs | AGPL-3.0 (core) |
| Steel | Node.js | Self-hostable browser-as-a-service API; Puppeteer/Playwright/Selenium compatible | Apache 2.0 |
| browser-harness (browser-use org) | Python | Low-level CDP harness exposed as importable helpers and a daemon | (open source) |
| cloakbrowser | C++ patched Chromium + Python launcher | Fingerprint-patched Chromium binary | (open source) |

---

## 2. The architectural axes

The surveyed projects differ along a small number of orthogonal axes. Understanding the axes makes the trade-offs explicit.

### 2.1 Browser engine

- **Forked/patched Chromium:** cloakbrowser. Anti-detection applied in C++ source, fingerprint seeds randomize canvas/WebGL/audio/fonts per launch, `navigator.webdriver` suppressed at binary level, `--enable-automation` and `--enable-unsafe-swiftshader` stripped.
- - **Stock browsers driven by CDP/Playwright:** Stagehand, browser-use, Playwright MCP, Skyvern, Steel. Use whatever Chrome/Chromium/Firefox/WebKit is installed.
  - - **New browser from scratch:** Lightpanda. Written in Zig, html5ever for parsing, v8 for JS, libcurl for HTTP. Benchmarks reported in their README: 123MB peak memory vs 2GB for headless Chrome on 100 pages, ~5s vs ~46s execution time for the same workload on an AWS m5.large.
    - - **Coverage trade-off (stated by Lightpanda):** "There are hundreds of Web APIs. Developing a browser (even just for headless mode) is a huge task. Coverage will increase over time." Listed implemented features: CORS, HTTP loader, HTML parser, DOM tree, JS via v8, DOM APIs, Ajax, XHR, Fetch, DOM dump, CDP/websockets server, click, input form, cookies, custom HTTP headers, proxy, network interception, robots.txt.
     
      - ### 2.2 Control protocol
     
      - - **CDP directly:** cloakbrowser exposes `--remote-debugging-port`; browser-harness connects via `BU_CDP_URL`; Steel uses Puppeteer/CDP; Lightpanda exposes a CDP/websockets server so existing Puppeteer/Playwright clients work.
        - - **Playwright on top of CDP:** Stagehand, Playwright MCP, Skyvern. Inherits Playwright's auto-waiting, locators, and multi-browser support.
          - - **MCP (Model Context Protocol) over stdio or HTTP:** Playwright MCP (native), Lightpanda (`lightpanda mcp`), Skyvern (supports MCP), browser-use (Claude Code skill). Playwright MCP also supports SSE/HTTP transport via `--port`.
            - - **CLI shell:** browser-use ships `browser-use open/state/click/type/screenshot/close`. cloak-browse ships `cloak-browse start/run/stop/status` and `run` execs Python in a namespace of helpers.
             
              - ### 2.3 Page-state representation given to the LLM
             
              - - **Accessibility tree / structured snapshot:** Playwright MCP ("Uses Playwright's accessibility tree, not pixel-based input … No vision models needed, operates purely on structured data"). browser-use's `state` command prints indexed clickable elements.
                - - **Visual / pixel input:** Skyvern ("relies on Vision LLMs to learn and interact with the websites … resistant to website layout changes, as there are no pre-determined XPaths or other selectors").
                  - - **Mixed (selector + AI fallback):** Skyvern's `page.click("#submit-btn", prompt="Click the Submit button")` tries the selector first and falls back to AI if it fails.
                    - - **Raw text / DOM dump:** cloak-browse + browser-harness (`visible_text()`, `js(expression)`). No first-class accessibility-tree or indexed-element representation in the documented helper list.
                     
                      - ### 2.4 Action interface exposed to the user / agent
                     
                      - - **Imperative low-level:** browser-harness (`new_tab`, `goto_url`, `click_at_xy`, `fill_input(selector, text)`, `press_key`, `capture_screenshot`, `wait_for_load`, `wait_for_element`, `list_tabs`, `switch_tab`, `js`, `page_info`, `visible_text`). Steel via Puppeteer/Playwright/Selenium.
                        - - **Natural-language verbs added on top of Playwright:** Stagehand (`act`, `extract`, `agent`), Skyvern (`page.act`, `page.extract`, `page.validate`, `page.prompt`, `page.agent.run_task`, `page.agent.login`, `page.agent.download_files`, `page.agent.run_workflow`).
                          - - **High-level autonomous agent:** browser-use `Agent(task=..., llm=...).run()`, Skyvern `run_task(prompt=..., data_extraction_schema=...)`.
                           
                            - ### 2.5 Caching and self-healing
                           
                            - - **Auto-cache of AI-resolved actions:** Stagehand. README: "Stagehand's auto-caching combined with self-healing remembers previous actions, runs without LLM inference, and knows when to involve AI whenever the website changes and your automation breaks."
                              - - **No caching documented:** browser-use, Playwright MCP, Skyvern, Steel, browser-harness, cloak-browse.
                               
                                - ### 2.6 Stealth / anti-detection
                               
                                - - **Binary-level patches:** cloakbrowser. Stated mechanisms: `--fingerprint=<seed>` randomizes canvas/WebGL/audio/font; `--fingerprint-platform=<os>` for platform spoofing; timezone and language set via binary flags (not CDP emulation); `--enable-automation` stripped; `--enable-unsafe-swiftshader` stripped; WebRTC IP spoofing via `--fingerprint-webrtc-ip`. Same patches work in headed and headless mode.
                                  - - **Stealth plugins / fingerprint management at the JS layer:** Steel ("Includes stealth plugins and fingerprint management").
                                    - - **Cloud-only anti-bot, captcha solvers, proxy rotation:** Skyvern Cloud, Browserbase, Browser Use Cloud.
                                      - - **None documented:** Lightpanda, Playwright MCP, browser-harness on its own.
                                       
                                        - ### 2.7 Session / state persistence
                                       
                                        - - **Persistent profile (full user data dir):** Playwright MCP (`--user-data-dir`, default location per OS, one workspace = one profile via workspace-hash). cloak-browse (`--profile DIR`). Skyvern (connect to local Chrome at `127.0.0.1:9222`).
                                          - - **Storage-state file (cookies + localStorage only):** Playwright MCP (`--storage-state PATH`).
                                            - - **Session API:** Steel `/sessions` endpoint creates a stateful browser session with options like `blockAds`, `proxyUrl`, `dimensions`, `isSelenium`.
                                              - - **Init scripts / init pages:** Playwright MCP (`--init-script` runs in every page before page scripts; `--init-page` runs once on the Playwright `page` object, useful for `grantPermissions`, `setGeolocation`, viewport size, etc.).
                                               
                                                - ### 2.8 Capability / tool-surface management
                                               
                                                - - **Opt-in capabilities:** Playwright MCP `--caps=vision,pdf,devtools,network,storage,testing`. Default tool set is minimal "core automation"; vision and others are opt-in. Rationale stated in their README: smaller tool schema = more context for the model.
                                                  - - **Single fixed surface:** browser-harness, Stagehand, browser-use, Skyvern, Steel, cloak-browse.
                                                   
                                                    - ### 2.9 Process model
                                                   
                                                    - - **Long-running daemon with IPC:** cloak-browse + browser-harness (Unix socket at `/tmp/bu-<name>.sock`, PID file at `/tmp/bu-<name>.pid`, CDP at `127.0.0.1:9333`). browser-use ("The CLI keeps the browser running between commands for fast iteration").
                                                      - - **Per-invocation server:** Playwright MCP (stdio or HTTP), Steel (HTTP server on port 3000, debug on 9223).
                                                        - - **Library in user's process:** Stagehand, Skyvern SDK, browser-use Python API.
                                                          - - **Docker container:** Steel (`ghcr.io/steel-dev/steel-browser`), Lightpanda (`lightpanda/browser:nightly`).
                                                           
                                                            - ### 2.10 Observability / debugging
                                                           
                                                            - - **Live view of the running browser:** Skyvern (livestreaming the viewport for debugging and intervention). Steel (built-in UI to view/debug sessions at `http://localhost:3000/ui`, console debugger at `:9223`).
                                                              - - **Console message capture with level filter:** Playwright MCP `--console-level error|warning|info|debug`.
                                                                - - **Network logging:** Steel ("Built-in request logging"). Playwright MCP network capability (opt-in).
                                                                  - - **Saved session artifacts:** Playwright MCP `--save-session` writes snapshots/console/network to a directory.
                                                                    - - **None documented:** browser-harness, cloak-browse beyond `capture_screenshot()`.
                                                                     
                                                                      - ### 2.11 Quick-action read-only endpoints
                                                                     
                                                                      - - **REST endpoints for one-shot scrapes:** Steel `/v1/scrape`, `/v1/screenshot`, `/v1/pdf`. Stated as "Ideal for simple, read-only, on-demand jobs."
                                                                        - - **CLI one-shot fetch:** Lightpanda `lightpanda fetch --dump html|markdown --wait-until/--wait-ms/--wait-selector/--wait-script <url>`.
                                                                          - - **None documented:** browser-harness, cloak-browse (would require composing helpers in a `run` call).
                                                                           
                                                                            - ### 2.12 Authentication / credentials
                                                                           
                                                                            - - **Password-manager integrations:** Skyvern (Bitwarden, 1Password, LastPass, custom credential HTTP API).
                                                                              - - **2FA / TOTP:** Skyvern (QR-based, email-based, SMS-based).
                                                                                - - **Login via stored credentials:** Skyvern `page.agent.login(credential_type, credential_id)`.
                                                                                  - - **Secrets via dotenv:** Playwright MCP `--secrets`.
                                                                                    - - **Profile-based (cookies persist):** cloak-browse, Playwright MCP, Skyvern (connect to local Chrome).
                                                                                     
                                                                                      - ### 2.13 Deployment / hosting story
                                                                                     
                                                                                      - - **Self-host only:** cloak-browse, browser-harness, Lightpanda (binary or Docker).
                                                                                        - - **Self-host + managed cloud (with stronger features in cloud):** browser-use (Browser Use Cloud has stealth, proxy rotation, captcha solving, 1000+ integrations, persistent filesystem/memory; open-source agent recommended to pair with cloud browsers). Skyvern (Skyvern Cloud bundles anti-bot, proxy network, captcha solvers; Skyvern's anti-bot measures are cloud-exclusive). Stagehand (paired with Browserbase). Steel (Steel Cloud).
                                                                                         
                                                                                          - ---

                                                                                          ## 3. browser-harness specifically

                                                                                          What the project (as used by cloak-browse) exposes per the cloak-browse README and `cli.py`:

                                                                                          - Helpers: `new_tab(url)`, `goto_url(url)`, `page_info()`, `visible_text()`, `js(expression)`, `click_at_xy(x, y)`, `fill_input(selector, text)`, `press_key(key)`, `capture_screenshot(path)`, `wait_for_load()`, `wait_for_element(sel)`, `list_tabs()`, `switch_tab(id)`.
                                                                                          - - Process model: daemon at `/tmp/bu-<BU_NAME>.sock`, started by `python -c "from browser_harness.daemon import main; asyncio.run(main())"`, configured via env `BU_NAME` and `BU_CDP_URL`.
                                                                                            - - Invocation in cloak-browse: `cloak-browse run "<code>"` imports `browser_harness.helpers`, builds a namespace of every non-underscore attribute, and `exec()`s the user-supplied code in that namespace.
                                                                                             
                                                                                              - What is **not** documented as present in browser-harness based on the cloak-browse README:
                                                                                             
                                                                                              - - Accessibility-tree snapshot with stable element references.
                                                                                                - - Indexed clickable-element listing (browser-use style).
                                                                                                  - - Natural-language `act` / `extract` / `validate` verbs.
                                                                                                    - - Action caching or self-healing.
                                                                                                      - - MCP server.
                                                                                                        - - Opt-in capability flags.
                                                                                                          - - Init-script / init-page hooks.
                                                                                                            - - Storage-state file (separate from full profile).
                                                                                                              - - Live debug view.
                                                                                                                - - Quick-action read-only REST endpoints.
                                                                                                                  - - Password-manager / 2FA integrations.
                                                                                                                   
                                                                                                                    - ---
                                                                                                                    
                                                                                                                    ## 4. Where each approach reportedly succeeds and where it has stated limits
                                                                                                                    
                                                                                                                    The bullets below are claims made in each project's own README, not external evaluations.
                                                                                                                    
                                                                                                                    ### 4.1 Lightpanda
                                                                                                                    - Stated strength: dramatic memory and speed improvement over headless Chrome on their benchmark, designed for AI/automation workloads, ships native MCP.
                                                                                                                    - - Stated limit: beta, "you may still encounter errors or crashes", Web API coverage is incomplete and growing. No stealth features listed.
                                                                                                                     
                                                                                                                      - ### 4.2 Browserbase Stagehand
                                                                                                                      - - Stated strength: mix of code and natural language in the same script; auto-caching and self-healing; preview AI actions before running; "Write once, run forever".
                                                                                                                        - - Stated limit: tightly coupled to Browserbase (cloud); requires LLM API keys for AI verbs.
                                                                                                                         
                                                                                                                          - ### 4.3 browser-use
                                                                                                                          - - Stated strength: persistent browser between CLI commands; fully open-source agent; many LLM providers supported; cloud add-on for stealth and scale.
                                                                                                                            - - Stated limit: stealth/proxy/captcha features are cloud-only; the open-source agent is recommended to be paired with the cloud browsers.
                                                                                                                             
                                                                                                                              - ### 4.4 Microsoft Playwright MCP
                                                                                                                              - - Stated strength: "Fast and lightweight. Uses Playwright's accessibility tree, not pixel-based input. LLM-friendly. No vision models needed, operates purely on structured data. Deterministic tool application. Avoids ambiguity common with screenshot-based approaches." Wide MCP client compatibility (Claude, Cursor, Copilot, Gemini CLI, Windsurf, etc.). Opt-in capabilities to control schema size. Rich configuration (`--init-script`, `--storage-state`, `--device`, `--user-agent`, `--viewport-size`, `--secrets`, `--console-level`, `--save-session`, etc.).
                                                                                                                                - - Stated limit (from README): "Playwright MCP is not a security boundary." Persistent profile cannot be used by two browser instances at once. README also notes that "Modern coding agents increasingly favor CLI–based workflows exposed as SKILLs over MCP because CLI invocations are more token-efficient" — i.e., MCP itself has a context-cost downside that the project acknowledges.
                                                                                                                                 
                                                                                                                                  - ### 4.5 Skyvern
                                                                                                                                  - - Stated strength: vision-based, resistant to layout changes; AI-fallback selectors; first-class `validate`; password-manager and 2FA support; workflows builder; livestreaming; SOTA WebBench score (64.4%) claimed in README.
                                                                                                                                    - - Stated limit: anti-bot measures are AGPL-3.0-excluded and only available in managed cloud. Heavyweight stack (Postgres or SQLite, server + UI).
                                                                                                                                     
                                                                                                                                      - ### 4.6 Steel
                                                                                                                                      - - Stated strength: batteries-included infrastructure layer; multi-client compatibility (Puppeteer / Playwright / Selenium); quick-action REST endpoints; debug UI; session API; extension support; proxy chains.
                                                                                                                                        - - Stated limit: not an agent — does not itself provide AI verbs; "Selenium API does not support all the features of the CDP-based browser sessions API."
                                                                                                                                         
                                                                                                                                          - ### 4.7 cloak-browse + browser-harness + cloakbrowser
                                                                                                                                          - - Stated strength: stealth applied at the C++ binary level (not via JS injection); same stealth in headed and headless; tiny glue layer; runs fully local; works through CDP so other clients could also attach; persistent profile and proxy supported.
                                                                                                                                            - - Stated limit (observable from README / code): no accessibility-tree representation, no natural-language verbs, no caching, no MCP server, no live debug view, no quick-action endpoints, no password-manager integration, no opt-in capability system. Unix-socket IPC implies macOS/Linux only.
                                                                                                                                             
                                                                                                                                              - ---
                                                                                                                                              
                                                                                                                                              ## 5. Cross-cutting observations
                                                                                                                                              
                                                                                                                                              - **CDP is the lingua franca.** Every surveyed project either speaks CDP directly or sits on top of Playwright (which speaks CDP). Lightpanda, despite being a brand-new browser, exposes CDP so existing clients work unchanged. This means the *interface* is portable across engines; the engine choice is independent.
                                                                                                                                              - - **Accessibility tree vs vision is a real fork in the road.** Playwright MCP explicitly argues accessibility tree is better for LLMs; Skyvern explicitly argues vision is better against layout changes. Both ship working products. Stagehand and browser-use are closer to the accessibility-tree side. cloak-browse is currently on neither side — it exposes raw `visible_text()` and pixel coordinates, which is a third (and less common) position.
                                                                                                                                                - - **MCP adoption is broad but its trade-off is acknowledged.** Lightpanda, Playwright MCP, Skyvern, and browser-use either ship or support MCP. Microsoft's own README states the case against MCP for high-throughput coding agents (CLI + skills is more token-efficient) and the case for MCP (long-running autonomous workflows). The choice is not binary; some projects ship both.
                                                                                                                                                  - - **Auto-caching of AI actions is rare.** Only Stagehand documents it in the surveyed set. It is the main mechanism by which their stated "runs without LLM inference" claim is achieved.
                                                                                                                                                    - - **Stealth is overwhelmingly cloud-monetized.** Browser Use, Skyvern, and Browserbase all gate their stealth/anti-bot/captcha capabilities behind paid cloud offerings. Cloakbrowser is the outlier — binary-level stealth in an open-source local-only stack.
                                                                                                                                                      - - **Live debug view is present in production-oriented stacks.** Skyvern (livestreaming) and Steel (debug UI) both ship it. Agent-framework projects (Stagehand, browser-use) and protocol-only projects (Playwright MCP) generally do not.
                                                                                                                                                        - - **Persistent state is split into two flavors.** "Full user data dir" (cloak-browse `--profile`, Playwright MCP `--user-data-dir`) and "storage state file" (Playwright MCP `--storage-state`). Steel uses session objects that can be configured per-create. The two flavors solve overlapping but distinct problems: portability/shareability vs full fidelity including extensions and cache.
                                                                                                                                                          - - **Quick-action endpoints (`scrape`, `screenshot`, `pdf`) are present where the project is framed as infrastructure rather than as an agent.** Steel ships them; Lightpanda ships `fetch --dump`. Agent-framing projects do not.
                                                                                                                                                           
                                                                                                                                                            - ---
                                                                                                                                                            
                                                                                                                                                            ## 6. Open decisions for cloak-browse to make
                                                                                                                                                            
                                                                                                                                                            These are framed as questions, not recommendations.
                                                                                                                                                            
                                                                                                                                                            1. Should cloak-browse expose an accessibility-tree representation of the page with stable element references? (Currently it does not; Playwright MCP, browser-use, Stagehand all do in some form.)
                                                                                                                                                            2. 2. Should the helper surface add natural-language verbs (`act`, `extract`, `validate`) that internally call an LLM, or stay purely imperative?
                                                                                                                                                               3. 3. Should action results be cached and replayed (Stagehand-style) to reduce LLM cost on repeated runs?
                                                                                                                                                                  4. 4. Should cloak-browse ship a native MCP server in addition to (or instead of) the `run "<python>"` CLI? Both Lightpanda and Playwright MCP do; cloak-browse currently does not.
                                                                                                                                                                     5. 5. Should the tool surface be opt-in via capability flags (Playwright MCP `--caps=...`) to reduce schema size for LLM consumers?
                                                                                                                                                                        6. 6. Should `--init-script` / `--init-page` hooks be added for per-launch JS injection on top of the existing binary-level stealth?
                                                                                                                                                                           7. 7. Should cloak-browse add a `--storage-state PATH` mode in addition to the existing `--profile DIR` mode?
                                                                                                                                                                              8. 8. Should a live debug view be added (Skyvern-style livestream, or Steel-style web UI)?
                                                                                                                                                                                 9. 9. Should quick-action endpoints (`scrape`, `screenshot`, `pdf` over HTTP, or `fetch` over CLI) be added on top of the existing daemon?
                                                                                                                                                                                    10. 10. Should cloak-browse stay Unix-only (current implementation uses `/tmp/` Unix sockets and `os.kill`) or grow Windows support via TCP IPC?
                                                                                                                                                                                        11. 11. Is cloak-browse positioned as the *agent layer* (like Stagehand/Skyvern/browser-use), the *infrastructure layer* (like Steel), or the *engine + control* layer (current position, like cloakbrowser + browser-harness wired together)? The downstream feature set depends on this answer.
                                                                                                                                                                                           
                                                                                                                                                                                            12. ---
                                                                                                                                                                                           
                                                                                                                                                                                            13. ## 7. Sources
                                                                                                                                                                                           
                                                                                                                                                                                            14. All claims in this document are drawn from the public README of each project as of the survey date. Specific projects referenced:
                                                                                                                                                                                           
                                                                                                                                                                                            15. - github.com/lightpanda-io/browser
                                                                                                                                                                                                - - github.com/browserbase/stagehand
                                                                                                                                                                                                  - - github.com/browser-use/browser-use
                                                                                                                                                                                                    - - github.com/microsoft/playwright-mcp
                                                                                                                                                                                                      - - github.com/Skyvern-AI/skyvern
                                                                                                                                                                                                        - - github.com/steel-dev/steel-browser
                                                                                                                                                                                                          - - github.com/vincenthopf/cloak-browse (this repo)
                                                                                                                                                                                                            - 
