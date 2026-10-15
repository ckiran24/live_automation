from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time
import unittest
from email.message import EmailMessage
from email.utils import formatdate
from pathlib import Path
from unittest.mock import patch

import pyotp

from automation.config import load_config
from automation.demo import FORM, FixturePortal, target
from automation.errors import FinalFailure
from automation.models import Identity, Target
from automation.offline import check_html
from automation.otp import Challenge, IMAPProvider, TOTPProvider
from automation.resolver import Resolver
from automation.runner import Runner
from automation.security import EvidenceHTML, Redactor


class BrowserAcceptance(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.fixture = FixturePortal().__enter__()
        self.credentials = self.fixture.credentials()
        self.credentials.__enter__()

    async def asyncTearDown(self):
        self.credentials.__exit__(None, None, None)
        await asyncio.to_thread(self.fixture.__exit__, None, None, None)
        self.temp.cleanup()

    async def run_portal(self, name, config=None, provider=None):
        runner = Runner(config or self.fixture.config(), {"category": "Books", "order": "Book A", "date": "2026-10-15"},
                        self.fixture.redactor(), self.root / name, self.root / "state.json", provider=provider)
        success = await runner.run()
        return success, runner

    async def test_login_reuse_corruption_and_revoked_http_200_session(self):
        success, first = await self.run_portal("first")
        self.assertTrue(success, first.manifest.get("failure"))
        self.assertEqual(self.fixture.login_count, 1)
        success, reused = await self.run_portal("second")
        self.assertTrue(success)
        self.assertTrue(reused.manifest["session"]["reused"])
        self.assertEqual(self.fixture.login_count, 1)
        self.assertFalse(any("/login" in p["url"] for p in reused.manifest["pages_visited"]))
        (self.root / "state.json").write_text("broken JSON")
        success, corrupt = await self.run_portal("corrupt")
        self.assertTrue(success)
        self.assertEqual(corrupt.manifest["session"]["state"], "corrupt")
        self.fixture.sessions.clear()
        success, stale = await self.run_portal("stale")
        self.assertTrue(success)
        self.assertFalse(stale.manifest["session"]["reused"])
        self.assertEqual(stale.manifest["session"]["state"], "stale")
        self.assertEqual(self.fixture.login_count, 3)
        self.assertEqual(stale.manifest["inputs"]["date"], "2026-10-15")

    async def test_wrong_code_retried_once_and_second_rejection_is_final(self):
        fixture = self.fixture

        class Codes:
            def __init__(self, always_wrong=False):
                self.calls = []
                self.always_wrong = always_wrong

            async def get_code(self, challenge):
                self.calls.append(challenge)
                correct = pyotp.TOTP(fixture.secret).now()
                if self.always_wrong or challenge.attempt == 1:
                    return f"{(int(correct) + 1) % 1000000:06d}"
                return correct

        codes = Codes()
        success, runner = await self.run_portal("wrong-once", provider=codes)
        self.assertTrue(success)
        self.assertEqual(len(codes.calls), 2)
        self.assertIsNotNone(codes.calls[1].previous_code)
        (self.root / "state.json").unlink()
        codes = Codes(always_wrong=True)
        before = fixture.code_count
        success, runner = await self.run_portal("wrong-twice", provider=codes)
        self.assertFalse(success)
        self.assertEqual(fixture.code_count - before, 2)
        self.assertEqual(runner.manifest["failure"]["error_type"], "AuthenticationFailure")

    async def test_second_factor_auto_submit_does_not_require_verify_button(self):
        self.fixture.auto_submit_code = True
        success, runner = await self.run_portal("auto-submit")
        self.assertTrue(success, runner.manifest.get("failure"))
        attempts = runner.manifest["resolver_attempts"]
        self.assertFalse(any(item["target"] == "verify" for item in attempts))
        self.assertTrue((self.root / "auto-submit/documents/report.pdf").is_file())

    async def test_iframe_dependent_fields_changed_inputs_and_all_capture_methods(self):
        success, first = await self.run_portal("download")
        self.assertTrue(success)
        self.assertIn(b"Books | Book A | 2026-10-15", (self.root / "download/documents/report.pdf").read_bytes())
        self.assertTrue(any(a["frame"] == 1 and a["outcome"] == "match" for a in first.manifest["resolver_attempts"]))
        success, changed = await self.run_portal("changed", self.fixture.config(category="Devices", order="Device B", date="2026-10-16"))
        self.assertTrue(success)
        self.assertIn(b"Devices | Device B | 2026-10-16", (self.root / "changed/documents/report.pdf").read_bytes())
        self.assertNotEqual(first.manifest["captured_files"][0]["sha256"], changed.manifest["captured_files"][0]["sha256"])
        for kind in ("popup_pdf", "print_pdf"):
            success, runner = await self.run_portal(kind, self.fixture.config(capture=kind))
            self.assertTrue(success)
            self.assertTrue((self.root / kind / "documents/report.pdf").read_bytes().startswith(b"%PDF-"))

    async def test_transient_backoff_and_final_redacted_evidence(self):
        self.fixture.transient_documents = 1
        success, runner = await self.run_portal("retry")
        self.assertTrue(success)
        retries = [r for r in runner.manifest["stages"] if r["status"] == "retry"]
        self.assertEqual(len(retries), 1)
        self.assertEqual(retries[0]["key"], "documents")
        self.assertGreater(retries[0]["backoff_ms"], 0)
        broken = self.fixture.config()
        broken.steps[-1].target = Target(key="broken", role="link", name="Absent", css=["#missing"])
        success, runner = await self.run_portal("failure", broken)
        self.assertFalse(success)
        directory = self.root / "failure/failure"
        for name in ("evidence.json", "page.html", "screenshot.png"):
            self.assertTrue((directory / name).is_file())
        metadata = json.loads((directory / "evidence.json").read_text())
        self.assertEqual(metadata["stage"], "capture")
        self.assertTrue(metadata["resolver_attempts"])
        for name in ("evidence.json", "page.html"):
            content = (directory / name).read_text()
            for secret in (self.fixture.username, self.fixture.password, self.fixture.secret, "Book A", "2026-10-15"):
                self.assertNotIn(secret, content)
        self.assertEqual(len([x for x in runner.manifest["stages"] if x["key"] == "capture"]), 1)

    async def test_wrong_account_identity_never_reuses_state_and_bad_cookie_schema_recovers(self):
        success, _ = await self.run_portal("identity-first")
        self.assertTrue(success)
        config = self.fixture.config()
        # The synthetic private page's workspace link stands in for a profile link.
        config.session.identity = Identity(target=Target.model_validate(target("identity", "Workspace", "link")),
                                           attribute="href", equals="/another-account")
        success, runner = await self.run_portal("wrong-account", config)
        self.assertFalse(success)
        self.assertFalse(runner.manifest["session"]["reused"])
        self.assertEqual(runner.manifest["failure"]["error_type"], "AuthenticationFailure")
        state = {"version": 1, "origin": self.fixture.base_url, "storage_state": {"cookies": [{"bad": "schema"}], "origins": []}}
        (self.root / "state.json").write_text(json.dumps(state))
        success, runner = await self.run_portal("bad-cookie-schema")
        self.assertTrue(success)
        self.assertEqual(runner.manifest["session"]["state"], "corrupt")


class ResolverAcceptance(unittest.IsolatedAsyncioTestCase):
    async def test_github_release_tag_dropdown_matches_current_ui(self):
        portal = json.loads(Path("portals/github.json").read_text())
        cases = [
            ("form.open-tag", '<button>Tag: Select tag</button>', "choose-tag"),
            ("form.create-tag-dialog", '<button>Create new tag</button>', "create-new-tag"),
            ("form.tag", '<label for="tag">Tag</label><input id="tag">', "new-tag-name"),
            ("form.create-tag", '<button>Create</button>', "create-tag"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for key, html, target_key in cases:
                target_spec = next(step["target"] for step in portal["steps"] if step["key"] == key)
                (root / "page.html").write_text(html)
                (root / "targets.json").write_text(json.dumps([target_spec]))
                attempts = await check_html(root / "page.html", root / "targets.json")
                self.assertTrue(any(item["target"] == target_key and item["outcome"] == "selected"
                                    for item in attempts), key)

    async def test_all_offline_variants_and_strategy_order(self):
        from html import escape

        original = '''<form><div class="old"><label for="category">Category</label><select id="category"><option>Books</option></select></div>
        <div class="old"><label for="date">Statement date</label><input id="date"></div></form>'''
        variants = [original, original.replace('class="old"', 'class="renamed"'),
                    '<form><div><label for="date">Statement date</label><input id="date"></div><div><label for="category">Category</label><select id="category"><option>Books</option></select></div></form>',
                    '<div><section>' + original + '</section></div>',
                    '<iframe srcdoc="' + escape('<div>' + original + '</div>', quote=True) + '"></iframe>']
        targets = [target("category", "Category", "combobox"), target("date", "Statement date")]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "targets.json").write_text(json.dumps(targets))
            for index, variant in enumerate(variants):
                path = root / f"variant-{index}.html"
                path.write_text(variant)
                attempts = await check_html(path, root / "targets.json")
                winners = [a for a in attempts if a["outcome"] == "selected"]
                self.assertEqual([a["strategy"] for a in winners], ["role_name", "role_name"])

    async def test_label_nearby_structure_css_and_ambiguity(self):
        fixture = '''<label for="x">Label fallback</label><input id="x">
        <fieldset><legend>Nearby fallback</legend><div><input></div></fieldset>
        <section data-structure><input></section><input id="last-resort">
        <button>Duplicate</button><button>Duplicate</button>'''
        targets = [
            {"key": "label", "role": "textbox", "name": "Wrong", "label": "Label fallback"},
            {"key": "nearby", "label": "Wrong", "nearby": "Nearby fallback", "control": "input"},
            {"key": "structure", "label": "Wrong", "structure": "section[data-structure] input"},
            {"key": "css", "label": "Wrong", "css": ["#last-resort"]},
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "page.html").write_text(fixture)
            (root / "targets.json").write_text(json.dumps(targets))
            attempts = await check_html(root / "page.html", root / "targets.json")
            self.assertEqual([a["strategy"] for a in attempts if a["outcome"] == "selected"],
                             ["label", "nearby_text", "structure", "css_1"])
            (root / "targets.json").write_text(json.dumps([target("ambiguous", "Duplicate", "button")]))
            with self.assertRaises(FinalFailure):
                await check_html(root / "page.html", root / "targets.json")


class ProvidersAndSecurity(unittest.IsolatedAsyncioTestCase):
    def provider(self):
        return IMAPProvider(Redactor())

    def message(self, code="314159", date=None, sender="noreply@github.com", subject="GitHub verification"):
        message = EmailMessage()
        message["From"] = sender
        message["Subject"] = subject
        message["Date"] = formatdate(date or time.time(), usegmt=True)
        message.set_content(f"Your verification code is {code}.")
        return message.as_bytes()

    async def test_imap_fresh_sender_subject_single_code_and_polling(self):
        values = {"IMAP_HOST": "imap.example.test", "IMAP_USERNAME": "owner@example.test", "IMAP_PASSWORD": "app-password", "IMAP_SENDER": "noreply@github.com", "IMAP_SUBJECT": "GitHub", "IMAP_POLL_SECONDS": "0.1", "IMAP_TIMEOUT_SECONDS": "1"}
        with patch.dict(os.environ, values):
            provider = self.provider()
            challenge = Challenge("login", requested_after=time.time())
            self.assertEqual(provider.extract(self.message(), challenge), "314159")
            self.assertIsNone(provider.extract(self.message(date=time.time() - 300), challenge))
            self.assertIsNone(provider.extract(self.message(sender="attacker@example.test"), challenge))
            self.assertIsNone(provider.extract(self.message(subject="Other mail"), challenge))
            self.assertIsNone(provider.extract(self.message(code="314159 and 271828"), challenge))
            self.assertIsNone(provider.extract(self.message(), Challenge("retry", previous_code="314159", requested_after=time.time())))
            with patch.object(provider, "poll", side_effect=[None, "314159"]) as poll:
                self.assertEqual(await provider.get_code(challenge), "314159")
                self.assertEqual(poll.call_count, 2)
            with patch.object(provider, "poll", return_value=None):
                with self.assertRaises(FinalFailure):
                    await provider.get_code(challenge)

    async def test_totp_rfc_vector_and_fail_closed_evidence(self):
        # RFC 6238 SHA-1 secret at t=59; six-digit truncation of 94287082.
        with patch.dict(os.environ, {"TEST_TOTP": "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"}):
            provider = TOTPProvider("TEST_TOTP", Redactor())
            self.assertEqual(provider.totp.at(59), "287082")
        safe = EvidenceHTML.sanitize('<h1>UnknownAccountID</h1><script>password</script><svg><text>OTP</text></svg><input value="secret"><img src="private"><iframe srcdoc="private"></iframe>')
        for value in ("UnknownAccountID", "password", "OTP", "secret", "private"):
            self.assertNotIn(value, safe)
        self.assertIn("[REDACTED]", safe)
        self.assertEqual(Redactor().clean({"date": "2026-10-15"}), {"date": "2026-10-15"})
        with self.assertRaises(ValueError):
            Target(key="fragile", css=["#only-selector"])


if __name__ == "__main__":
    unittest.main()
