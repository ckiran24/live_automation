#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m venv .venv
.venv/bin/python -m pip install --disable-pip-version-check -r requirements.lock
if [[ -n "${BROWSER_EXECUTABLE:-}" ]]; then
  test -x "$BROWSER_EXECUTABLE"
elif command -v chromium >/dev/null; then
  chromium --version
else
  .venv/bin/python -m playwright install chromium
fi
.venv/bin/python -m pip check
echo 'Setup complete. Run: .venv/bin/python -m automation demo'
