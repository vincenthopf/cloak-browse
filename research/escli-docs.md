# escli docs research

- escli: escli v0.21.1
endpoint  https://ai.eightstate.co/v1
- generated: 2026-09-01T10:44:21Z

## browser-harness search

```text

  Search results:

  /browser-use/browser-harness             Browser Harness
    state=finalized  stars=6395  Browser Harness is a self-healing LLM automation framework that provides direct 
  /deepseek-ai/deepseek-harness            DeepSeek Harness
    state=finalized  stars=49097  DeepSeek Harness is an open-source, plugin-based agent harness developed by Deep
  /koorchik/mui-harness                    MUI Harness
    state=finalized  stars=0  MUI Harness is a TypeScript library providing test harnesses for Material UI com
  /koorchik/dom-harness                    Dom Harness
    state=finalized  stars=0  Dom Harness is a lightweight DOM component test harness library that provides a 
  /pydantic/pydantic-ai-harness            Pydantic AI Harness
    state=finalized  stars=742  Pydantic AI Harness is the official capability library for Pydantic AI, providin


[exit 0]
```

## CloakBrowser search

```text

  Search results:

  /cloakhq/cloakbrowser                    CloakBrowser
    state=finalized  stars=68  CloakBrowser is a stealth Chromium browser with source-level fingerprint patches
  /swimmwatch/cloakbrowser-mcp             Cloakbrowser MCP
    state=finalized  stars=9  Cloakbrowser MCP is a Model Context Protocol browser automation server that runs
  /cloakhq/cloakbrowser-manager            CloakBrowser Manager
    state=finalized  stars=584  A browser profile manager for creating, managing, and launching isolated browser


[exit 0]
```

## Playwright process and launch guidance

```text
  → resolved: /microsoft/playwright-python
### Automate browsers with Playwright

Source: https://github.com/microsoft/playwright-python/blob/main/README.md

Demonstrates launching multiple browser types and taking screenshots using both synchronous and asynchronous APIs.

```python
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    for browser_type in [p.chromium, p.firefox, p.webkit]:
        browser = browser_type.launch()
        page = browser.new_page()
        page.goto('http://playwright.dev')
        page.screenshot(path=f'example-{browser_type.name}.png')
        browser.close()
```

```python
import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        for browser_type in [p.chromium, p.firefox, p.webkit]:
            browser = await browser_type.launch()
            page = await browser.new_page()
            await page.goto('http://playwright.dev')
            await page.screenshot(path=f'example-{browser_type.name}.png')
            await browser.close()

asyncio.run(main())
```

--------------------------------

### normalize_launch_params converts executablePath to string

Source: https://github.com/microsoft/playwright-python/blob/main/playwright/_impl/_browser_type.py

The only Python-side processing: executablePath is converted from Path to string. channel passes through untouched. All actual resolution happens in the Node.js driver.

```python
def normalize_launch_params(params: Dict) -> None:
    if "env" in params:
        params["env"] = [
            {"name": name, "value": str(value)}
            for [name, value] in params["env"].items()
        ]
    if "ignoreDefaultArgs" in params:
        if params["ignoreDefaultArgs"] is True:
            params["ignoreAllDefaultArgs"] = True
            del params["ignoreDefaultArgs"]
        elif params["ignoreDefaultArgs"] is False:
            del params["ignoreDefaultArgs"]
    if "executablePath" in params:
        params["executablePath"] = str(Path(params["executablePath"]))
```

--------------------------------

### Video.path() docs: guaranteed to be written upon closing browser context

Source: https://github.com/microsoft/playwright-python/blob/main/playwright/sync_api/_generated.py

The generated API docstring confirms the video is guaranteed to be written to the filesystem upon closing the browser context.

```python
def path(self) -> pathlib.Path:
    """Video.path

    Returns the file system path this video will be recorded to. The video is guaranteed to be written to the
    filesystem upon closing the browser context. This method throws when connected remotely.
    """
    return mapping.from_maybe_impl(self._sync(self._impl_obj.path()))
```

[exit 0]
```

## Patchright compatibility guidance

