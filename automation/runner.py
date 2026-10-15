from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from playwright.async_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeout, async_playwright, expect

from .browser import launch_options
from .errors import AuthenticationFailure, FinalFailure, RetryableFailure
from .models import Action, Portal
from .otp import Challenge, CodeProvider, IMAPProvider, TOTPProvider
from .resolver import Resolver
from .security import EvidenceHTML, Redactor, private_json


class Runner:
    def __init__(self, portal: Portal, inputs: dict, redactor: Redactor, output: Path,
                 state: Path, *, provider: CodeProvider | None = None, headed=False):
        self.portal, self.inputs, self.redactor = portal, inputs, redactor
        self.output, self.state, self.headed = output, state, headed
        self.provider = provider
        self.stage = "startup"
        self.console = []
        self.page = self.context = self.browser = None
        self.started = time.perf_counter()
        self.manifest = {
            "schema_version": 1, "run_id": uuid.uuid4().hex,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "portal": portal.name, "inputs": redactor.clean(inputs),
            "status": "running", "session": {}, "pages_visited": [],
            "stages": [], "resolver_attempts": [], "captured_files": [],
        }
        self.resolver = Resolver(self.manifest["resolver_attempts"], portal.timeout_ms)

    def url(self, path):
        return urljoin(self.portal.base_url + "/", path)

    def observe_page(self, page):
        def visited(frame):
            if frame != page.main_frame or not frame.url.startswith(("https://", "http://")):
                return
            self.manifest["pages_visited"].append({
                "url": self.redactor.url(frame.url), "stage": self.stage,
                "elapsed_ms": round((time.perf_counter() - self.started) * 1000, 2),
            })

        page.on("framenavigated", visited)
        # Browser output can contain unknown personal data. Keep event type but
        # never persist raw browser-controlled messages, arguments, or stack traces.
        page.on("console", lambda msg: self.console.append({"type": msg.type, "message": "[REDACTED_BROWSER_MESSAGE]"}))
        page.on("pageerror", lambda _: self.console.append({"type": "pageerror", "message": "[REDACTED_BROWSER_ERROR]"}))
        page.set_default_timeout(self.portal.timeout_ms)

    async def stage_run(self, key, operation, *, retry_safe=True):
        self.stage = key
        maximum = self.portal.attempts if retry_safe else 1
        for attempt in range(1, maximum + 1):
            started = time.perf_counter()
            record = {"key": key, "attempt": attempt}
            try:
                result = await operation()
                record["status"] = "passed"
                return result
            except Exception as exc:
                transient = isinstance(exc, (RetryableFailure, PlaywrightTimeout))
                if isinstance(exc, PlaywrightError) and not isinstance(exc, PlaywrightTimeout):
                    transient = any(code in str(exc) for code in (
                        "net::ERR_CONNECTION_RESET", "net::ERR_TIMED_OUT", "net::ERR_CONNECTION_CLOSED",
                        "net::ERR_NETWORK_CHANGED", "net::ERR_CONNECTION_REFUSED"))
                record.update(status="retry" if transient and attempt < maximum else "failed",
                              error_type=type(exc).__name__, retryable=transient)
                if not transient or attempt == maximum:
                    raise
                delay = self.portal.backoff_seconds * 2 ** (attempt - 1)
                record["backoff_ms"] = round(delay * 1000, 2)
                await asyncio.sleep(delay)
            finally:
                record["duration_ms"] = round((time.perf_counter() - started) * 1000, 2)
                self.manifest["stages"].append(record)

    async def goto(self, page, path):
        response = await page.goto(self.url(path), wait_until="domcontentloaded")
        if response:
            if response.status == 429 or response.status >= 500:
                raise RetryableFailure("Portal temporarily unavailable")
            if response.status >= 400:
                raise FinalFailure("Portal rejected navigation")

    async def authenticated(self):
        """Check positive private-page content, plus an optional authenticated API.

        A separate tab preserves the current OTP challenge if authentication fails.
        A login redirect alone is never treated as proof either way.
        """
        check = await self.context.new_page()
        try:
            await self.goto(check, self.portal.session.path)
            for marker in self.portal.session.markers:
                if not await self.resolver.present(check, marker, 500):
                    return False
            if self.portal.session.identity:
                identity = self.portal.session.identity
                control = await self.resolver.resolve(check, identity.target, timeout_ms=1000)
                if await control.get_attribute(identity.attribute) != identity.equals:
                    return False
            if self.portal.session.probe_path:
                response = await self.context.request.get(self.url(self.portal.session.probe_path))
                if response.status == 429 or response.status >= 500:
                    raise RetryableFailure("Session probe temporarily unavailable")
                if response.status in (401, 403):
                    return False
                if response.status != 200:
                    raise FinalFailure("Unexpected session probe response")
                if self.portal.session.probe_json:
                    try:
                        body = await response.json()
                    except (ValueError, PlaywrightError) as exc:
                        raise FinalFailure("Session probe did not return JSON") from exc
                    if not isinstance(body, dict) or any(
                        body.get(k) != v for k, v in self.portal.session.probe_json.items()
                    ):
                        return False
            return True
        finally:
            await check.close()

    async def login(self):
        self.manifest["session"]["full_login"] = True
        requested_after = time.time()
        await self.stage_run("login.open", lambda: self.goto(self.page, self.portal.login.path))
        for action in self.portal.login.steps:
            if urlsplit(self.page.url).netloc != urlsplit(self.portal.base_url).netloc:
                raise AuthenticationFailure("Unexpected login origin; a separate SSO adapter is required")
            await self.stage_run("login." + action.key, lambda action=action: self.action(action),
                                 retry_safe=action.retry_safe or action.kind in ("fill", "select", "wait"))
        await self.resolver.resolve(self.page, self.portal.login.challenge)
        provider = self.provider or (IMAPProvider(self.redactor) if self.portal.login.provider == "imap"
                                     else TOTPProvider(self.portal.login.totp_env, self.redactor))
        previous = None
        for attempt in (1, 2):
            self.stage = "login.second_factor"
            async def submit_code():
                if urlsplit(self.page.url).netloc != urlsplit(self.portal.base_url).netloc:
                    raise AuthenticationFailure("Unexpected code-challenge origin")
                code = await provider.get_code(Challenge(self.stage, attempt, previous, requested_after))
                self.redactor.add(code)
                challenge = await self.resolver.resolve(self.page, self.portal.login.challenge)
                await challenge.fill(code)
                # Some portals submit a one-time code as soon as it is entered.
                # Give that flow a brief chance to establish the session before
                # requiring a submit control that may no longer exist.
                challenge_deadline = time.monotonic() + 0.5
                challenge_still_visible = True
                while time.monotonic() < challenge_deadline:
                    challenge_still_visible = await self.resolver.present(self.page, self.portal.login.challenge, 100)
                    if not challenge_still_visible:
                        break
                    await asyncio.sleep(0.05)
                if not challenge_still_visible and await self.wait_authenticated(timeout_seconds=2):
                    return code, True
                submit = await self.resolver.resolve(self.page, self.portal.login.submit)
                await submit.click()
                await self.page.wait_for_load_state("domcontentloaded")
                return code, False

            code, authenticated_after_fill = await self.stage_run(
                "login.second_factor", submit_code, retry_safe=False
            )
            # GitHub may navigate directly to an authenticated page after accepting
            # the code. Confirm that outcome before inspecting challenge-page text:
            # stale/hidden login markup must not override a successful login.
            if authenticated_after_fill or await self.authenticated():
                await self.save_authenticated_state()
                return
            # Never retry an ambiguous network failure here: only a clearly rejected
            # code receives the one permitted second attempt.
            if await self.resolver.present(self.page, self.portal.login.rejected, 1000):
                if attempt == 2:
                    raise AuthenticationFailure("Second factor rejected twice")
                previous = code
                if self.portal.login.resend:
                    requested_after = time.time()
                    resend = await self.resolver.resolve(self.page, self.portal.login.resend)
                    await resend.click()
                continue
            raise AuthenticationFailure("Authentication not confirmed; check account challenges")
        raise AuthenticationFailure("Authentication failed")

    async def wait_authenticated(self, timeout_seconds=2):
        deadline = time.monotonic() + timeout_seconds
        while True:
            if await self.authenticated():
                return True
            if time.monotonic() >= deadline:
                return False
            await asyncio.sleep(0.2)

    async def save_authenticated_state(self):
        private_json(self.state, {"version": 1, "origin": self.portal.base_url,
                                  "storage_state": await self.context.storage_state()})

    def capture_path(self, filename):
        if not filename or Path(filename).name != filename or filename in (".", ".."):
            raise FinalFailure("Capture filename must be a basename")
        path = self.output / "documents" / filename
        path.parent.mkdir(exist_ok=True, mode=0o700)
        if path.exists():
            raise FinalFailure("Capture would overwrite an existing file")
        return path

    def register_file(self, path, method):
        content = path.read_bytes()
        if not content or (path.suffix.lower() == ".pdf" and not content.startswith(b"%PDF-")):
            path.unlink(missing_ok=True)
            raise FinalFailure("Capture was empty or not a valid PDF")
        os.chmod(path, 0o600)
        self.manifest["captured_files"].append({
            "path": str(path.relative_to(self.output)), "method": method,
            "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest(),
        })

    async def action(self, action: Action):
        target = await self.resolver.resolve(self.page, action.target) if action.target else None
        if action.kind == "goto":
            await self.goto(self.page, action.value)
        elif action.kind == "fill":
            await target.fill(action.value)
        elif action.kind == "select":
            await target.select_option(label=action.value)
        elif action.kind == "click":
            await target.click()
            await self.page.wait_for_load_state("domcontentloaded")
        elif action.kind == "wait":
            await target.wait_for(state="visible")
            try:
                await expect(target).to_be_enabled(timeout=self.portal.timeout_ms)
            except AssertionError as exc:
                raise RetryableFailure("Dependent field not enabled before timeout") from exc
        elif action.kind == "download":
            path = self.capture_path(action.filename)
            async with self.page.expect_download() as event:
                await target.click()
            download = await event.value
            if await download.failure():
                raise RetryableFailure("Download failed")
            await download.save_as(path)
            self.register_file(path, "native_download")
        elif action.kind == "popup_pdf":
            path = self.capture_path(action.filename)
            async with self.page.expect_popup() as event:
                await target.click()
            popup = await event.value
            try:
                await popup.wait_for_load_state("domcontentloaded")
                # Render HTML popups using Chromium's native print engine.
                await popup.pdf(path=str(path), print_background=True)
                self.register_file(path, "popup_print_pdf")
            finally:
                await popup.close()
        elif action.kind == "print_pdf":
            path = self.capture_path(action.filename)
            await self.page.pdf(path=str(path), print_background=True)
            self.register_file(path, "print_pdf")

    async def evidence(self, exc):
        directory = self.output / "failure"
        directory.mkdir(mode=0o700)
        metadata = {
            "stage": self.stage, "error_type": type(exc).__name__,
            "message": "Automation failed; inspect the stage and resolver attempts.",
            # URL origin is useful; all path segments are masked because unknown
            # account IDs can occur anywhere in a portal URL.
            "url": None,
            "console": self.console,
            "resolver_attempts": self.manifest["resolver_attempts"],
        }
        if self.page and not self.page.is_closed():
            parts = urlsplit(self.page.url)
            metadata["url"] = self.redactor.text(f"{parts.scheme}://{parts.netloc}/[REDACTED_PATH]")
            try:
                html = EvidenceHTML.sanitize(await self.page.content())
                (directory / "page.html").write_text(html)
                # Screenshot an inert sanitized copy, so unknown text, QR codes,
                # images, scripts, canvas pixels and nested frames cannot leak.
                context = await self.browser.new_context(java_script_enabled=False, service_workers="block")
                try:
                    await context.route("**/*", lambda route: route.abort())
                    page = await context.new_page()
                    await page.set_content(html, wait_until="domcontentloaded")
                    await page.screenshot(path=str(directory / "screenshot.png"), full_page=True)
                finally:
                    await context.close()
            except Exception as evidence_error:
                metadata["capture_error_type"] = type(evidence_error).__name__
        private_json(directory / "evidence.json", self.redactor.clean(metadata))
        self.manifest["failure"] = {"stage": self.stage, "error_type": type(exc).__name__,
                                    "bundle": "failure/evidence.json"}

    async def run(self):
        # Exclusive directory creation protects previous run outputs.
        self.output.mkdir(parents=True, mode=0o700, exist_ok=False)
        try:
            async with async_playwright() as playwright:
                try:
                    self.browser = await playwright.chromium.launch(**launch_options(self.headed))
                    storage = None
                    if self.state.exists():
                        try:
                            saved = json.loads(self.state.read_text())
                            if saved["version"] != 1 or saved["origin"] != self.portal.base_url:
                                raise ValueError("Wrong session scope")
                            storage = saved["storage_state"]
                            if not isinstance(storage, dict) or not isinstance(storage.get("cookies"), list) or not isinstance(storage.get("origins"), list):
                                raise ValueError("Invalid storage state")
                            self.manifest["session"]["state"] = "loaded"
                        except (ValueError, KeyError, TypeError, OSError):
                            self.manifest["session"]["state"] = "corrupt"
                    else:
                        self.manifest["session"]["state"] = "missing"
                    try:
                        self.context = await self.browser.new_context(storage_state=storage, accept_downloads=True)
                    except PlaywrightError:
                        if storage is None:
                            raise
                        self.manifest["session"]["state"] = "corrupt"
                        self.context = await self.browser.new_context(accept_downloads=True)
                        storage = None
                    self.context.on("page", self.observe_page)
                    self.page = await self.context.new_page()
                    valid = await self.stage_run("session.validate", self.authenticated) if storage else False
                    self.manifest["session"]["reused"] = valid
                    if not valid:
                        # Reset localStorage as well as cookies after a dead session.
                        if storage:
                            await self.context.close()
                            self.context = await self.browser.new_context(accept_downloads=True)
                            self.context.on("page", self.observe_page)
                            self.page = await self.context.new_page()
                            self.manifest["session"]["state"] = "stale"
                        await self.stage_run("login", self.login, retry_safe=False)
                    else:
                        self.manifest["session"]["full_login"] = False
                    await self.stage_run("navigate.start", lambda: self.goto(self.page, self.portal.session.path))
                    for action in self.portal.steps:
                        await self.stage_run(action.key, lambda action=action: self.action(action),
                                             retry_safe=action.retry_safe or action.kind in ("fill", "select", "wait"))
                    if not self.manifest["captured_files"]:
                        raise FinalFailure("Workflow produced no document")
                    # Refresh cookies that the portal may rotate during normal use.
                    private_json(self.state, {"version": 1, "origin": self.portal.base_url,
                                              "storage_state": await self.context.storage_state()})
                    self.manifest["status"] = "success"
                except Exception as exc:
                    self.manifest["status"] = "failed"
                    await self.evidence(exc)
                finally:
                    if self.browser:
                        await self.browser.close()
        except Exception as exc:
            self.manifest["status"] = "failed"
            if "failure" not in self.manifest:
                await self.evidence(exc)
        finally:
            self.manifest["duration_ms"] = round((time.perf_counter() - self.started) * 1000, 2)
            private_json(self.output / "manifest.json", self.redactor.clean(self.manifest))
        return self.manifest["status"] == "success"
