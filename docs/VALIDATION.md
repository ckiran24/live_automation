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
| Real GitHub workflow | User reported successful run `runs\\20261015T144734Z-4ff2a107`; manifest status `success`, `session_reused: true` | Passed once with reused session; printed release-preview PDF recorded as `documents\\shopping-bot-release-preview.pdf` (105,824 bytes). Run output is on the user's Windows machine, not copied into this repository |
| GitHub fresh login | Earlier fresh-login attempt reached the release form after password/TOTP; it failed on selectors before the later successful reused-session run | Login was observed working, but a complete successful fresh-login-to-PDF run remains unverified |
| GitHub stale-session recovery | Not yet run on the live account after the successful workflow | Pending |
| GitHub changed input | Fixture test produces a different PDF when inputs change; the live alternate input has not yet been run | Passed locally; live check pending |
| GitHub release form | User confirmed current Tag → Create new tag dialog; later successful run captured its preview | Passed for tag selection, release preview, and print-to-PDF in the reported live run |
| GitHub login choice | User chose native GitHub password + TOTP after clarifying their current Google SSO flow | TOTP submission succeeded during live login; complete fresh-login workflow still needs one successful end-to-end run |
| GitHub submission | Submission repository is `ckiran24/live_automation` | See Git history for the source revision |

The final complete unittest suite executed **11 tests**, all passed (89.752 seconds), including malformed cookie schema recovery, wrong-account identity rejection, automatic second-factor submission, and the current GitHub tag dialog locators. The generated CLI demonstration executed **9 scenarios**: 8 successful workflows and 1 expected intentional failure. The expected failure is a failure outcome with a bundle; it is not counted as a successful workflow.

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

Remaining live acceptance work: run once after deleting `.state/github.json` and confirm a successful full password/TOTP login through PDF capture; run again and retain the reused-session manifest; corrupt a backup of the saved state and confirm automatic full-login recovery; use `examples/inputs.github.alternate.json` and confirm a different PDF without code changes. The successful reused-session run and current tag-dialog interaction are confirmed by the user, but its manifest/PDF remain on the user's machine. Copy a deliberately reviewed success manifest/PDF and a sanitized failure bundle into the submission artifacts. Never include `.env` or `.state/`.
