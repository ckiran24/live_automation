from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Target(Model):
    """Independent descriptions of a control, ordered by semantic stability."""

    key: str
    role: str | None = None
    name: str | None = None
    label: str | None = None
    text: str | None = None
    nearby: str | None = None
    control: str = "input, select, textarea, button, a"
    structure: str | None = None
    css: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def multiple_descriptions(self):
        count = bool(self.role and self.name) + sum(
            bool(x) for x in (self.label, self.text, self.nearby, self.structure, self.css)
        )
        if count < 2:
            raise ValueError("Each target needs at least two independent locator strategies")
        return self


class Action(Model):
    key: str
    kind: Literal["goto", "click", "fill", "select", "wait", "download", "popup_pdf", "print_pdf"]
    target: Target | None = None
    value: str | None = None
    filename: str | None = None
    # Retrying a click can duplicate a side effect. Opt in only for safe navigation.
    retry_safe: bool = False

    @model_validator(mode="after")
    def required_fields(self):
        if self.kind not in ("print_pdf", "goto") and self.target is None:
            raise ValueError("This action requires a target")
        if self.kind in ("fill", "select", "goto") and self.value is None:
            raise ValueError("fill/select requires a value")
        if self.kind == "goto" and (not self.value.startswith("/") or self.value.startswith("//")):
            raise ValueError("goto must use a relative path on the configured origin")
        if self.kind in ("download", "popup_pdf", "print_pdf") and not self.filename:
            raise ValueError("Captures require a filename")
        return self


class Identity(Model):
    target: Target
    attribute: str
    equals: str


class Session(Model):
    path: str
    markers: list[Target] = Field(min_length=2)
    probe_path: str | None = None
    probe_json: dict[str, str | bool | int] | None = None
    identity: Identity | None = None


class Login(Model):
    path: str
    steps: list[Action]
    challenge: Target
    submit: Target
    rejected: Target
    resend: Target | None = None
    provider: Literal["totp", "imap"] = "totp"
    totp_env: str = "PORTAL_TOTP_SECRET"


class Portal(Model):
    name: str
    base_url: str
    session: Session
    login: Login
    steps: list[Action]
    sensitive_inputs: list[str] = Field(default_factory=lambda: ["account_id", "email", "phone"])
    timeout_ms: int = Field(default=8000, ge=100, le=120000)
    attempts: int = Field(default=3, ge=1, le=5)
    backoff_seconds: float = Field(default=0.3, ge=0, le=10)

    @model_validator(mode="after")
    def validate_portal(self):
        from urllib.parse import urlsplit

        url = urlsplit(self.base_url)
        if url.scheme not in ("https", "http") or not url.hostname or url.username or url.password:
            raise ValueError("base_url must be an HTTP(S) origin without credentials")
        if url.path not in ("", "/") or url.query or url.fragment:
            raise ValueError("base_url must contain only the origin")
        if url.scheme == "http" and url.hostname not in ("localhost", "127.0.0.1", "::1"):
            raise ValueError("Use HTTPS for real portals")
        for path in (self.session.path, self.session.probe_path, self.login.path):
            if path and (not path.startswith("/") or path.startswith("//")):
                raise ValueError("Portal paths must be relative to the configured origin")
        keys = [a.key for a in self.steps]
        if len(keys) != len(set(keys)):
            raise ValueError("Action keys must be unique")
        return self
