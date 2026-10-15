# Bravebird Browser Automation

This project automates a real GitHub release-preview workflow with Playwright. It signs in with a GitHub password and authenticator code, checks and reuses browser sessions, fills the release form in `ckiran24/shopping_bot`, and saves a PDF preview. It does **not** publish a release or save a draft.

The required workflow has passed the live acceptance run: fresh login, session reuse, recovery from corrupted state, and a run with changed inputs. Offline locator mutation, failure-evidence redaction, and all 17 local tests also pass. The optional local job API and browser UI are implemented and tested. See [validation evidence](docs/VALIDATION.md) for what was run and where its private live artifacts remain.

For a detailed, file-by-file explanation, use the [project study guide](docs/PROJECT_STUDY_GUIDE.pdf). The [CTO final-round practice pack](docs/CTO_FINAL_ROUND_QA.pdf) is a separate interview-preparation document.

## Run it in VS Code

Clone the repository and open its root folder:

```powershell
git clone https://github.com/ckiran24/live_automation.git
cd live_automation
code .
```

Use Python 3.11 or newer. In the VS Code terminal on Windows, create the environment and install the pinned packages and browser:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m playwright install chromium
```

On macOS or Linux, run `bash scripts/setup.sh`. It creates `.venv`, installs from the same lock file, and uses system Chromium or installs Playwright Chromium if needed.

Run the local demo and tests; neither needs a GitHub account:

```powershell
.\.venv\Scripts\python.exe -m automation demo --output runs/local-demo
.\.venv\Scripts\python.exe -m unittest discover -v
```

The demo uses a disposable local portal. It covers login, TOTP, session reuse, dependent form fields, document capture, retry, and a deliberately broken step. Use a new `--output` directory each time because existing run output is preserved.

## Run the live GitHub workflow

Follow [GitHub authentication setup](docs/GITHUB_SETUP.md). Copy `.env.example` to `.env` and enter your GitHub username, native GitHub password, and Base32 authenticator enrollment seed in that local file. The seed is not the changing six-digit code. Never commit `.env`, send credentials in chat, or put them in a portal/input JSON file. The command below checks configuration without printing secret values:

```powershell
Copy-Item .env.example .env
code .env
.\.venv\Scripts\python.exe -m automation check-config
```

Start a preview run from the repository root:

```powershell
.\.venv\Scripts\python.exe -m automation run --portal portals/github.json --inputs examples/inputs.github.json --headed
```

The command prints the manifest path. The PDF is beside that manifest under `documents\shopping-bot-release-preview.pdf`. Run `scripts/test-live.ps1 -Headed` to repeat all four live checks with a separate test session and output directory. The script does not publish a release.

The business values live in `examples/inputs.github.json`; the portal selectors and action sequence live in `portals/github.json`. `examples/inputs.github.alternate.json` changes the title, notes, tag, and output filename without a code change. A unique tag should be used for each real preview.

## Use the local job queue and UI

The API adds a bounded FIFO queue in front of the same runner. It accepts one job at a time, binds only to `127.0.0.1`, requires a bearer token, and only accepts project-local JSON paths. Start it in PowerShell:

```powershell
.\.venv\Scripts\python.exe -m automation api
```

Open `http://127.0.0.1:8765/`. The first start creates `.state\api-token.json`; enter its token in the UI, choose portal and input JSON paths, and queue the run. The token stays in page memory. Do not expose the API to a network or enter its token into another site. The UI shows job status and the manifest path when the run finishes.

The API can also be called directly. `POST /jobs` submits a job, `GET /jobs/{id}` reports its status, and `GET /health` reports queue health. The pending queue is bounded (eight by default); when it is full, the API returns HTTP 429. This is a local single-worker queue, not a durable or horizontally scaled service.

## How the automation works

The authenticator provider computes a time-based code locally from the enrollment seed. The optional email provider polls a configured mailbox over TLS and accepts a fresh message only when its sender, subject, date, and code match. When GitHub clearly rejects a code, the runner allows one new-code attempt. It does not resubmit a code after an ambiguous network error; a second rejection or unsupported challenge fails safely.

To decide whether to reuse a saved session, the runner opens a private page in a separate tab and checks positive page markers plus the configured account identity. A login redirect is not the only signal: a private page that returns HTTP 200 with logged-out content still fails validation. Corrupt, malformed, wrong-origin, or expired state is discarded, a clean context is created, and login runs again. State is saved only after authentication is positively confirmed.

The locator resolver searches all current frames in this order:

1. Accessible role and exact name, because it reflects what a user sees and usually survives styling changes.
2. Associated form label, because labels express a control's purpose and survive wrapper or sibling changes.
3. Exact visible text and nearby field text, for markup with incomplete accessibility names.
4. Portal-specific structural relationships, for unusual but stable DOM relationships.
5. CSS selectors, as a last resort because IDs and classes often change during redesigns.

Every target has at least two locator descriptions. Multiple visible matches fail as ambiguous instead of selecting an arbitrary control. The offline command uses the same resolver with network access blocked. The mutation fixture renames classes, reorders siblings, adds a wrapper, and places fields in an iframe.

The project handles dependent form fields, nested frames, asynchronous controls, TOTP/email challenges, session expiration, native downloads, HTML print views, PDF printing, retries, and sanitized failure evidence. Transient timeouts, connection resets, HTTP 429/5xx responses, temporarily unavailable locators, and dropped IMAP connections can retry with bounded exponential backoff. A click or other side effect is not retried unless the portal explicitly marks it safe. Invalid configuration, ambiguous locators, authentication rejection, most 4xx responses, unsupported challenges, and invalid documents fail without repeated side effects.

For one hundred portals, the first changes should be versioned portal adapters, contract tests against consented and sanitized DOM captures, account-scoped secret/session isolation, structured health metrics, and per-portal rate limits and locking. The current queue serializes jobs and does not implement concurrent portals or proxy routing; those require account isolation, consent, operational controls, and separate validation.

## What to submit

Submit the Git repository at `https://github.com/ckiran24/live_automation`, including the tracked source, portal and input specifications, tests, scripts, README, validation record, and the two study PDFs. The tracked `examples/output/` files come from the disposable local fixture and are clearly labeled as fixture output. For a strong live-demo hand-in, add one reviewed successful GitHub manifest and its generated PDF under a clearly named `submission-artifacts/github-live/` folder if the assignment expects run artifacts. Those files are currently in the ignored local `runs/` directory and will not be pushed automatically.

Do not add `.env`, `.state/`, `.venv/`, or ignored `runs/` data. Live manifests and PDFs are on your computer and can contain account-related information; include one only if the evaluator requests it and you have reviewed it. The repository is already pushed to `main`; check `git status` before making your final submission.

Useful references: [VS Code setup](docs/VSCODE.md), [GitHub setup](docs/GITHUB_SETUP.md), and [validation evidence](docs/VALIDATION.md).
