# Trace one document from input to output

Start with `examples/inputs.github.json`. `owner` and `repository` identify the target, `tag` and `branch` determine the release target, `title` and `notes` become form values, and `filename` determines the local capture basename. Change this JSON to request another preview. Authentication data comes from the process environment separately.

`python -m automation run --portal portals/github.json --inputs examples/inputs.github.json` enters `automation/__main__.py`. `load_config()` reads both files and substitutes only named tokens in the portal specification. For example, `/{{inputs.owner}}/{{inputs.repository}}` becomes the repository route. This is literal substitution, not executable interpolation. Pydantic rejects unknown fields and malformed action/target definitions before opening the browser.

`Runner.run()` creates the output directory, launches Chromium and reads `.state/github.json`. The file is an envelope with `version`, `origin`, and Playwright `storage_state`. Cookies and localStorage are restored into a new browser context. Nothing about a readable file proves that GitHub still accepts the session.

`authenticated()` opens `/settings/profile` in a separate tab. It resolves the private profile heading and update button, then checks the profile link's `href` against the configured username. Missing private content or the wrong account means the session is invalid. A server/network error raises a retryable failure instead of triggering login. The separate tab means this check cannot destroy an in-progress email challenge.

If invalid, the runner discards the old context, opens the login page, and runs `login.steps`. The default GitHub adapter uses the native username/password login followed by the authenticator/TOTP challenge, as selected by the user. It does not implement the user's previous **Continue with Google** route. An unexpected SSO origin stops before credentials are filled. Native account enrollment, secure credential injection, and live validation are pending.

When the challenge control exists, `get_code()` receives a `Challenge` containing the attempt number, previous rejected code, and challenge start time. The email provider scans a fresh window of the configured mailbox. The TOTP provider instead computes an authenticator code locally. The caller fills the code and submits it. A rejection allows one new-code attempt; success requires another positive private-page check. Only then is storage state written atomically.

The workflow then walks through `portal.steps`. A `goto` navigates within the configured origin. A `click`, `fill`, `select`, or `wait` asks the resolver for its target. The resolver searches all frames by semantic role/name first, then label, text/nearby text, structural relationship and CSS alternatives. It returns exactly one visible match or raises a classified error. The same function runs against saved HTML in `offline` mode.

The GitHub configuration opens the repository, releases and new-release form, chooses a new tag and its target branch, fills the title/notes, opens the Markdown preview, and calls Chromium's `page.pdf()`. It does not publish. The generic engine can also listen for a Playwright download event or wait for a popup and print its HTML. Files are checked for non-empty content and a PDF header when applicable, then hashed and recorded.

Every stage records its elapsed milliseconds and attempt outcome. Safe transient failures use exponential backoff; side-effecting actions do not repeat implicitly. A failure captures an aggressively sanitized page copy, renders its screenshot with scripts/network disabled, and writes diagnostics. Raw browser text and raw exception strings never enter the persisted logs. Successful account documents remain private; only the failure bundle is designed to be shareable.

Finally, `manifest.json` records the input, session decision, visited pages, stage attempts, locator history, file paths/sizes/hashes and success/failure. The CLI prints that manifest's location and returns an exit code suitable for a shell script. There is no separate job service: the caller runs one process and waits for it.

To see all of this without account setup, run the `demo` command. Its in-process HTTP server implements a real TOTP check and revocable sessions; its embedded report form has category, dependent order, and date fields. The local portal validates the runner's mechanics while the chosen real GitHub route awaits secure account validation.
