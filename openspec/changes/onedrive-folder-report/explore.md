# Exploration: onedrive-folder-report

**Date**: 2026-05-22
**Project**: control-epa
**Change**: onedrive-folder-report

---

## Current State

The `onedrive_rpa/` package is a clean, layered Python RPA tool.

**Architecture**:
- `main.py` — Single Click command (`main()`); orchestrates load config → auth → clean loop
- `config.py` — Central constants. Paths: `SESSION_PATH`, `FOLDERS_PATH`, `LOG_DIR`. No `REPORT_PATH` exists yet
- `rpa/cleaner.py` — `FolderCleaner.clean(folder_path)` does DFS traversal. Internally calls `_navigate_to_folder()`, `_list_items()` (returns `_ItemInfo(name, is_folder)`), `_enter_folder()`, `_go_back()`
- `rpa/ui.py` — Rich TUI via `RPACallbacks` Observer
- `auth/session.py` — `load_or_login()` handles both manual and auto modes
- `rpa/_retry.py` — `@with_retry` decorator
- `rpa/logger.py` — Loguru two-sink setup

**Current requirements**: `playwright`, `click`, `loguru`, `python-dotenv`, `rich`. No Excel or password generation library present.

**No tests exist** in the project.

---

## Approaches Considered

| Approach | Pros | Cons | Effort |
|----------|------|------|--------|
| 1. Click group (`clean` + `report` subcommands) | Clean CLI UX; proper separation | Requires minor refactor of `main()` | Medium |
| 2. New flags on existing `main` command | Zero structural change | Two unrelated concerns in one command | Low |
| 3. Standalone script with own `__main__` | Zero coupling | Duplicates auth setup; hard to discover | Medium |

---

## Recommendation

**Approach 1 — Click group with `report` subcommand.**

- `main.py` becomes a `@click.group`; existing logic moves to `clean` subcommand
- New `report` subcommand: `--root-folder` (required, default overrideable via config), `--output-file` (optional, timestamped default)
- New `onedrive_rpa/rpa/reporter.py` module with:
  - `collect_subfolders(page, root_folder) -> list[str]`
  - `generate_password(length=24) -> str` — `secrets` + custom alphabet, no quotes
  - `build_report_rows(folder_names) -> list[dict]` — pure, testable
  - `write_excel(rows, output_path)` — `openpyxl`

**Library choices**:
- Excel: `openpyxl` — pure Python, no C deps
- Password: `secrets` stdlib — no added dependency

```python
import secrets, string
ALPHABET = string.ascii_letters + string.digits + "!@#$%^&*()-_=+[]{}|;:,.<>?"
def generate_password(length: int = 24) -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(length))
```

---

## Risks

- **DOM virtualization**: `_list_items()` reads only visible rows. Large root folders (50+ subfolders) may be truncated. V1 should document this limit.
- **No tests**: new pure functions should be unit-testable. Playwright interaction isolated in `collect_subfolders`.
- **`_navigate_to_folder` is module-private**: needs to be made importable or extracted to `rpa/nav.py`.
- **Excel overwrite**: default output name must include timestamp to avoid silent overwrites.

---

## Ready for Proposal

Yes. Scope: 1 new module, 1 refactored CLI file, 1 new dependency, 0 changes to deletion logic.
