from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class BrowserOptions:
    cdp_port: int
    proxy: str | None
    profile: str | None
    headless: bool
    humanize: bool


@dataclass
class BrowserHandle:
    resource: Any

    def close(self) -> None:
        self.resource.close()


class BrowserLauncher:
    def ensure_binary(self) -> Path:
        from cloakbrowser import ensure_binary

        return Path(ensure_binary())

    def launch(self, options: BrowserOptions) -> BrowserHandle:
        from cloakbrowser import launch, launch_persistent_context

        launch_options = {
            "headless": options.headless,
            "proxy": options.proxy,
            "args": [
                "--remote-debugging-address=127.0.0.1",
                f"--remote-debugging-port={options.cdp_port}",
            ],
            "humanize": options.humanize,
        }
        if options.profile:
            resource = launch_persistent_context(
                user_data_dir=os.path.expanduser(options.profile),
                **launch_options,
            )
        else:
            resource = launch(**launch_options)
        return BrowserHandle(resource)
