# Configure your real GitHub account

You selected native GitHub password + TOTP for this assignment. Your existing **Continue with Google** session can be used to configure your account; the automation will subsequently use GitHub's native login form. This document does not claim the account has already been configured.

1. While signed into GitHub, open **Settings → Password and authentication**. Establish or reset a native GitHub password if the account does not already have one. Use GitHub's own password/reset flow; a Google password is not a GitHub password.
2. Under two-factor authentication, set up an authenticator app. Follow [GitHub's official TOTP instructions](https://docs.github.com/en/authentication/securing-your-account-with-two-factor-authentication-2fa/configuring-two-factor-authentication).
3. During enrollment, use GitHub's text/manual setup option to retain the **Base32 enrollment secret** in your password manager. Your authenticator app and this runner use the same seed to compute time-based codes. Do not send the seed, QR image, recovery codes, or live OTP to chat. Do not turn off existing security just to extract a seed; use a supported app export or GitHub's supported authenticator reconfiguration flow if necessary.
4. Finish enrollment using the code from your authenticator app, and save the recovery codes privately. The runner never uses recovery codes.
5. Make `PORTAL_USERNAME`, `PORTAL_PASSWORD`, and `PORTAL_TOTP_SECRET` available as actual environment values to the Python process. Use a password manager's process environment integration if available. A local `.env` file may be used with a trusted environment loader; it is ignored by Git and should be mode 0600. This program does not load it automatically. An HTTPS proxy-secret placeholder cannot be decoded by PyOTP, so choose a runtime supporting actual private environment values or run locally.
6. Verify in your own browser that native GitHub login now asks for your password and then the authenticator code. Tell the agent only that setup is complete; no secret value is needed in chat.

Run from the repository root:

```bash
bash scripts/setup.sh
.venv/bin/python -m automation run --portal portals/github.json --inputs examples/inputs.github.json
```

The JSON input points to `ckiran24/shopping_bot`, which you selected. Use a unique tag name that does not already exist. The form is filled and printed to PDF; no release or tag is published, and no draft is saved.

Re-run the same command to check saved-session reuse. For a stale-state check, back up the ignored state privately and replace it with invalid JSON, or revoke only that browser session through your account's session settings. Do not revoke unrelated sessions. The next run should perform full password/TOTP login and overwrite state only after authentication succeeds.

Change to `examples/inputs.github.alternate.json` for a different release-preview document. Inspect the manifest's `session`, `stages`, `pages_visited`, and `captured_files` to see exactly which path occurred. Do not publish raw session files or real account PDFs in the submission without reviewing their contents.
