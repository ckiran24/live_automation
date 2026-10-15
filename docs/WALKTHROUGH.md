# Trace one document from input to output

This short walkthrough is now kept in sync with the current implementation. For the full module-by-module explanations, tradeoffs, security model, and test coverage, read the [Project Study Guide](PROJECT_STUDY_GUIDE.pdf) or its [Markdown source](PROJECT_STUDY_GUIDE.md).

1. `automation/__main__.py` parses the command and loads the project-root `.env`. `config.load_config()` reads `portals/github.json` and `examples/inputs.github.json`, substitutes only named input/environment tokens, and validates the result with Pydantic models.
2. `Runner.run()` creates a fresh output directory and Chromium context. If saved state exists, it validates its shape and origin, then probes GitHub's private profile page for positive markers and the configured account identity. A 200 response alone does not prove the session is alive.
3. Missing, corrupt, or expired state uses a clean context and the configured password/TOTP flow. TOTP is generated locally from the enrollment seed. State is saved only after the runner confirms authenticated private-page content.
4. The runner executes the portal steps in order. `Resolver` searches each current frame using accessible role/name, label, text, structural and CSS descriptions. GitHub's adapter opens the repository's release form, creates/selects the new tag choice, fills release data, waits for the preview and prints it to PDF.
5. The output directory receives a manifest and PDF. The manifest records redacted inputs, session decision, pages, stage timings, locator outcomes, file size/hash, and final status. If a step fails, it also records a sanitized failure bundle.

The local API and browser UI call the same `Runner` through a bounded one-worker queue. The UI is loopback-only and intended for local demonstration, not as a public service. The live GitHub acceptance run has passed; its private artifacts remain on the user's Windows machine.

To follow the code in order, see [the study guide](PROJECT_STUDY_GUIDE.md). To practice explaining the decisions in an interview, see [the CTO final-round Q&A](CTO_FINAL_ROUND_QA.pdf).
