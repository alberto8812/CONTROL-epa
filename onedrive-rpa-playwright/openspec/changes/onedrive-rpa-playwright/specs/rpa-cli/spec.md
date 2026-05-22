# rpa-cli Specification

## Purpose

Command-line entry point that orchestrates authentication and folder cleaning. Exposes all operational flags and enforces safety confirmations before destructive runs.

## Requirements

### Requirement: Mode Selection

The CLI MUST accept a `--mode` flag with values `manual` and `auto`. If omitted, the system MUST default to `auto`. The selected mode MUST be forwarded to the session management layer.

#### Scenario: Explicit auto mode — happy path

- GIVEN a valid `session.json` and no `--mode` flag
- WHEN the CLI is invoked
- THEN the system runs in headless auto mode

#### Scenario: Explicit manual mode

- GIVEN the `--mode manual` flag is passed
- WHEN the CLI is invoked
- THEN a visible browser opens for interactive login

### Requirement: Confirmation Gate

Before executing any destructive run (not dry-run), the system MUST print a summary of folders to be cleaned and the number of files found, then prompt for explicit confirmation. The `--yes` flag MUST skip this prompt.

#### Scenario: Interactive confirmation accepted

- GIVEN a real (non dry-run) run without `--yes`
- WHEN the summary is displayed
- AND the user types "y" or "yes"
- THEN the deletion run proceeds

#### Scenario: Interactive confirmation rejected

- GIVEN a real run without `--yes`
- WHEN the user types anything other than "y" / "yes"
- THEN the system exits with code `0` and no files are deleted

#### Scenario: Skip confirmation with --yes

- GIVEN `--yes` is passed
- WHEN the CLI is invoked for a destructive run
- THEN the confirmation prompt is skipped and deletion proceeds immediately

### Requirement: Config File Loading

The CLI MUST read target folder paths from a `--config` file (default: `folders.json`). If the file is missing or malformed (invalid JSON, empty array), the system MUST exit with code `1` and a descriptive error.

#### Scenario: Valid config loaded

- GIVEN a well-formed `folders.json` with at least one path
- WHEN the CLI starts
- THEN all listed folders are queued for processing

#### Scenario: Config file not found

- GIVEN `--config` points to a non-existent file
- WHEN the CLI starts
- THEN the system exits with code `1` and prints the path that was not found

### Requirement: Dry-Run Flag

The CLI MUST propagate `--dry-run` to the cleaner layer. A dry-run MUST NOT require confirmation and MUST NOT modify any files.

#### Scenario: Dry-run skips confirmation

- GIVEN `--dry-run` is active
- WHEN the CLI is invoked
- THEN no confirmation prompt is shown
- AND the cleaner operates in read-only mode
