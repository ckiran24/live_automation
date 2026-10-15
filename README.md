**##Live-automation**
A Python/Playwright runner with automated email or TOTP codes, reusable browser state, semantic locator fallbacks, PDF/download capture, redacted failure evidence, and an authenticated localhost FIFO job API.

To run the downloaded project locally, follow [Download and run in VS Code](docs/VSCODE.md), including Windows and macOS/Linux commands and ready-to-use debugger configurations.

Clone and open the project from PowerShell:

```powershell
git clone https://github.com/ckiran24/live_automation.git
cd live_automation
code .
```

## One-command setup

Requires Python 3.11+ and Linux/macOS with Chromium dependencies installed:

```bash
bash scripts/setup.sh
```

This creates `.venv`, installs pinned dependencies from `requirements.lock`, and uses `BROWSER_EXECUTABLE`, system Chromium, or installs Playwright Chromium. A machine missing browser OS libraries can use Playwright's documented `python -m playwright install --with-deps chromium` with administrator access. TLS/checksum verification stays enabled.

Run the complete local demonstration with disposable credentials:

```bash
.venv/bin/python -m automation demo --output runs/demo
.venv/bin/python -m unittest discover -v
```

Use a fresh demo output path each time. Existing output is preserved. The demo runs the HTTP fixture in a background thread **inside the same process**; it needs no queue, database, or external server. Its temporary account and TOTP seed are synthetic. It demonstrates the mechanics, not the real-site requirement.

## Live GitHub run

First follow [GitHub authentication setup](docs/GITHUB_SETUP.md) to establish a native password and authenticator/TOTP enrollment. In PowerShell, copy `.env.example` to `.env` using `Copy-Item .env.example .env`, then enter the values in the new file. The CLI loads the project-root `.env` automatically without displaying its contents. Alternatively, supply process environment variables through a password manager or runtime. Do not put secret values in JSON, screenshots, Git, or chat.

| Variable | Purpose |
| --- | --- |
| `PORTAL_USERNAME` | Your GitHub username |
| `PORTAL_PASSWORD` | Your native GitHub password |
| `PORTAL_TOTP_SECRET` | Base32 enrollment seed for your GitHub authenticator (not the changing code) |
| `BROWSER_EXECUTABLE` | Optional Chromium executable override |

The TOTP seed must be available to the Python process. An HTTPS proxy substitution placeholder is not a usable authenticator seed. If your cloud settings only support destination-bound proxy secrets, run this workflow locally with your password manager rather than pasting credentials into chat.

Check which required settings are present and whether the TOTP seed is valid without displaying any values:

```powershell
.\.venv\Scripts\python.exe -m automation check-config
```

On macOS/Linux use `.venv/bin/python -m automation check-config`.

The optional `portals/github-email.json` adapter uses native GitHub password login followed by email device verification. It does not implement Google SSO. For that optional mode:

| Variable | Purpose |
| --- | --- |
| `IMAP_HOST` | Mail provider's TLS IMAP hostname |
| `IMAP_USERNAME` | Mailbox login receiving this account's GitHub codes |
| `IMAP_PASSWORD` | Mail-provider app password, when supported |
| `IMAP_ACCESS_TOKEN` | Alternative short-lived OAuth access token for XOAUTH2 |
| `IMAP_SENDER` | Expected exact sender address, usually `noreply@github.com`; confirm from your email |
| `IMAP_SUBJECT` | Subject substring; default `GitHub` |
| `IMAP_FOLDER` | Folder to poll; default `INBOX` |
| `IMAP_CODE_PATTERN` | Regex with one capture group; default `(?<!\d)(\d{6,8})(?!\d)` |
| `IMAP_TIMEOUT_SECONDS` | Total polling budget, default 90, maximum 300 |
| `IMAP_POLL_SECONDS` | Poll interval, default 3 |
| `BROWSER_EXECUTABLE` | Optional Chromium executable override |

