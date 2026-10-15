"""Disposable local acceptance portal. This is deliberately not a live-site claim."""
from __future__ import annotations

import hashlib
import html
import json
import os
import secrets
import threading
from contextlib import contextmanager
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

import pyotp

from .models import Portal, Target
from .runner import Runner
from .security import Redactor, private_json


def target(key, name, role="textbox", css=None):
    result = {"key": key, "role": role, "name": name, "label": name}
    if role not in ("textbox", "combobox"):
        result.pop("label")
        result["text"] = name
    if css:
        result["css"] = [css]
    return result


FORM = '''<!doctype html><html><body><h1>Report form</h1>
<form action="/result" method="get" target="_top">
<div data-field><label for="category">Category</label><select id="category" name="category"
onchange="let o=document.getElementById('order');o.disabled=false;o.innerHTML=this.value==='Books'?'<option>Book A</option><option>Book B</option>':'<option>Device A</option><option>Device B</option>'">
<option value="">Choose a category</option><option>Books</option><option>Devices</option></select></div>
<div data-field><label for="order">Order</label><select id="order" name="order" disabled><option>Choose category first</option></select></div>
<div data-field><label for="date">Statement date</label><input id="date" name="date" type="text"></div>
<button type="submit">Generate document</button></form></body></html>'''


def pdf_bytes(text):
    text = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = f"BT /F1 14 Tf 50 750 Td ({text}) Tj ET".encode("ascii", "replace")
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
               b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"]
    result = b"%PDF-1.4\n"
    offsets = [0]
    for i, value in enumerate(objects, 1):
        offsets.append(len(result))
        result += f"{i} 0 obj\n".encode() + value + b"\nendobj\n"
    xref = len(result)
    result += f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode()
    result += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets[1:])
    result += f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return result


class FixturePortal:
    def __init__(self):
        self.username = "fixture-owner@example.test"
        self.password = secrets.token_urlsafe(24)
        self.secret = pyotp.random_base32()
        self.sessions = set()
        self.challenges = set()
        self.login_count = 0
        self.code_count = 0
        self.reject_codes = 0
        self.transient_documents = 0
        self.server = None

    @property
    def base_url(self):
        return f"http://127.0.0.1:{self.server.server_port}"

    def __enter__(self):
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def send(self, content, status=200, content_type="text/html", cookie=None):
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                if cookie:
                    self.send_header("Set-Cookie", cookie)
                self.end_headers()
                self.wfile.write(content.encode() if isinstance(content, str) else content)

            def cookie(self, key):
                values = SimpleCookie(self.headers.get("Cookie", ""))
                return values[key].value if key in values else None

            def redirect(self, url, cookie=None):
                self.send_response(303)
                self.send_header("Location", url)
                if cookie:
                    self.send_header("Set-Cookie", cookie)
                self.end_headers()

            def do_GET(self):
                parsed = urlsplit(self.path)
                path = parsed.path
                if path == "/login":
                    self.send('''<h1>Sign in</h1><form method="post" action="/login">
                    <label>Username<input name="username"></label>
                    <label>Password<input type="password" name="password"></label>
                    <button>Sign in</button></form>''')
                    return
                if path == "/two-factor":
                    self.challenge()
                    return
                valid = self.cookie("session") in fixture.sessions
                if path == "/api/session":
                    self.send(json.dumps({"authenticated": valid}), 200 if valid else 401, "application/json")
                    return
                if not valid:
                    # Deliberately HTTP 200 at the private URL: no redirect signal.
                    self.send('<h1>Session expired</h1><a href="/login">Sign in</a>')
                    return
                if path == "/account":
                    self.send('<h1>Your account</h1><button>Sign out</button><a href="/workspace">Workspace</a>')
                elif path == "/workspace":
                    self.send('<h1>Workspace</h1><a href="/documents">Documents</a>')
                elif path == "/documents":
                    if fixture.transient_documents:
                        fixture.transient_documents -= 1
                        self.send("Temporarily unavailable", 503)
                    else:
                        self.send('<h1>Documents</h1><a href="/reports">Create report</a>')
                elif path == "/reports":
                    self.send('<h1>Reports</h1><iframe title="Report fields" src="/form"></iframe>')
                elif path == "/form":
                    self.send(FORM)
                elif path == "/result":
                    query = parse_qs(parsed.query)
                    text = " | ".join(query.get(k, [""])[0] for k in ("category", "order", "date"))
                    escaped = html.escape(text)
                    encoded = html.escape(urlencode({"text": text}), quote=True)
                    self.send(f'<h1>Document ready</h1><p>{escaped}</p><a href="/download?{encoded}">Download PDF</a><a href="/print?{encoded}" target="_blank">Print view</a>')
                elif path in ("/download", "/print"):
                    text = parse_qs(parsed.query).get("text", [""])[0]
                    if path == "/download":
                        self.send_response(200)
                        self.send_header("Content-Type", "application/pdf")
                        self.send_header("Content-Disposition", 'attachment; filename="report.pdf"')
                        self.end_headers()
                        self.wfile.write(pdf_bytes(text))
                    else:
                        self.send(f'<h1>Printable statement</h1><p>{html.escape(text)}</p>')
                else:
                    self.send("Not found", 404)

            def challenge(self, rejected=False):
                prefix = '<p role="alert">Incorrect authentication code</p>' if rejected else ""
                self.send(prefix + '''<form method="post" action="/two-factor">
                <label>Authentication code<input name="code" autocomplete="one-time-code"></label>
                <button>Verify</button></form>''')

            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                values = parse_qs(self.rfile.read(length).decode())
                if self.path == "/login":
                    fixture.login_count += 1
                    if values.get("username") != [fixture.username] or values.get("password") != [fixture.password]:
                        self.send("Invalid credentials", 403)
                        return
                    challenge = secrets.token_urlsafe(24)
                    fixture.challenges.add(challenge)
                    self.redirect("/two-factor", f"challenge={challenge}; HttpOnly; SameSite=Lax; Path=/")
                elif self.path == "/two-factor":
                    fixture.code_count += 1
                    challenge = self.cookie("challenge")
                    correct = pyotp.TOTP(fixture.secret).verify(values.get("code", [""])[0], valid_window=1)
                    rejected = fixture.reject_codes > 0
                    if rejected:
                        fixture.reject_codes -= 1
                    if challenge not in fixture.challenges or not correct or rejected:
                        self.challenge(True)
                        return
                    fixture.challenges.remove(challenge)
                    session = secrets.token_urlsafe(24)
                    fixture.sessions.add(session)
                    self.redirect("/account", f"session={session}; HttpOnly; SameSite=Lax; Path=/")
                else:
                    self.send("Not found", 404)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    @contextmanager
    def credentials(self):
        values = {"PORTAL_TOTP_SECRET": self.secret}
        previous = {k: os.environ.get(k) for k in values}
        os.environ.update(values)
        try:
            yield
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def config(self, *, category="Books", order="Book A", date="2026-10-15", capture="download"):
        login = {
            "path": "/login",
            "steps": [
                {"key": "username", "kind": "fill", "target": target("username", "Username"), "value": self.username},
                {"key": "password", "kind": "fill", "target": {"key": "password", "label": "Password", "structure": "input[type=password]"}, "value": self.password},
                {"key": "credentials", "kind": "click", "target": target("sign-in", "Sign in", "button")},
            ],
            "challenge": target("code", "Authentication code"),
            "submit": target("verify", "Verify", "button"),
            "rejected": {"key": "rejected", "text": "Incorrect authentication code", "structure": "[role=alert]"},
        }
        steps = [
            {"key": "workspace", "kind": "click", "retry_safe": True, "target": target("workspace", "Workspace", "link")},
            {"key": "documents", "kind": "goto", "value": "/documents", "retry_safe": True},
            {"key": "reports", "kind": "click", "retry_safe": True, "target": target("reports", "Create report", "link")},
            {"key": "category", "kind": "select", "value": category, "target": target("category", "Category", "combobox")},
            {"key": "order-enabled", "kind": "wait", "target": target("order-enabled", "Order", "combobox")},
            {"key": "order", "kind": "select", "value": order, "target": target("order", "Order", "combobox")},
            {"key": "date", "kind": "fill", "value": date, "target": target("date", "Statement date")},
            {"key": "generate", "kind": "click", "target": target("generate", "Generate document", "button")},
        ]
        capture_action = {"key": "capture", "kind": capture, "filename": "report.pdf"}
        if capture != "print_pdf":
            capture_action["target"] = target("capture", "Download PDF" if capture == "download" else "Print view", "link")
        steps.append(capture_action)
        return Portal.model_validate({
            "name": "local-acceptance-fixture", "base_url": self.base_url,
            "timeout_ms": 1500, "backoff_seconds": 0.05,
            "session": {"path": "/account", "markers": [target("account", "Your account", "heading"), target("sign-out", "Sign out", "button")],
                        "probe_path": "/api/session", "probe_json": {"authenticated": True}},
            "login": login, "steps": steps,
        })

    def redactor(self):
        return Redactor([self.username, self.password, self.secret])


