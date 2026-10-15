# Download and run in VS Code

If Git is installed, you can clone and open the repository directly from PowerShell:

```powershell
git clone https://github.com/ckiran24/live_automation.git
cd live_automation
code .
```

Then continue with Python installation and environment setup below. Alternatively, use the ZIP instructions in step 1.

1. Extract `live_automation.zip` and open the extracted **live_automation** folder using VS Code's **File → Open Folder**. Open the folder containing `README.md`, `requirements.lock`, and `automation/`, rather than its parent.
2. Install Python 3.11 or newer and Microsoft's **Python** and **Python Debugger** extensions. VS Code will recommend these extensions for this folder.
3. Open **Terminal → New Terminal** and run the commands for your operating system below. These install project dependencies and Chromium; no GitHub account credentials are needed for the local demo.

## Windows (PowerShell)

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m playwright install chromium
.\.venv\Scripts\python.exe -m automation demo --output runs/local-demo
```

If Windows does not recognize `py`, use `python` in the first command. Explicit interpreter paths avoid needing to change PowerShell's execution policy or activate the environment.

## macOS or Linux

```bash
bash scripts/setup.sh
.venv/bin/python -m automation demo --output runs/local-demo
```

On a Linux machine missing browser system libraries, use Playwright's documented `install --with-deps chromium` command with appropriate administrator privileges.

## Run and debug

Use **Ctrl+Shift+P → Python: Select Interpreter**, then choose the interpreter inside `.venv`. Open **Run and Debug**, select **Local demo (no account needed)**, and press **F5**. A breakpoint in `automation/runner.py` lets you step through session checking, login, form filling, and capture. **Offline resolver** runs the saved-HTML case without any network access.

The local demo prints a JSON result with `passed: true` and writes `summary.json`, manifests, PDFs, and an intentional failure bundle under the chosen output directory. Eight workflows succeed and one deliberately fails to demonstrate evidence capture. The command exits successfully only if these expected outcomes occur.

Output directories must be fresh. If a demo has already run, change the `--output` path (including in `.vscode/launch.json`) to a new name or move the previous local output before running it again. Breakpoints pause the client but not the local server or its clock, so a long pause during TOTP submission can expire a code; re-run without pausing in the authentication step when checking acceptance.

Run the tests using the same interpreter:

```powershell
# Windows
.\.venv\Scripts\python.exe -m unittest discover -v
```

```bash
# macOS/Linux
.venv/bin/python -m unittest discover -v
```

The full local suite has 17 tests and passed in the development environment. The real GitHub acceptance matrix (fresh login, reuse, corrupted-state recovery, and changed inputs) was also completed from PowerShell on the user's Windows machine. The live manifests and PDFs remain on that machine.

## Your real GitHub account

Follow [GITHUB_SETUP.md](GITHUB_SETUP.md) to enable the selected native GitHub password/TOTP login. In the project root, run `Copy-Item .env.example .env` in PowerShell, then fill only the required `PORTAL_USERNAME`, `PORTAL_PASSWORD`, and `PORTAL_TOTP_SECRET` values privately. The CLI loads this file automatically and `.gitignore` excludes it. The TOTP value is the existing Base32 enrollment seed, not the changing six-digit code.

Run `.\.venv\Scripts\python.exe -m automation check-config` in PowerShell to check the required settings without showing their values. Then choose **GitHub preview (requires password and TOTP)** in **Run and Debug** and press **F5**, or run the command below in a terminal. Both CLI launches load the project-root `.env` automatically.

The configured target is `ckiran24/shopping_bot`. The workflow fills an unpublished release preview and prints a PDF. The local demo validates mechanics with synthetic credentials; it does not replace the completed live GitHub acceptance run.

For a full code walkthrough and interview preparation, see [PROJECT_STUDY_GUIDE.pdf](PROJECT_STUDY_GUIDE.pdf) and [CTO_FINAL_ROUND_QA.pdf](CTO_FINAL_ROUND_QA.pdf).

The ZIP includes source, documentation, debugger settings, and synthetic example results. It excludes Git metadata, virtual environments, caches, real run/session state, and populated environment files. It is a source snapshot, not a clone containing commit history. You can initialize Git locally if you want history for your own changes.
