# Validation evidence

These checks were executed in the cloud workspace on 15 October 2026. The browser was system Chromium 154.0.8037.57, with Python 3.12 and Playwright 1.62.0. All account credentials in the local portal are disposable synthetic data.

| Requirement/check | Evidence | Status |
| --- | --- | --- |
| Reproducible setup | `bash scripts/setup.sh`; pinned packages; `pip check`; browser version | Passed in this instance, including repeat setup |
| Automated second factor | Local HTTP portal validates real RFC 6238 TOTP; provider called asynchronously | Passed locally |
| Wrong code retry limit | Browser test sends one wrong code then a valid one; second case sends two wrong codes | Passed; exactly two submissions maximum |
| Email provider | Fresh message, sender/subject/date filtering, ambiguity rejection, previous-code rejection, bounded polling | Passed with synthetic MIME messages and mocked transport; real Gmail connection unrun |
| Session reuse | Second browser context uses saved cookies with no login navigation | Passed locally |
| Corrupt state | Broken JSON forces full login | Passed locally |
| Dead session beyond redirect | Server invalidates valid stored cookies; private page returns HTTP 200 with logged-out content | Passed; full login recovers |
| Nested form | Account → Workspace → Documents → Reports, embedded form | Passed locally |
| Three fields and dependency | Category, order, statement date; category enables and populates order | Passed locally |
| Changed JSON/data | Books/Book A and Devices/Device B produce distinct PDF content/hashes | Passed locally |
| Quirks and captures | Iframe, dependent field, download, popup HTML print view, current-page PDF | Passed locally |
| Manifest | Business inputs/date, visited pages, timings, strategies, captured-file sizes/hashes | Present in recorded output |
| Locator mutations | Renamed classes, reordered siblings, wrapper and iframe; same production resolver | Passed with network blocked |
| Locator fallbacks | Role, label, nearby text, structure, CSS; ambiguous matches fail | Passed offline |
| Retry classification | One HTTP 503 recovers with recorded backoff; unsafe capture click does not repeat | Passed locally |
| Failure evidence | Intentionally absent download control | HTML, sanitized screenshot, stage/URL/console/strategy JSON written |
| Redaction | Secret/identity checks in HTML/JSON; screenshot visually inspected | Passed for synthetic fixture; all page-controlled evidence text masked |
| Real GitHub workflow | User's live acceptance run `runs\\live-acceptance-20261015T210051-d64414` | Passed fresh login, reuse, corrupted-state recovery, and alternate input; its private PDFs/manifests remain on the user's Windows machine |
| GitHub fresh login | Acceptance case `01-fresh-login`; state `missing`, `session_reused: false`, `full_login: true`, PDF captured | Passed live |
| GitHub session reuse | Acceptance case `02-reused-session`; state `loaded`, `session_reused: true`, `full_login: false`, same inputs, PDF captured | Passed live and faster than fresh run. PDF hashes differ because Chromium may add varying metadata, so byte-identical output is not asserted |
| GitHub corrupted-state recovery | Acceptance case `03-corrupt-state-recovery`; state `corrupt`, `session_reused: false`, `full_login: true`, PDF captured | Passed live |
| GitHub changed input | Acceptance case `04-changed-input`; alternate JSON values and filename, saved session reused, PDF captured | Passed live; user confirmed the generated outputs work |
| Live acceptance script | `scripts/test-live.ps1` ran the above four cases using separate state and output paths | Passed on Windows; artifacts are under the user's ignored `runs/live-acceptance-*` folder |
| GitHub release form | User confirmed current Tag → Create new tag dialog; later successful run captured its preview | Passed for tag selection, release preview, and print-to-PDF in the reported live run |
| GitHub login choice | User chose native GitHub password + TOTP after clarifying their current Google SSO flow | TOTP and complete fresh-login workflow passed live |
| Extra credit: local job API | Authenticated HTTP submission, project-path restriction, queue-full response, and an API-queued fixture workflow that captures a PDF | Passed locally; loopback-only FIFO API has no additional dependencies |
| Extra credit: browser UI | UI submits portal/input paths to the authenticated queue and polls job status | Passed in a headless Chromium smoke test against a fixture job; served only from the loopback API |
| GitHub submission | Submission repository is `ckiran24/live_automation` | See Git history for the source revision |

The final complete unittest suite executed **17 tests**, all passed (98.159 seconds), including malformed cookie schema recovery, wrong-account identity rejection, automatic second-factor submission, current GitHub tag dialog locators, authenticated API queue submission through fixture PDF capture, and browser UI job submission/status tracking. The generated CLI demonstration executed **9 scenarios**: 8 successful workflows and 1 expected intentional failure. The expected failure is a failure outcome with a bundle; it is not counted as a successful workflow.

The demonstration's first run took 4134.82 ms and its reused-session run took 2721.68 ms in the recorded sample. Browser startup and concurrent test load dominate these small cases; speed is not an asserted timing threshold. The functional reuse assertion checks that no login occurred.

Reproduce:

```bash
bash scripts/setup.sh
.venv/bin/python -m unittest discover -v
.venv/bin/python -m automation demo --output runs/fresh-acceptance
.venv/bin/python -m automation offline --html examples/saved-form.html --targets examples/targets.json
.venv/bin/python scripts/mutate_html.py examples/saved-form.html /tmp/mutated-form.html
.venv/bin/python -m automation offline --html /tmp/mutated-form.html --targets examples/targets.json
```

`examples/output/summary.json` is the actual fixture scenario summary. Example manifests and PDF are under `01-first-login` and `02-reuse`; the intentional bundle is under `06-intentional-failure/failure`. These artifacts are not a real GitHub run and must not be represented as one.

The live four-case acceptance matrix passed on the user's machine. The script saves its separate session and output under ignored `.state/acceptance/` and `runs/live-acceptance-*`. Review those PDFs/manifests before submission; never include `.env` or `.state/`.
