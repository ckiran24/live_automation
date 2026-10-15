from __future__ import annotations

import json
from pathlib import Path

from playwright.async_api import async_playwright

from .browser import launch_options
from .models import Target
from .resolver import Resolver


async def check_html(html_path: Path, targets_path: Path):
    """Use exactly the production resolver, with every network request blocked.

    Saved frames must be embedded as srcdoc (including nested srcdoc frames).
    Scripts are disabled: fixture HTML cannot fetch data or mutate under test.
    """
    attempts = []
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(**launch_options())
        try:
            context = await browser.new_context(java_script_enabled=False, service_workers="block")
            await context.route("**/*", lambda route: route.abort())
            page = await context.new_page()
            await page.set_content(html_path.read_text(), wait_until="load")
            resolver = Resolver(attempts, timeout_ms=1000)
            for raw in json.loads(targets_path.read_text()):
                await resolver.resolve(page, Target.model_validate(raw))
        finally:
            await browser.close()
    return attempts