async def acceptance_demo(root: Path):
    if root.exists():
        raise ValueError("Choose a new output directory; existing outputs are preserved")
    root.mkdir(parents=True, mode=0o700)
    results = []
    with FixturePortal() as portal, portal.credentials():
        state = root / ".state" / "fixture.json"

        async def execute(name, config=None, inputs=None):
            runner = Runner(config or portal.config(), inputs or {"category": "Books", "order": "Book A", "date": "2026-10-15"},
                            portal.redactor(), root / name, state)
            result = await runner.run()
            results.append({"scenario": name, "success": result, "session": runner.manifest["session"],
                            "duration_ms": runner.manifest["duration_ms"]})
            return runner

        first = await execute("01-first-login")
        await execute("02-reuse")
        state.write_text("{corrupt")
        await execute("03-corrupt-state")
        portal.sessions.clear()  # Valid JSON/cookies but server-side revocation, HTTP 200.
        await execute("04-server-expired")
        changed = await execute("05-changed-input", portal.config(category="Devices", order="Device B", date="2026-10-16"),
                                {"category": "Devices", "order": "Device B", "date": "2026-10-16"})
        broken = portal.config()
        broken.steps[-1].target = Target(key="deliberately-broken", role="link", name="Missing document", css=["#absent"])
        await execute("06-intentional-failure", broken)
        await execute("07-popup", portal.config(capture="popup_pdf"))
        await execute("08-print", portal.config(capture="print_pdf"))
        portal.transient_documents = 1
        retry = await execute("09-transient-retry")
        hashes_differ = first.manifest["captured_files"] and changed.manifest["captured_files"] and (
            first.manifest["captured_files"][0]["sha256"] != changed.manifest["captured_files"][0]["sha256"])
    expected = all(r["success"] == (r["scenario"] != "06-intentional-failure") for r in results)
    expected = expected and bool(hashes_differ) and any(x["status"] == "retry" for x in retry.manifest["stages"])
    private_json(root / "summary.json", {"source": "local fixture, not a real GitHub run", "passed": expected,
                                         "changed_input_changed_document": bool(hashes_differ), "results": results})
    print(json.dumps({"source": "local fixture", "passed": expected, "summary": str(root / "summary.json")}))
    return 0 if expected else 1
