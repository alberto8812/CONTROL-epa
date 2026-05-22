# onedrive-session-management Specification

## Purpose

Capture, persist, and reuse an authenticated Playwright browser session against OneDrive for Business. Eliminates repeated interactive logins by serialising cookies and storage state to disk.

## Requirements

### Requirement: Session Capture on Manual Login

The system MUST launch a visible Chromium browser, navigate to the configured OneDrive URL, and wait for the user to complete login (including MFA). Upon browser close, the system MUST serialise the full storage state (cookies + localStorage) to `session.json`.

#### Scenario: First-time login — happy path

- GIVEN no `session.json` exists on disk
- WHEN the user runs the CLI with `--mode manual`
- THEN a visible browser opens at the OneDrive URL
- AND after the user closes the browser, `session.json` is written to the configured path

#### Scenario: Login interrupted by user

- GIVEN no `session.json` exists
- WHEN the user closes the browser before completing login
- THEN the system MUST NOT write a partial `session.json`
- AND the system MUST exit with a non-zero code and an explanatory message

### Requirement: Session Reuse in Auto Mode

The system MUST load `session.json` as the browser context storage state when running in `--mode auto`. If `session.json` does not exist, the system MUST abort with exit code `1` and a message instructing the user to run `--mode manual` first.

#### Scenario: Valid session reused — happy path

- GIVEN a valid `session.json` exists
- WHEN the system runs in `--mode auto`
- THEN the headless browser starts authenticated without prompting for credentials

#### Scenario: Missing session file

- GIVEN `session.json` does not exist
- WHEN the system starts in `--mode auto`
- THEN the system exits with code `1` and prints "Run with --mode manual first to create a session."

### Requirement: Expired Session Detection

In `--mode auto`, the system MUST detect when OneDrive redirects to the Microsoft login page (session expiry). Upon detection, the system MUST abort with exit code `1` and a message instructing the user to re-authenticate with `--relogin`.

#### Scenario: Session expired mid-run

- GIVEN a `session.json` that has expired
- WHEN the system navigates to a OneDrive folder
- THEN a redirect to `login.microsoftonline.com` is detected
- AND the system exits with code `1` and prints "Session expired. Run with --relogin to re-authenticate."

### Requirement: Force Re-login

The system MUST support a `--relogin` flag that deletes any existing `session.json` and restarts the manual login flow.

#### Scenario: Re-login requested

- GIVEN a stale `session.json` exists
- WHEN the user runs with `--relogin`
- THEN the existing `session.json` is deleted before the browser launches
- AND the manual login flow executes as in the first-time scenario
