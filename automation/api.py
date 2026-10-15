from __future__ import annotations

import asyncio
import json
import mimetypes
import secrets
import threading
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from importlib.resources import files
from queue import Full, Queue
from urllib.parse import urlsplit

from .config import load_config
from .runner import Runner
from .security import private_json


MAX_REQUEST_BYTES = 16 * 1024
UI_ASSETS = {
    "/": "ui.html",
    "/ui.js": "ui.js",
    "/ui.css": "ui.css",
}


def api_token(root: Path) -> str:
    """Load or create a private local API bearer token under ignored state."""
    path = root / ".state" / "api-token.json"
    try:
        value = json.loads(path.read_text())
        token = value.get("token") if isinstance(value, dict) else None
        if isinstance(token, str) and len(token) >= 40:
            return token
    except (OSError, ValueError):
        pass
    token = secrets.token_urlsafe(48)
    private_json(path, {"token": token})
    return token


class LocalJobService:
    """A bounded, sequential runner queue exposed only on localhost."""

    def __init__(self, root: Path, token: str, *, max_queued=8, executor=None):
        if max_queued < 1 or max_queued > 100:
            raise ValueError("max_queued must be between 1 and 100")
        self.root = root.resolve()
        self.token = token
        self.queue: Queue[str | None] = Queue(maxsize=max_queued)
        self.jobs: dict[str, dict] = {}
        self.lock = threading.Lock()
        self.executor = executor or self._run_job
        self.worker = threading.Thread(target=self._work, name="automation-job-worker", daemon=True)

    def start(self):
        self.worker.start()

    def stop(self):
        if self.worker.is_alive():
            self.queue.put(None)
            self.worker.join(timeout=2)

    def resolve_json(self, value):
        if not isinstance(value, str) or not value or "\\" in value:
            raise ValueError("portal and inputs must be project-relative JSON paths")
        candidate = Path(value)
        if candidate.is_absolute() or ".." in candidate.parts or candidate.suffix.lower() != ".json":
            raise ValueError("portal and inputs must be project-relative JSON paths")
        resolved = (self.root / candidate).resolve(strict=True)
        if not resolved.is_relative_to(self.root) or not resolved.is_file():
            raise ValueError("portal and inputs must be project-local files")
        return resolved

    def submit(self, body):
        if not isinstance(body, dict) or set(body) - {"portal", "inputs", "headed"}:
            raise ValueError("Expected portal, inputs, and optional headed fields")
        if "headed" in body and not isinstance(body["headed"], bool):
            raise ValueError("headed must be a boolean")
        portal = self.resolve_json(body.get("portal"))
        inputs = self.resolve_json(body.get("inputs"))
        job_id = uuid.uuid4().hex
        job = {
            "id": job_id,
            "status": "queued",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "portal": portal.relative_to(self.root).as_posix(),
            "inputs": inputs.relative_to(self.root).as_posix(),
            "headed": body.get("headed", False),
        }
        with self.lock:
            self.jobs[job_id] = job
        try:
            self.queue.put_nowait(job_id)
        except Full:
            with self.lock:
                self.jobs.pop(job_id, None)
            raise
        return self.snapshot(job_id)

    def snapshot(self, job_id):
        with self.lock:
            job = self.jobs.get(job_id)
            return dict(job) if job else None

    def health(self):
        with self.lock:
            running = sum(job["status"] == "running" for job in self.jobs.values())
        return {"status": "ready", "queued": self.queue.qsize(), "running": running}

    def _work(self):
        while True:
            job_id = self.queue.get()
            if job_id is None:
                self.queue.task_done()
                return
            with self.lock:
                self.jobs[job_id]["status"] = "running"
                self.jobs[job_id]["started_at"] = datetime.now(timezone.utc).isoformat()
                job = dict(self.jobs[job_id])
            try:
                result = self.executor(job)
                with self.lock:
                    self.jobs[job_id].update(result)
                    self.jobs[job_id]["finished_at"] = datetime.now(timezone.utc).isoformat()
            except Exception as exc:
                with self.lock:
                    self.jobs[job_id].update(
                        status="failed",
                        error_type=type(exc).__name__,
                        message="Job failed. Inspect its local manifest when available.",
                        finished_at=datetime.now(timezone.utc).isoformat(),
                    )
            finally:
                self.queue.task_done()

    def _run_job(self, job):
        portal_path = self.root / job["portal"]
        inputs_path = self.root / job["inputs"]
        portal, inputs, redactor = load_config(portal_path, inputs_path)
        output = self.root / "runs" / f"api-{job['id']}"
        state = self.root / ".state" / f"api-{portal_path.stem}.json"
        runner = Runner(portal, inputs, redactor, output, state, headed=job["headed"])
        success = asyncio.run(runner.run())
        return {
            "status": "succeeded" if success else "failed",
            "manifest": output.relative_to(self.root).as_posix() + "/manifest.json",
            "session_reused": runner.manifest["session"].get("reused", False),
        }


def make_server(service: LocalJobService, port=8765):
    class Handler(BaseHTTPRequestHandler):
        server_version = "LocalAutomationAPI/1"

        def log_message(self, _format, *args):
            # Do not log bearer headers, request bodies, account inputs, or codes.
            return

        def send_json(self, status, payload):
            encoded = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(encoded)

        def authorized(self):
            value = self.headers.get("Authorization", "")
            scheme, _, supplied = value.partition(" ")
            return scheme.lower() == "bearer" and secrets.compare_digest(supplied, service.token)

        def do_GET(self):
            path = urlsplit(self.path).path
            if path in UI_ASSETS:
                asset = files("automation").joinpath(UI_ASSETS[path]).read_bytes()
                content_type = mimetypes.guess_type(UI_ASSETS[path])[0] or "application/octet-stream"
                self.send_response(200)
                self.send_header("Content-Type", f"{content_type}; charset=utf-8")
                self.send_header("Content-Length", str(len(asset)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'")
                self.end_headers()
                self.wfile.write(asset)
                return
            if path == "/health":
                self.send_json(200, service.health())
                return
            if not self.authorized():
                self.send_json(401, {"error": "unauthorized"})
                return
            parts = path.strip("/").split("/")
            if len(parts) == 2 and parts[0] == "jobs":
                job = service.snapshot(parts[1])
                self.send_json(200 if job else 404, job or {"error": "not_found"})
                return
            self.send_json(404, {"error": "not_found"})

        def do_POST(self):
            if urlsplit(self.path).path != "/jobs":
                self.send_json(404, {"error": "not_found"})
                return
            if not self.authorized():
                self.send_json(401, {"error": "unauthorized"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length < 1 or length > MAX_REQUEST_BYTES:
                    self.send_json(413, {"error": "request_too_large_or_empty"})
                    return
                if not self.headers.get("Content-Type", "").lower().startswith("application/json"):
                    self.send_json(415, {"error": "json_required"})
                    return
                body = json.loads(self.rfile.read(length))
                job = service.submit(body)
            except Full:
                self.send_json(429, {"error": "queue_full"})
            except (ValueError, json.JSONDecodeError, OSError):
                self.send_json(400, {"error": "invalid_job_request"})
            else:
                self.send_json(202, job)

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def serve(root: Path, *, port=8765, max_queued=8):
    root = root.resolve()
    token = api_token(root)
    service = LocalJobService(root, token, max_queued=max_queued)
    server = make_server(service, port)
    service.start()
    print(json.dumps({
        "status": "ready",
        "url": f"http://127.0.0.1:{server.server_port}",
        "token_file": str((root / ".state" / "api-token.json").relative_to(root)),
        "max_queued": max_queued,
    }))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        service.stop()
