from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from dotenv import load_dotenv

from .config import load_config
from .errors import FinalFailure
from .offline import check_html
from .otp import TOTPProvider
from .runner import Runner


def parser():
    result = argparse.ArgumentParser(description="Bravebird portal automation")
    commands = result.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="Run a JSON-configured real portal")
    run.add_argument("--portal", type=Path, required=True)
    run.add_argument("--inputs", type=Path, required=True)
    run.add_argument("--output", type=Path)
    run.add_argument("--state", type=Path, default=Path(".state/github.json"))
    run.add_argument("--headed", action="store_true")
    offline = commands.add_parser("offline", help="Resolve targets against offline HTML")
    offline.add_argument("--html", type=Path, required=True)
    offline.add_argument("--targets", type=Path, required=True)
    demo = commands.add_parser("demo", help="Run the local acceptance portal (not GitHub)")
    demo.add_argument("--output", type=Path, default=Path("runs/demo"))
    check = commands.add_parser("check-config", help="Check required settings without showing values")
    check.add_argument("--portal", type=Path, default=Path("portals/github.json"))
    check.add_argument("--inputs", type=Path, default=Path("examples/inputs.github.json"))
    return result


async def main(args):
    if args.command == "offline":
        attempts = await check_html(args.html, args.targets)
        print(json.dumps({"status": "success", "resolver_attempts": attempts}, indent=2))
        return 0
    if args.command == "demo":
        from .demo import acceptance_demo
        return await acceptance_demo(args.output)
    if args.command == "check-config":
        # Report missing settings first. Normal config interpolation correctly
        # fails fast on missing credentials, but a diagnostic needs to list all.
        portal_source = json.loads(args.portal.read_text())
        provider_name = portal_source.get("login", {}).get("provider", "totp")
        required = ["PORTAL_USERNAME", "PORTAL_PASSWORD"]
        if provider_name == "imap":
            required.extend(["IMAP_HOST", "IMAP_USERNAME", "IMAP_SENDER"])
            missing = [name for name in required if not os.environ.get(name, "").strip()]
            if not os.environ.get("IMAP_PASSWORD", "").strip() and not os.environ.get("IMAP_ACCESS_TOKEN", "").strip():
                missing.append("IMAP_PASSWORD or IMAP_ACCESS_TOKEN")
        else:
            required.append(portal_source.get("login", {}).get("totp_env", "PORTAL_TOTP_SECRET"))
            missing = [name for name in required if not os.environ.get(name, "").strip()]
        if missing:
            print(json.dumps({"status": "missing_configuration", "missing_variables": missing,
                              "detail": "Values are checked but never displayed."}))
            return 1
        portal, _inputs, redactor = load_config(args.portal, args.inputs)
        if portal.login.provider == "totp":
            # Verify that the TOTP value decodes as a seed, without displaying it.
            TOTPProvider(portal.login.totp_env, redactor)
        print(json.dumps({"status": "ready" if not missing else "missing_configuration",
                          "missing_variables": missing,
                          "detail": "Values are checked but never displayed."}))
        return 0 if not missing else 1
    portal, inputs, redactor = load_config(args.portal, args.inputs)
    output = args.output or Path("runs") / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8])
    runner = Runner(portal, inputs, redactor, output, args.state, headed=args.headed)
    success = await runner.run()
    print(json.dumps({"status": runner.manifest["status"], "manifest": str(output / "manifest.json"),
                      "session_reused": runner.manifest["session"].get("reused", False)}))
    return 0 if success else 1


def entrypoint():
    # Load .env in terminal runs, without overwriting already exported values.
    load_dotenv(dotenv_path=Path.cwd() / ".env", override=False)
    args = parser().parse_args()
    try:
        return asyncio.run(main(args))
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        # Validation/library exceptions can quote secret input values. Emit only
        # the exception class before a browser/evidence directory exists.
        safe_detail = "Check the project-root .env, input files, portal JSON, and output path."
        if isinstance(exc, FinalFailure):
            missing = re.fullmatch(
                r"Missing env value: (PORTAL_USERNAME|PORTAL_PASSWORD|PORTAL_TOTP_SECRET|IMAP_[A-Z_]+)",
                str(exc),
            )
            if missing:
                safe_detail = f"Missing environment variable {missing.group(1)}. Check the name in .env."
            elif str(exc) == "Invalid TOTP secret; use the Base32 enrollment seed":
                safe_detail = "PORTAL_TOTP_SECRET is not a valid Base32 seed. Check that you entered the authenticator setup key, not a current six-digit code."
            elif str(exc) == "Inputs must be a JSON object":
                safe_detail = "The inputs file must contain a JSON object."
        print(json.dumps({"status": "configuration_error", "error_type": type(exc).__name__,
                          "message": safe_detail}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(entrypoint())
