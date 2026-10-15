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
| Real GitHub account | Public `shopping_bot` release page inspected; no releases existed | Read-only inspection passed; authenticated workflow unrun |
| GitHub login choice | User chose native GitHub password + TOTP after clarifying their current Google SSO flow | Default adapter updated; account enrollment and secure credentials pending |
| GitHub submission | Submission repository is `ckiran24/live_automation` | See Git history for the source revision |

The final complete unittest suite executed **9 tests**, all passed (70.497 seconds), including malformed cookie schema recovery and wrong-account identity rejection. The additional cookie-schema test first exposed a status-label bug; it was fixed and the complete suite rerun successfully. The generated CLI demonstration executed **9 scenarios**: 8 successful workflows and 1 expected intentional failure. The expected failure is a failure outcome with a bundle; it is not counted as a successful workflow.

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

Before submission, enable the chosen native GitHub password/TOTP flow and securely supply its credentials, run the full real-portal acceptance matrix, confirm the current release form dependency, and review the generated output. None of those live checks has been replaced by local tests.