Enable IMAP and use an app password or an OAuth token according to your mail provider. Do not weaken mailbox security to enable ordinary password login. TLS certificates are verified. IMAP uses TLS port 993 and needs an actual credential in the local process. An HTTPS-only proxy secret placeholder **cannot** authenticate a raw IMAP socket; configure this in a suitable runtime or run locally. GitHub requires HTTPS access to `github.com` and its page assets, commonly `github.githubassets.com` and `avatars.githubusercontent.com`; the mailbox needs its actual provider hostname. This environment has package-manager/GitHub access but no mailbox credentials.

```bash
.venv/bin/python -m automation run \
  --portal portals/github.json \
  --inputs examples/inputs.github.json
```

Run the same command again to reuse `.state/github.json`. To generate a different PDF without changing code:

```bash
.venv/bin/python -m automation run \
  --portal portals/github.json \
  --inputs examples/inputs.github.alternate.json
```

`--headed` is available on a machine with a display. `--state` chooses a session path; `--output` chooses a fresh run directory. Exit codes: 0 success, 1 runtime failure with manifest/evidence, 2 invalid setup/configuration before execution, 130 interrupted. Concurrent invocations must use different state/output paths; the intended shape is one sequential CLI process.

The live path is private profile → repository → releases → new release. The form contains tag, target branch, title, and notes. A **new, non-existing tag choice makes the target branch relevant**; use a unique tag in the input. Selecting that tag in the form does not create it on GitHub until publishing. The runner renders the Markdown preview and prints the page using Chromium. It never clicks Publish or Save draft. Your `shopping_bot` repository is not modified. A successful live preview run has been reported; the remaining real-account acceptance matrix is listed in [validation status](docs/VALIDATION.md). An already existing tag, GitHub UI change, email challenge variation, CAPTCHA, passkey prompt, or account-policy requirement can require adapting `portals/github.json` and revalidating the live flow.