```text
  → resolved: /kaliiiiiiiiii-vinyzu/patchright-python
### Configure residential proxies

Source: https://github.com/kaliiiiiiiiii-vinyzu/patchright-python/blob/main/_autodocs/README.md

Pass proxy credentials to the new_context method to route traffic through residential proxies.

```python
context = await browser.new_context(
    proxy={
        "server": "http://proxy.provider.com:port",
        "username": "user",
        "password": "pass"
    }
)
```

--------------------------------

### Configure Browser Launch Options

Source: https://github.com/kaliiiiiiiiii-vinyzu/patchright-python/blob/main/_autodocs/configuration.md

Example demonstrating standard Playwright launch options supported by Patchright.

```python
browser = await playwright.chromium.launch(
    # Standard Playwright options
    executable_path="/path/to/chromium",
    headless=True,
    args=["--start-maximized"],
    ignore_default_args=False,
    handle_sigterm=True,
    handle_sigint=True,
    handle_sighup=True,
    timeout=30000,  # milliseconds
    env={"CUSTOM_VAR": "value"},
    proxy={
        "server": "http://proxy.example.com:3128",
        "bypass": "localhost,.example.com",
        "username": "user",
        "password": "pass"
    },
    downloads_path="/tmp/downloads",
    chromium_sandbox=True,
    slow_mo=100,  # milliseconds
    traces_dir="/tmp/traces",
    channel="chrome",  # "chrome", "chromium"
)
```

--------------------------------

### Configure Proxy with Patchright

Source: https://github.com/kaliiiiiiiiii-vinyzu/patchright-python/blob/main/_autodocs/stealth-features.md

Integrate residential proxies by providing server, username, and password details within the browser context.

```python
# Use proxy with Patchright
context = await browser.new_context(
    proxy={
        "server": "http://proxy.provider.com:port",
        "username": "user",
        "password": "pass"
    },
    # Don't override fingerprints
)
```

--------------------------------

### Replace Playwright with Patchright

Source: https://github.com/kaliiiiiiiiii-vinyzu/patchright-python/blob/main/_autodocs/cli-reference.md

Demonstrates the drop-in replacement syntax for existing Playwright workflows.

```bash
# Before
playwright install chromium && pytest tests/

# After
patchright install chromium && pytest tests/
```

--------------------------------

### Example generated Python code

Source: https://github.com/kaliiiiiiiiii-vinyzu/patchright-python/blob/main/_autodocs/cli-reference.md

The resulting Python code structure after running the codegen command.

```python
from patchright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    page.goto("https://example.com")
    # ... recorded actions ...
    browser.close()
```

[exit 0]
```

## websockets sync client guidance

```text
  → resolved: /python-websockets/websockets
### Connect a synchronous WebSocket client

Source: https://github.com/python-websockets/websockets/blob/main/docs/intro/examples.rst

Uses connect() as a context manager to ensure the WebSocket connection is closed after the block finishes.

```python
#!/usr/bin/env python

from websockets.sync.client import connect

def hello():
    uri = "ws://localhost:8765"
    with connect(uri) as websocket:
        name = input("What's your name? ")

        websocket.send(name)
        print(f">>> {name}")

        greeting = websocket.recv()
        print(f"<<< {greeting}")

if __name__ == "__main__":
    hello()
```

--------------------------------

### websockets.sync.client.connect

Source: https://github.com/python-websockets/websockets/blob/main/docs/reference/sync/client.rst

Establishes a connection to a WebSocket server at the specified URI.

```APIDOC
## websockets.sync.client.connect(uri, ...)

### Description
Connect to the WebSocket server at `uri`. This function acts as a context manager yielding a `ClientConnection` object.

### Parameters
- **uri** (str) - The WebSocket URI to connect to.
- **sock** (socket) - Optional socket object.
- **ssl** (SSLContext) - Optional SSL context.
- **server_hostname** (str) - Optional server hostname for SNI.
- **origin** (str) - Optional origin header.
- **extensions** (list) - Optional list of extensions.
- **subprotocols** (list) - Optional list of subprotocols.
- **compression** (str) - Compression method, defaults to 'deflate'.
- **additional_headers** (dict) - Optional additional HTTP headers.
- **user_agent_header** (str) - User agent header string.
- **proxy** (bool) - Whether to use a proxy.
- **open_timeout** (float) - Timeout for opening the connection.
- **ping_interval** (float) - Interval for sending pings.
- **ping_timeout** (float) - Timeout for waiting for pongs.
- **close_timeout** (float) - Timeout for closing the connection.
- **max_size** (int) - Maximum message size.
- **max_queue** (int) - Maximum queue size.
- **legacy** (bool) - Flag for backwards compatibility behavior.
```

--------------------------------

### websockets.asyncio.client.connect

Source: https://github.com/python-websockets/websockets/blob/main/docs/reference/asyncio/client.rst

Establishes a connection to a WebSocket server at the specified URI. It can be used as an asynchronous context manager, an infinite iterator for automatic reconnection, or awaited directly.

```APIDOC
## websockets.asyncio.client.connect(uri, *, ...)

