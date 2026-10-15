# Configure your real GitHub account

This project uses native GitHub password + authenticator-app TOTP. If an account currently uses **Continue with Google**, that is a separate sign-in path; this adapter expects GitHub's native login form and stops safely if redirected to Google SSO.

1. While signed into GitHub, open **Settings → Password and authentication**. Establish or reset a native GitHub password if the account does not already have one. Use GitHub's own password/reset flow; a Google password is not a GitHub password.
2. Under two-factor authentication, set up an authenticator app. Follow [GitHub's official TOTP instructions](https://docs.github.com/en/authentication/securing-your-account-with-two-factor-authentication-2fa/configuring-two-factor-authentication).
3. During enrollment, use GitHub's text/manual setup option to retain the **Base32 enrollment secret** in your password manager. Your authenticator app and this runner use the same seed to compute time-based codes. Do not send the seed, QR image, recovery codes, or live OTP to chat. Do not turn off existing security just to extract a seed; use a supported app export or GitHub's supported authenticator reconfiguration flow if necessary.
4. Finish enrollment using the code from your authenticator app, and save the recovery codes privately. The runner never uses recovery codes.
5. In PowerShell, copy `.env.example` to `.env` with `Copy-Item .env.example .env`, open `.env` in VS Code, and set `PORTAL_USERNAME`, `PORTAL_PASSWORD`, and `PORTAL_TOTP_SECRET`. The CLI loads the file automatically; `.gitignore` excludes it. You can also supply these values through a password manager or process environment. An HTTPS proxy-secret placeholder cannot be decoded by PyOTP.
6. Verify in your own browser that native GitHub login now asks for your password and then the authenticator code. Do not share the password, seed, QR code, recovery codes, or live OTP.

Check that the required settings exist and the TOTP seed is valid. This prints missing variable names only, never their values:

```powershell
.\.venv\Scripts\python.exe -m automation check-config
```

Run the automation from the repository root:

```bash
bash scripts/setup.sh
.venv/bin/python -m automation run --portal portals/github.json --inputs examples/inputs.github.json
```

The JSON input points to `ckiran24/shopping_bot`, which you selected. Use a unique tag name that does not already exist. The form is filled and printed to PDF; the release is not published and no draft is saved. The live acceptance matrix has passed for this account; see `VALIDATION.md` for evidence and limitations.

Re-run the same command to check saved-session reuse. For a stale-state check, back up the ignored state privately and replace it with invalid JSON, or revoke only that browser session through your account's session settings. Do not revoke unrelated sessions. The next run should perform full password/TOTP login and overwrite state only after authentication succeeds.

Change to `examples/inputs.github.alternate.json` for a different release-preview document. Inspect the manifest's `session`, `stages`, `pages_visited`, and `captured_files` to see exactly which path occurred. Do not publish raw session files or real account PDFs in the submission without reviewing their contents.
