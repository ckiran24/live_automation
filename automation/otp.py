from __future__ import annotations

import asyncio
import os
import time
import imaplib
import re
import ssl
from email import policy
from email.parser import BytesParser
from email.utils import parsedate_to_datetime, parseaddr
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Protocol

import pyotp

from .errors import FinalFailure
from .security import Redactor


@dataclass(frozen=True)
class Challenge:
    stage: str
    attempt: int = 1
    previous_code: str | None = None
    requested_after: float = 0


class CodeProvider(Protocol):
    async def get_code(self, challenge: Challenge) -> str: ...


class TOTPProvider:
    """RFC 6238 codes from an existing authenticator seed, never from chat."""

    def __init__(self, env_name: str, redactor: Redactor):
        secret = os.environ.get(env_name)
        if not secret:
            raise FinalFailure(f"Missing environment variable: {env_name}")
        self.totp = pyotp.TOTP(secret.replace(" ", ""))
        self.redactor = redactor
        self.redactor.add(secret)
        self.redactor.add(secret.replace(" ", ""))
        try:
            self.totp.now()
        except Exception as exc:
            raise FinalFailure("Invalid TOTP secret; use the Base32 enrollment seed") from exc

    async def get_code(self, challenge: Challenge) -> str:
        # Avoid sending a code about to expire in transit.
        remaining = self.totp.interval - time.time() % self.totp.interval
        if remaining < 3:
            await asyncio.sleep(remaining + 0.1)
        code = self.totp.now()
        # A rejected code gets exactly one retry, in the next time window.
        if code == challenge.previous_code:
            await asyncio.sleep(self.totp.interval - time.time() % self.totp.interval + 0.1)
            code = self.totp.now()
        self.redactor.add(code)
        return code


class IMAPProvider:
    """Poll a TLS mailbox for a fresh, sender-matched message, without marking read.

    Password authentication should use an app password. Servers requiring OAuth
    can receive a short-lived access token through IMAP_ACCESS_TOKEN instead.
    """

    def __init__(self, redactor: Redactor):
        required = ("IMAP_HOST", "IMAP_USERNAME", "IMAP_SENDER")
        for name in required:
            if not os.environ.get(name):
                raise FinalFailure(f"Missing environment variable: {name}")
        self.host = os.environ["IMAP_HOST"]
        self.username = os.environ["IMAP_USERNAME"]
        self.password = os.environ.get("IMAP_PASSWORD")
        self.access_token = os.environ.get("IMAP_ACCESS_TOKEN")
        if not self.password and not self.access_token:
            raise FinalFailure("IMAP_PASSWORD or IMAP_ACCESS_TOKEN is required")
        self.sender = os.environ["IMAP_SENDER"].lower()
        self.folder = os.environ.get("IMAP_FOLDER", "INBOX")
        self.subject = os.environ.get("IMAP_SUBJECT", "GitHub")
        self.pattern = re.compile(os.environ.get("IMAP_CODE_PATTERN", r"(?<!\d)(\d{6,8})(?!\d)"))
        if self.pattern.groups != 1:
            raise FinalFailure("IMAP_CODE_PATTERN must have exactly one capture group")
        self.timeout = min(max(float(os.environ.get("IMAP_TIMEOUT_SECONDS", "90")), 1), 300)
        self.interval = min(max(float(os.environ.get("IMAP_POLL_SECONDS", "3")), 0.1), 15)
        self.redactor = redactor
        self.consumed = set()
        for value in (self.username, self.password, self.access_token):
            redactor.add(value)

    def extract(self, raw: bytes, challenge: Challenge):
        message = BytesParser(policy=policy.default).parsebytes(raw)
        if parseaddr(str(message.get("From", "")))[1].lower() != self.sender:
            return None
        if self.subject.lower() not in str(message.get("Subject", "")).lower():
            return None
        try:
            received = parsedate_to_datetime(str(message["Date"])).timestamp()
        except (ValueError, TypeError, OverflowError):
            return None
        if received < challenge.requested_after - 30 or received > time.time() + 60:
            return None
        parts, html_parts = [], []
        for part in message.walk():
            if part.get_content_type() in ("text/plain", "text/html") and part.get_content_disposition() != "attachment":
                try:
                    content = part.get_content()
                    (parts if part.get_content_type() == "text/plain" else html_parts).append(content)
                except (LookupError, UnicodeError):
                    continue
        candidates = set(self.pattern.findall("\n".join(parts or html_parts)))
        candidates.discard(challenge.previous_code)
        if len(candidates) != 1:
            return None
        code = candidates.pop()
        self.redactor.add(code)
        return code

    def poll(self, challenge: Challenge):
        try:
            with imaplib.IMAP4_SSL(self.host, 993, ssl_context=ssl.create_default_context(), timeout=10) as client:
                if self.access_token:
                    auth = f"user={self.username}\x01auth=Bearer {self.access_token}\x01\x01".encode()
                    client.authenticate("XOAUTH2", lambda _: auth)
                else:
                    client.login(self.username, self.password)
                status, _ = client.select(self.folder, readonly=True)
                if status != "OK":
                    raise FinalFailure("Unable to select IMAP folder")
                since = datetime.fromtimestamp(challenge.requested_after - 30, timezone.utc).strftime("%d-%b-%Y")
                status, data = client.uid("search", None, "SINCE", since)
                if status != "OK":
                    raise FinalFailure("IMAP search failed")
                # Inspect newest messages first; do not scan an unbounded mailbox.
                for uid in reversed(data[0].split()[-50:]):
                    if uid in self.consumed:
                        continue
                    status, rows = client.uid("fetch", uid, "(BODY.PEEK[])")
                    if status != "OK":
                        continue
                    for row in rows:
                        if isinstance(row, tuple) and isinstance(row[1], bytes):
                            code = self.extract(row[1], challenge)
                            if code:
                                self.consumed.add(uid)
                                return code
        except imaplib.IMAP4.abort:
            return None  # A dropped connection can be retried by bounded polling.
        except imaplib.IMAP4.error as exc:
            raise FinalFailure("IMAP authentication or protocol failure") from exc
        except ssl.SSLCertVerificationError as exc:
            raise FinalFailure("IMAP TLS verification failed") from exc
        except (TimeoutError, OSError):
            return None
        return None

    async def get_code(self, challenge: Challenge) -> str:
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            try:
                code = await asyncio.wait_for(asyncio.to_thread(self.poll, challenge), timeout=remaining)
            except asyncio.TimeoutError:
                break
            if code:
                return code
            await asyncio.sleep(min(self.interval, max(0, deadline - time.monotonic())))
        raise FinalFailure("No fresh matching email code arrived before the timeout")
