from __future__ import annotations

import asyncio
import time

from playwright.async_api import Error as PlaywrightError

from .errors import FinalFailure, LocatorUnavailable
from .models import Target


class Resolver:
    def __init__(self, attempts: list[dict], timeout_ms=8000):
        self.attempts = attempts
        self.timeout_ms = timeout_ms

    def strategies(self, root, target):
        if target.role and target.name:
            yield "role_name", lambda: root.get_by_role(target.role, name=target.name, exact=True)
        if target.label:
            yield "label", lambda: root.get_by_label(target.label, exact=True)
        if target.text:
            yield "text", lambda: root.get_by_text(target.text, exact=True)
        if target.nearby:
            # Locate a field's enclosing block without depending on sibling order.
            yield "nearby_text", lambda: root.locator("label, fieldset, [data-field]").filter(
                has=root.get_by_text(target.nearby, exact=True)
            ).locator(target.control)
        if target.structure:
            yield "structure", lambda: root.locator(target.structure)
        for index, css in enumerate(target.css):
            yield f"css_{index + 1}", lambda css=css: root.locator(css)

    async def resolve(self, page, target: Target, timeout_ms=None):
        deadline = time.monotonic() + (timeout_ms if timeout_ms is not None else self.timeout_ms) / 1000
        # Re-scan while the DOM and frame list settle. Prefer a semantic strategy
        # globally across frames before considering a weaker strategy anywhere.
        while True:
            frames = page.frames
            names = [name for name, _ in self.strategies(page.main_frame, target)]
            for strategy in names:
                matches = []
                for frame_index, frame in enumerate(frames):
                    try:
                        factory = dict(self.strategies(frame, target))[strategy]
                        locator = factory()
                        visible = []
                        for i in range(await locator.count()):
                            item = locator.nth(i)
                            if await item.is_visible():
                                visible.append(item)
                        if visible:
                            matches.extend(visible)
                        self.record(target.key, strategy, frame_index, "match" if visible else "miss")
                    except PlaywrightError as exc:
                        if frame.is_detached() or "Execution context was destroyed" in str(exc):
                            self.record(target.key, strategy, frame_index, "frame_changed")
                        else:
                            self.record(target.key, strategy, frame_index, "invalid_locator")
                            raise FinalFailure(f"Invalid locator definition: {target.key}") from exc
                if len(matches) > 1:
                    self.record(target.key, strategy, None, "ambiguous")
                    raise FinalFailure(f"Ambiguous target: {target.key}")
                if matches:
                    self.record(target.key, strategy, None, "selected")
                    return matches[0]
            if time.monotonic() >= deadline:
                raise LocatorUnavailable(f"Target unavailable: {target.key}")
            await asyncio.sleep(0.1)

    def record(self, target, strategy, frame, outcome):
        entry = {"target": target, "strategy": strategy, "frame": frame, "outcome": outcome}
        # Keep the complete strategy history without flooding logs each poll.
        if not self.attempts or self.attempts[-1] != entry:
            self.attempts.append(entry)

    async def present(self, page, target, timeout_ms=250):
        try:
            await self.resolve(page, target, timeout_ms)
            return True
        except LocatorUnavailable:
            return False