To execute the real-account acceptance matrix on Windows, use the PowerShell script below after `.env` is configured. It performs a fresh login, a reused-session run, corrupt-state recovery, and an alternate-input run. It stores its test session under `.state\acceptance\` and outputs manifests/PDFs under a new `runs\live-acceptance-*` folder; your regular `.state\github.json` is untouched. Add `-Headed` to watch the browser.

```powershell
.\scripts\test-live.ps1
# or
.\scripts\test-live.ps1 -Headed
```

## Local FIFO job API (extra credit)

The optional API places a bounded queue in front of the same runner. It binds only to `127.0.0.1`, accepts only project-local JSON portal/input paths, requires a bearer token, and runs one job at a time so jobs cannot race over the API's saved browser session. It uses separate `.state\api-<portal>.json` state files from the CLI. No web framework or additional package is required. Start it in one PowerShell terminal:

```powershell
.\.venv\Scripts\python.exe -m automation api
```

The first start creates the private, Git-ignored `.state\api-token.json`. In a second terminal, submit and poll a job:

```powershell
$token = (Get-Content .\.state\api-token.json -Raw | ConvertFrom-Json).token
$headers = @{ Authorization = "Bearer $token" }
$body = @{ portal = "portals/github.json"; inputs = "examples/inputs.github.json"; headed = $true } | ConvertTo-Json
$job = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8765/jobs -Headers $headers -ContentType "application/json" -Body $body
do {
    Start-Sleep -Seconds 1
    $result = Invoke-RestMethod -Uri "http://127.0.0.1:8765/jobs/$($job.id)" -Headers $headers
} while ($result.status -in @("queued", "running"))
$result
```

`POST /jobs` returns a job ID, `GET /jobs/{id}` returns status and the eventual manifest path, and `GET /health` reports queue health. The pending queue is bounded (default 8; change with `--max-queued`); a full queue returns HTTP 429. Stop the service with Ctrl+C. Keep the token file private and do not bind the service to a LAN address.

The default adapter requires an actual TOTP challenge. GitHub email verification commonly confirms a new device and is **not GitHub account-level 2FA**. Do not claim account-level 2FA based on an email device code. The optional email adapter fails if no email challenge appears. The native adapter stops on an unexpected Google SSO origin before filling credentials.

## How the code works

1. `automation/__main__.py` parses the CLI and selects a real run, offline resolver check, or local demonstration.
2. `config.py` loads a portal JSON and a separate business-input JSON. It substitutes only literal `{{inputs.key}}` and `{{env.NAME}}` tokens, with no Python evaluation. `models.py` validates the action shapes, HTTPS origin, bounded timeouts/retries, and locator descriptions. Business changes belong in input JSON; portal UI changes belong in the portal specification.
3. `runner.py` creates a fresh output directory and Chromium context. It loads a versioned storage-state envelope only for the configured origin. Invalid JSON/schema/cookies are discarded; a readable file is not treated as a valid login.
4. `authenticated()` opens a private page in a separate tab and checks at least **two positive authenticated-page markers**. GitHub additionally checks that the personal-profile link points to the configured username. The fixture also checks an authenticated JSON endpoint. A private URL returning HTTP 200 with an expired-session message still fails. Network/server errors retry instead of being misclassified as logout.
5. If the state is dead, a fresh context removes both cookies and localStorage. The runner enters username/password, waits for the configured challenge, calls `await provider.get_code(challenge)`, fills it, and verifies the authenticated page again. It saves `context.storage_state()` only after successful validation. Rotated state is refreshed at the end. State is sensitive, excluded from Git, written atomically with mode 0600, and should be stored on encrypted disk. SessionStorage-only portals need a separate adapter.
6. The sequential action engine visits pages, fills/selects fields, waits for dependent controls, and captures a download, an HTML popup printed to PDF, or the current page printed to PDF. Captures have explicit safe basenames, non-empty content, PDF magic validation, byte counts, and SHA-256 hashes. It does not use a server-provided filename as a filesystem path. A popup showing a browser PDF viewer needs a native-download adapter; `popup_pdf` is for HTML print views.
7. `manifest.json` records redacted business inputs, main-page/popup visits, elapsed time per stage and attempt, retry backoff, whether the session was reused, every resolver strategy attempted, and captured-file metadata. Configuration failures before a browser exists return a safe diagnostic class; browser-stage failures also produce a failure bundle.

### How the email code arrives and what happens when it is wrong

`otp.py` defines the interface `async def get_code(challenge) -> str`. `IMAPProvider` runs blocking TLS IMAP work using `asyncio.to_thread`, polls only the chosen mailbox in read-only mode, searches the challenge date, and fetches the newest 50 matching-day messages with `BODY.PEEK[]` (does not mark them read). It accepts a message only when sender and subject match and its Date is within the challenge window (30 seconds of clock skew). Plain text is preferred over HTML. Exactly one distinct code must match the regex; ambiguous messages are ignored. Already-consumed message UIDs and the previous rejected code are excluded.

A clearly rejected code gets exactly **one** retry. If the adapter defines a resend control, it requests a fresh email before polling again. A second rejection is final. A timeout, invalid mailbox credentials, TLS verification failure, missing challenge, or unsupported account prompt is not silently bypassed. Network failures during code submission are not blindly resubmitted. Codes and credentials are never emitted to logs. Keep the host clock synchronized; only email header timestamps are checked, so a provider-specific inbox integration is preferable for stronger delivery/provenance guarantees.

`TOTPProvider` is the default real implementation using PyOTP/RFC 6238. `portals/github.json` selects it and defines the GitHub challenge locators. Supply `PORTAL_TOTP_SECRET` (the existing Base32 authenticator seed). It avoids near-expiry codes and waits for the next 30-second window after rejection. The seed never belongs in input JSON. A six-digit OTP is not an enrollment seed.

### Locator strategy order and offline operation

`resolver.py` tries these strategies in order, across **all current frames**, including nested iframes:

1. Exact accessible role and name: closest to how a user identifies the control.
2. Associated label: survives layout, wrappers, and class changes.
3. Exact visible text, then nearby text in a label/fieldset/field block.
4. Structural relationship supplied by the portal adapter.
5. ID/class CSS alternatives as the final fallback.

Each target must describe at least two strategies. The resolver records target key, strategy, frame index, and match/miss/selected/ambiguous outcome. It waits within a bounded deadline for asynchronously loaded controls and frames. Multiple visible matches fail explicitly; it never chooses `.first` arbitrarily. A semantic match anywhere in the frame tree wins before a weaker main-frame CSS match.

```bash
.venv/bin/python -m automation offline \
  --html examples/saved-form.html --targets examples/targets.json
