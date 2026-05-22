# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project does

Python RPA that automates file deletion in OneDrive via Playwright (Chromium). Recursively deletes all files inside configured folders while keeping the folder structure intact. Ships a real-time Rich TUI.

## Setup

```bash
cd onedrive_rpa
pip install -r requirements.txt
playwright install chromium
cp env.example .env   # then fill ONEDRIVE_USERNAME and ONEDRIVE_PASSWORD
```

## Running

All commands run from inside `onedrive_rpa/` or as a module from the repo root.

```bash
# Dry-run first — always
python main.py --mode manual --dry-run

# Real run (prompts for literal "DELETE" confirmation)
python main.py --mode manual

# Automated / headless (requires session.json from a prior manual run)
python main.py --mode auto --yes

# Force re-authentication
python main.py --mode manual --relogin
```

## Architecture

The project has a strict layered separation:

```
main.py           CLI (Click) — orchestrates the run: load config, auth, clean, summary
config.py         All constants: URLs, timeouts, selectors, credentials from .env
auth/session.py   Authentication — creates/loads Playwright storage_state (session.json)
rpa/cleaner.py    Core DFS traversal and deletion logic
rpa/ui.py         Rich TUI — Observer pattern via RPACallbacks dataclass
rpa/logger.py     Loguru configuration + rotating audit log in logs/
rpa/_retry.py     @with_retry decorator with exponential backoff
```

**Data flow**: `main.py` creates `RPADisplay`, then `FolderCleaner(page, callbacks=display.callbacks)`. The cleaner calls callbacks (Observer pattern) and the display updates the TUI in real time without the cleaner knowing about Rich.

**Session handling**: Playwright `storage_state` (cookies + localStorage) is persisted in `session.json`. `auth/session.py` detects session expiry by checking whether the current URL redirected to any host in `LOGIN_REDIRECT_HOSTS`. Expiry mid-run raises `SessionExpiredError` → exit code 3.

**DFS deletion**: `cleaner.py` traverses folders depth-first. After each file delete it re-lists the DOM because OneDrive's list is virtualized and stale after mutation. Delete is intentionally NOT wrapped in `@with_retry` (ADR-7: delete is not idempotent from the UI — a retry could delete a different file that moved into the same DOM slot).

**Selectors**: `config.py → SELECTORS` uses `data-automationid` attributes instead of `aria-label`. This is load-bearing: `aria-label` text varies by tenant language; `data-automationid` is a Microsoft testing contract and more stable across locales.

## Key files to edit for common tasks

| Task | File |
|------|------|
| OneDrive UI changed / selectors broke | `config.py → SELECTORS` |
| Change timeouts | `config.py → NAV_TIMEOUT_MS / ACTION_TIMEOUT_MS` |
| Add folders to clean | `folders.json` |
| Change retry behavior | `config.py → MAX_RETRIES / RETRY_BACKOFF_SEC` |
| Detect session expiry from new URL patterns | `config.py → LOGIN_REDIRECT_HOSTS` |
| Add new TUI event category | `rpa/ui.py → _EVENTS` dict |

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | Success or user cancelled at confirmation |
| 1 | Config error (bad `folders.json`) |
| 2 | `session.json` missing in `--mode auto` |
| 3 | Session expired mid-run |
| 130 | Ctrl+C |
