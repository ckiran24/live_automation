from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .config import load_config
from .offline import check_html
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
    return result


async def main(args):
    if args.command == "offline":
        attempts = await check_html(args.html, args.targets)
        print(json.dumps({"status": "success", "resolver_attempts": attempts}, indent=2))
        return 0
    if args.command == "demo":
        from .demo import acceptance_demo
        return await acceptance_demo(args.output)
    portal, inputs, redactor = load_config(args.portal, args.inputs)
    output = args.output or Path("runs") / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8])
    runner = Runner(portal, inputs, redactor, output, args.state, headed=args.headed)
    success = await runner.run()
    print(json.dumps({"status": runner.manifest["status"], "manifest": str(output / "manifest.json"),
                      "session_reused": runner.manifest["session"].get("reused", False)}))
    return 0 if success else 1


def entrypoint():
    args = parser().parse_args()
    try:
        return asyncio.run(main(args))
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        # Validation/library exceptions can quote secret input values. Emit only
        # the exception class before a browser/evidence directory exists.
        print(json.dumps({"status": "configuration_error", "error_type": type(exc).__name__,
                          "message": "Check JSON schemas, required environment variable names, and output path."}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(entrypoint())
