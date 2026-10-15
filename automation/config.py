from __future__ import annotations

import json
import os
import re
from pathlib import Path

from .errors import FinalFailure
from .models import Portal
from .security import Redactor

TOKEN = re.compile(r"\{\{(inputs|env)\.([A-Za-z_][A-Za-z0-9_]*)\}\}")


def load_config(path: Path, inputs_path: Path):
    raw = json.loads(path.read_text())
    inputs = json.loads(inputs_path.read_text())
    if not isinstance(inputs, dict):
        raise FinalFailure("Inputs must be a JSON object")
    redactor = Redactor()
    for key in raw.get("sensitive_inputs", ["account_id", "email", "phone"]):
        redactor.add(inputs.get(key))

    def render(value):
        if isinstance(value, list):
            return [render(v) for v in value]
        if isinstance(value, dict):
            return {k: render(v) for k, v in value.items()}
        if not isinstance(value, str):
            return value

        def replace(match):
            kind, key = match.groups()
            source = inputs if kind == "inputs" else os.environ
            if key not in source or source[key] is None:
                raise FinalFailure(f"Missing {kind} value: {key}")
            result = str(source[key])
            if kind == "env":
                if not result.strip():
                    raise FinalFailure(f"Missing env value: {key}")
                redactor.add(result)
            return result

        return TOKEN.sub(replace, value)

    portal = Portal.model_validate(render(raw))
    # A seed may not appear in a template; register it independently.
    redactor.add(os.environ.get(portal.login.totp_env))
    for key in ("IMAP_USERNAME", "IMAP_PASSWORD", "IMAP_ACCESS_TOKEN"):
        redactor.add(os.environ.get(key))
    return portal, inputs, redactor