### Description
Connects to the WebSocket server at the provided URI. This function returns a ClientConnection object and supports multiple usage patterns including context managers, reconnection loops, and direct awaiting.

### Parameters
- **uri** (str) - Required - The WebSocket server URI.
- **origin** (str) - Optional - The origin header.
- **extensions** (list) - Optional - List of extensions.
- **subprotocols** (list) - Optional - List of subprotocols.
- **compression** (str) - Optional - Compression method, defaults to 'deflate'.
- **additional_headers** (dict) - Optional - Extra headers to send.
- **user_agent_header** (str) - Optional - User-Agent header value.
- **proxy** (bool) - Optional - Whether to use a proxy.
- **open_timeout** (int) - Optional - Timeout for opening the connection.
- **ping_interval** (int) - Optional - Interval for sending pings.
- **ping_timeout** (int) - Optional - Timeout for ping responses.
- **close_timeout** (int) - Optional - Timeout for closing the connection.
- **max_size** (int) - Optional - Maximum message size.
- **max_queue** (int) - Optional - Maximum queue size.
- **write_limit** (int) - Optional - Write buffer limit.
```

--------------------------------

### Default timeout and max_size values in asyncio connect()

Source: https://github.com/python-websockets/websockets/blob/main/src/websockets/asyncio/client.py

Default values for connect() in websockets.asyncio.client

```python
        # Timeouts
        open_timeout: float | None = 10,
        ping_interval: float | None = 20,
        ping_timeout: float | None = 20,
        close_timeout: float | None = 10,
        # Limits
        max_size: int | None | tuple[int | None, int | None] = 2**20,
```

--------------------------------

### Handle ConnectionClosedError for lost connections

Source: https://github.com/python-websockets/websockets/blob/main/docs/faq/connection.rst

Traceback examples for server and client connection loss.

```pytb
connection handler failed
Traceback (most recent call last):
  ...
websockets.exceptions.ConnectionClosedError: no close frame received or sent
```

```pytb
Traceback (most recent call last):
  ...
websockets.exceptions.ConnectionClosedError: no close frame received or sent
```

[exit 0]
```

## Hatch dynamic version and distributions

```text
  → resolved: /pypa/hatch
### Configure Build Targets in TOML

Source: https://github.com/pypa/hatch/blob/master/docs/build.md

Define build targets like sdist and wheel in your `pyproject.toml` file. Specify packages to include and files/directories to exclude from the build.

```toml
[tool.hatch.build.targets.sdist]
exclude = [
  "/.github",
  "/docs",
]

[tool.hatch.build.targets.wheel]
packages = ["src/foo"]
```

--------------------------------

### Define project version

Source: https://github.com/pypa/hatch/blob/master/docs/config/metadata.md

Configures the project version using either dynamic path resolution or a static value.

```toml
[project]
...
dynamic = ["version"]

[tool.hatch.version]
path = "..."
```

```toml
[project]
...
version = "0.0.1"
```

--------------------------------

### Configure Versioning with Regex Source

Source: https://github.com/pypa/hatch/blob/master/docs/version.md

Defines the file path and optional custom regex pattern for version tracking in pyproject.toml.

```toml
[tool.hatch.version]
path = "src/hatch_demo/__about__.py"
```

```toml
[tool.hatch.version]
path = "pkg/__init__.py"
pattern = "BUILD = 'b(?P<version>[^']+)'"
```

--------------------------------

### Wheel Builder Configuration

Source: https://github.com/pypa/hatch/blob/master/docs/plugins/builder/wheel.md

Configuration schema for the wheel build target in pyproject.toml.

```APIDOC
## Wheel Builder Configuration