.venv/bin/python scripts/mutate_html.py examples/saved-form.html /tmp/mutated-form.html
.venv/bin/python -m automation offline \
  --html /tmp/mutated-form.html --targets examples/targets.json
```

The mutation command renames classes, reverses field siblings, adds a wrapper and moves the form into an iframe. The offline command uses the **same resolver** as production, disables JavaScript/service workers and aborts all network requests. Saved iframe HTML must use `srcdoc`, because remote frame contents cannot be reconstructed offline. The checked-in fixture is intentionally non-sensitive; failure HTML is aggressively redacted and is not a resolver replay fixture.

### Quirks, retries, and evidence

The fixture exercises iframe traversal, dependent category→order selection, a native download, a new-tab HTML print view, and current-page print-to-PDF. The GitHub adapter uses its dependent tag→target-branch form and print-to-PDF. A live run has completed successfully with a reused session and captured the release preview PDF; see [validation status](docs/VALIDATION.md) for the remaining live acceptance checks.

Transient navigation resets, connection/timeouts, HTTP 429/5xx, temporarily missing locators, and dropped IMAP connections may retry. A safe action gets at most `attempts` tries (default 3, maximum 5), with exponential backoff. Fill/select/wait are idempotent; safe navigation opts in. Clicks, downloads, OTP submissions, and other potentially repeated side effects **do not retry automatically** unless the adapter explicitly marks them safe. Authentication rejection, ambiguous targets, invalid inputs/configuration, HTTP 4xx other than 429, unsupported challenges, invalid documents, and exhausted retries are final. There is no anti-bot bypass; use another permitted portal if GitHub blocks automation.

On final browser-stage failure, `failure/` contains `evidence.json` (stage, error class, URL origin with masked path, console events, resolver attempts), `page.html`, and `screenshot.png` when the browser/page is available. Browser console messages may contain unknown identifiers, so only event type is retained. Evidence HTML retains structural tags but masks **all** page-controlled text/attributes and removes scripts, images, SVG, canvas, and embedded frames. The screenshot is taken from an inert, network-blocked sanitized copy, not a raw account page. This intentionally trades visual detail for reliable identifier redaction. Resolver history still identifies the missing control and strategy. If the browser crashes before capture, the JSON records a capture error; no fake screenshot is generated.

Manifests redact registered environment credentials, configured sensitive input values (including the GitHub owner), emails, and URL query values. Raw exception strings are not persisted because Playwright call logs can quote field values. Final run output contains a status and manifest path only. Downloaded documents are private account data, stored mode 0600 under ignored `runs/`; failure evidence and disposable fixture examples are the only artifacts intended for sharing.

### What I would change first for a hundred portals

Keep the runner and code-provider interface, but replace large hand-written JSON workflows with versioned portal adapters and contract tests based on consented, sanitized DOM captures. Separate authentication from document workflows, add scoped credential/session storage per account and origin, and record structured health metrics so UI changes are detectable. Only after that add a bounded worker queue, per-portal rate limits, cancellation and account-level locking. Avoid building proxy/fingerprint/CAPTCHA infrastructure before the five core requirements work.

## Submission artifacts and remaining validation

`examples/output/` contains genuine **local fixture** outputs: successful download/PDF, first/reused-session manifests, a deliberately broken-step failure bundle, and an acceptance summary. A user-reported successful live GitHub run is recorded in `docs/VALIDATION.md`; its private run directory is local to the user's Windows machine and has not been copied into this repository.

Before submission, complete the live fresh-login, stale-session recovery, and changed-input checks listed in `docs/VALIDATION.md`. Include the reviewed successful live manifest/PDF and one sanitized failure bundle in the submission artifacts. Do not submit `.env`, `.state/`, or unreviewed account data. The local fixture cannot substitute for missing live checks. The submission repository is `https://github.com/ckiran24/live_automation`.
