from __future__ import annotations

import json
import os
import re
from html import escape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


class Redactor:
    def __init__(self, secrets=()):
        self.secrets: set[str] = {str(s) for s in secrets if str(s)}

    def add(self, value):
        if value:
            self.secrets.add(str(value))

    def text(self, value: str) -> str:
        for secret in sorted(self.secrets, key=len, reverse=True):
            value = value.replace(secret, "[REDACTED]")
            # URLs can contain an encoded username or account identifier.
            from urllib.parse import quote
            value = value.replace(quote(secret, safe=""), "[REDACTED]")
        value = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[REDACTED_EMAIL]", value)
        value = re.sub(r"(?<!\w)\+\d{10,15}(?!\w)", "[REDACTED_PHONE]", value)
        return value

    def clean(self, value):
        if isinstance(value, dict):
            return {
                self.text(str(k)): "[REDACTED]" if re.search(
                    r"password|secret|token|cookie|authorization|username|account.?id|email|phone|^otp$",
                    str(k), re.I
                ) else self.clean(v)
                for k, v in value.items()
            }
        if isinstance(value, list):
            return [self.clean(x) for x in value]
        if isinstance(value, str):
            return self.text(value)
        if str(value) in self.secrets:
            return "[REDACTED]"
        return value

    def url(self, value: str) -> str:
        parts = urlsplit(value)
        # Query/fragment frequently carry signed download tokens or account data.
        return self.text(urlunsplit((parts.scheme, parts.netloc.split("@")[-1], parts.path,
                                    "[REDACTED_QUERY]" if parts.query else "", "")))


def private_json(path: Path, value):
    """Atomic replace prevents partially written session/manifest files."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.with_name(path.name + ".tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump(value, handle, indent=2)
        handle.write("\n")
    os.chmod(temp, 0o600)
    os.replace(temp, path)


class EvidenceHTML(HTMLParser):
    """Fail-closed evidence: retain structure; discard all page-controlled text/data.

    Known-secret replacement alone misses unknown account IDs. Evidence therefore
    masks *every* text node and attribute, with only fixed safe types retained.
    Offline resolver fixtures are separate non-sensitive HTML, not this evidence.
    """

    tags = {"html", "head", "body", "main", "header", "footer", "nav", "section", "article",
            "div", "span", "p", "form", "label", "input", "button", "select", "option", "textarea",
            "h1", "h2", "h3", "ul", "ol", "li", "table", "tr", "td", "th", "a", "br", "hr"}
    types = {"text", "password", "email", "number", "checkbox", "radio", "submit", "button", "date"}
    voids = {"input", "br", "hr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.output = []
        self.blocked = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "svg"):
            self.blocked += 1
        if self.blocked or tag not in self.tags:
            return
        safe = ""
        if tag == "input":
            kind = dict(attrs).get("type", "text")
            safe = f' type="{escape(kind if kind in self.types else "text")}" value="[REDACTED]"'
        self.output.append(f"<{tag}{safe}>")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "svg") and self.blocked:
            self.blocked -= 1
            return
        if not self.blocked and tag in self.tags and tag not in self.voids:
            self.output.append(f"</{tag}>")

    def handle_data(self, data):
        if not self.blocked and data.strip():
            self.output.append("[REDACTED]")

    @classmethod
    def sanitize(cls, html):
        parser = cls()
        parser.feed(html)
        return "<!doctype html>" + "".join(parser.output)