### Description
Configures the wheel build target for Hatch projects.

### Request Body
- **core-metadata-version** (string) - Optional - The version of core metadata to use (default: "2.4").
- **shared-data** (mapping) - Optional - Mapping for data subdirectory installation.
- **shared-scripts** (mapping) - Optional - Mapping for scripts subdirectory installation.
- **extra-metadata** (mapping) - Optional - Mapping for extra metadata in .dist-info.
- **strict-naming** (boolean) - Optional - Whether file names contain the normalized project name (default: true).
- **macos-max-compat** (boolean) - Optional - Whether to signal broad support on macOS (default: false).
- **bypass-selection** (boolean) - Optional - Whether to suppress errors when file selection heuristics fail (default: false).
- **sbom-files** (list) - Optional - List of paths to Software Bill of Materials files.

### Request Example
[tool.hatch.build.targets.wheel]
core-metadata-version = "2.4"
strict-naming = true
```

--------------------------------

### Configure sdist target

Source: https://github.com/pypa/hatch/blob/master/docs/plugins/builder/sdist.md

Define the sdist build target within the project configuration file.

```toml
[tool.hatch.build.targets.sdist]
```

[exit 0]
```

## GitHub Actions release validation

```text
  → resolved: /websites/github_en_actions
### Commit, Tag, and Push Action Release

Source: https://docs.github.com/en/actions/tutorials/create-actions/create-a-javascript-action

Stage bundled files, create an initial commit, and publish an annotated version tag.

```shell
git add src/index.js dist/index.js rollup.config.js package.json package-lock.json README.md action.yml
git commit -m "Initial commit of my first action"
git tag -a -m "My first action release" v1.1
git push --follow-tags
```

--------------------------------

### Specify action versions in workflow steps

Source: https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax

Reference an action using a commit SHA, major release tag, specific release version, or branch ref. Using a full commit SHA provides the highest level of stability and security.

```yaml
steps:
  # Reference a specific commit
  - uses: actions/checkout@8f4b7f84864484a7bf31766abe9204da3cbe65b3
  # Reference the major version of a release
  - uses: actions/checkout@v6
  # Reference a specific version
  - uses: actions/checkout@v6.2.0
  # Reference a branch
  - uses: actions/checkout@main
```

--------------------------------

### Reference an action by commit SHA in YAML

Source: https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/find-and-customize-actions

Pin an action using an immutable full commit SHA from the action's repository for maximum reliability. Action updates and bug fixes will not be automatically pulled.

```yaml
steps:
  - uses: actions/javascript-action@a824008085750b8e136effc585c3cd6082bd575f
```

### Using immutable releases and tags to manage your action's releases

Source: https://docs.github.com/en/actions/how-tos/create-and-publish-actions/using-immutable-releases-and-tags-to-manage-your-actions-releases

If you enable immutable releases on your action's repository, you can manage your action's releases as follows: 1. To start the release cycle, develop and validate a potential release for your action on a release branch. 2. Determine how you want to share your changes: * If you are ready to share an unchangeable version of your action, create a release on GitHub with a release-specific tag (for example, `v1.0.0`). See [Managing releases in a repository](/en/repositories/releasing-projects-on-github/managing-releases-in-a-repository#creating-a-release). * If you want to be able to update the Git tag of a release later, do not create a release on GitHub. Instead, create a tag as follows: * If your release contains breaking changes for existing workflows, create a major version tag (for example, `v1`). * If your release contains new backwards-compatible functionality, create a minor version tag (for example, `v1.1`). * If your release contains backwards-compatible bug fixes, create a patch version tag (for example, `v1.1.1`). 3. For Git tags that are not tied to a release on GitHub, ensure users have access to the latest compatible version of your action by updating them as follows: * For a major version, update the tag to point to the Git ref of the latest related minor version or patch version. * For a minor version, update the tag to point to the Git ref of the latest related patch version.

--------------------------------

### Using release management for your custom actions

Source: https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/find-and-customize-actions

Tags allow you to decide when to switch between versions, but they can be moved or deleted by maintainers. Using a full, unabbreviated SHA value is immutable and more reliable, though it prevents automatic bug fixes and security updates. Pinning to a branch ensures the workflow always runs the latest commit on that branch, which can introduce breaking changes unexpectedly.

[exit 0]
```

