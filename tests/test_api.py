from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from playwright.sync_api import expect, sync_playwright

from automation.api import LocalJobService, api_token, make_server
from automation.browser import launch_options
from automation.demo import FixturePortal


class LocalAPIAcceptance(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "portals").mkdir()
        (self.root / "examples").mkdir()
        (self.root / "portals/test.json").write_text("{}")
        (self.root / "examples/input.json").write_text("{}")
        self.token = api_token(self.root)
        self.service = LocalJobService(self.root, self.token, executor=self.execute_stub)
        self.service.start()
        self.server = make_server(self.service, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.service.stop()
        self.temp.cleanup()

    @staticmethod
    def execute_stub(_job):
        return {"status": "succeeded", "manifest": "runs/test/manifest.json", "session_reused": True}

    def request(self, path, *, token=None, method="GET", body=None):
        headers = {}
        data = None
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode()
        return urlopen(Request(self.base + path, data=data, headers=headers, method=method), timeout=2)

    def test_authenticated_job_submission_and_status(self):
        with self.assertRaises(HTTPError) as caught:
            self.request("/jobs", method="POST", body={"portal": "portals/test.json", "inputs": "examples/input.json"})
        self.assertEqual(caught.exception.code, 401)

        response = self.request("/jobs", token=self.token, method="POST", body={
            "portal": "portals/test.json", "inputs": "examples/input.json", "headed": False,
        })
        self.assertEqual(response.status, 202)
        submitted = json.loads(response.read())
        self.assertEqual(submitted["status"], "queued")

        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            status = json.loads(self.request(f"/jobs/{submitted['id']}", token=self.token).read())
            if status["status"] == "succeeded":
                break
            time.sleep(0.01)
        self.assertEqual(status["status"], "succeeded")
        self.assertEqual(status["manifest"], "runs/test/manifest.json")

    def test_queue_rejects_paths_outside_project(self):
        with self.assertRaises(HTTPError) as caught:
            self.request("/jobs", token=self.token, method="POST", body={
                "portal": "../outside.json", "inputs": "examples/input.json",
            })
        self.assertEqual(caught.exception.code, 400)

    def test_pending_queue_is_bounded(self):
        started, release = threading.Event(), threading.Event()

        def blocked_executor(_job):
            started.set()
            release.wait(timeout=5)
            return {"status": "succeeded"}

        service = LocalJobService(self.root, self.token, max_queued=1, executor=blocked_executor)
        service.start()
        server = make_server(service, port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
        body = json.dumps({"portal": "portals/test.json", "inputs": "examples/input.json"}).encode()
        try:
            first = json.loads(urlopen(Request(base + "/jobs", data=body, headers=headers, method="POST"), timeout=2).read())
            self.assertTrue(started.wait(timeout=2))
            urlopen(Request(base + "/jobs", data=body, headers=headers, method="POST"), timeout=2).close()
            with self.assertRaises(HTTPError) as caught:
                urlopen(Request(base + "/jobs", data=body, headers=headers, method="POST"), timeout=2)
            self.assertEqual(caught.exception.code, 429)
            self.assertEqual(service.snapshot(first["id"])["status"], "running")
        finally:
            release.set()
            server.shutdown()
            server.server_close()
            service.stop()

    def test_health_and_token_file(self):
        health = json.loads(self.request("/health").read())
        self.assertEqual(health["status"], "ready")
        token_data = json.loads((self.root / ".state/api-token.json").read_text())
        self.assertEqual(token_data["token"], self.token)

    def test_browser_ui_submits_and_tracks_a_job(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(**launch_options())
            page = browser.new_page()
            try:
                response = page.goto(self.base + "/")
                self.assertEqual(response.status, 200)
                self.assertIn("default-src 'none'", response.headers["content-security-policy"])
                page.locator("#token").fill(self.token)
                page.locator("#portal").fill("portals/test.json")
                page.locator("#inputs").fill("examples/input.json")
                page.locator("#submit").click()
                expect(page.locator("#job-status")).to_have_text("succeeded", timeout=3000)
                expect(page.locator("#manifest")).to_have_text("runs/test/manifest.json")
                self.assertIn("Run completed", page.locator("#message").inner_text())
            finally:
                browser.close()

    def test_queued_job_runs_fixture_portal_and_captures_pdf(self):
        with FixturePortal() as fixture, fixture.credentials():
            (self.root / "portals/fixture.json").write_text(fixture.config().model_dump_json())
            (self.root / "examples/fixture-input.json").write_text(json.dumps({
                "category": "Books", "order": "Book A", "date": "2026-10-15",
            }))
            self.service.executor = self.service._run_job
            response = urlopen(Request(self.base + "/jobs", data=json.dumps({
                "portal": "portals/fixture.json", "inputs": "examples/fixture-input.json",
            }).encode(), headers={"Authorization": f"Bearer {self.token}",
                                  "Content-Type": "application/json"}, method="POST"), timeout=3)
            submitted = json.loads(response.read())
            deadline = time.monotonic() + 15
            status = None
            while time.monotonic() < deadline:
                status = json.loads(urlopen(Request(
                    self.base + f"/jobs/{submitted['id']}",
                    headers={"Authorization": f"Bearer {self.token}"}), timeout=3).read())
                if status["status"] in ("succeeded", "failed"):
                    break
                time.sleep(0.05)
            self.assertEqual(status["status"], "succeeded", status)
            manifest_path = self.root / status["manifest"]
            manifest = json.loads(manifest_path.read_text())
            capture = manifest["captured_files"][0]
            self.assertTrue((manifest_path.parent / capture["path"]).is_file())


if __name__ == "__main__":
    unittest.main()
