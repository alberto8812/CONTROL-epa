# Design: folder-sharing-link

## Technical Approach

After each folder is cleaned, set an "Anyone" sharing link (expiry today+9d, password = report password) via a new function-based module `rpa/sharer.py`, mirroring `reporter.run_report()`. Passwords are pre-generated once before the clean loop into a `dict[str,str]` keyed by folder base name, then consumed by both the sharer (step 4) and `build_report_rows()` (step 5) — single source of truth. Per-folder sharing failures are non-fatal: caught at `main.py`, logged, recorded in `ShareStats`, never abort the run nor change the exit code (same contract as `run_report`).

## Architecture Decisions

| ID | Decision | Choice | Rationale / Rejected |
|----|----------|--------|----------------------|
| S1 | Module shape | Function `share_folder(page, folder_path, password, expiry_date)` + `ShareStats` | Sharing is stateless per call; matches `reporter.run_report`. Class (`FolderCleaner` style) rejected — no per-instance state to hold. |
| S2 | Selector strategy | `SHARE_SELECTORS` dict, comma-separated CSS lists, `data-automationid` first then aria/title/text | Same locale-stable contract as `SELECTORS`. Selectors UNKNOWN → must verify in live probe; centralizing keeps the fix one-place. |
| S3 | Retry | `@with_retry()` on `_open_share_dialog()` and `_apply_share_settings()` | Sharing OVERWRITES existing link state → idempotent (unlike delete, ADR-7). Re-applying same scope/expiry/password is safe. |
| S4 | Date format | Pure helper `_format_expiry(dt) -> str` → `dt.strftime("%d/%m/%Y")` | Locale-fixed DD/MM/YYYY, browser-free unit test. |
| S5 | Password coordination | `build_report_rows(..., passwords: dict[str,str] \| None = None)` | When provided and name in map → reuse; else `generate_password()` (backward compat). Keeps "share pwd == report pwd" invariant. |
| S6 | Folder selection | Reuse `_find_row_by_name()` pattern → click row checkbox → click share toolbar | Pre-mutation re-list is the existing virtualized-DOM convention. |
| S7 | Path→key mapping | Pure helper `folder_key(path) -> str` = `path.rstrip("/").split("/")[-1]` | "pruebas/archivos_1" → "archivos_1" = report row key. Unit-testable invariant. |

## Data Flow

    main.py: load folders.json
        │
        ├─ folder_key(path) for each clean path ──► passwords: dict[str,str]   (PRE-GENERATED, single source)
        │                                                │
        ▼                                                │
    for each folder_path:                                │
        FolderCleaner.clean(folder_path)                 │
        └─ on success ─► sharer.share_folder(            │
                            page, folder_path,           │
                            password=passwords[key], ◄───┤
                            expiry_date=today+9d)        │
                            └─ ShareStats (non-fatal)    │
                                                         │
    post-clean: reporter.build_report_rows(              │
                   subfolders, passwords=passwords) ◄────┘
                   (same pwd lands in Excel)

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `onedrive_rpa/rpa/sharer.py` | Create | `share_folder()`, `ShareStats`, `ShareError`, `_format_expiry`, `folder_key`, retry-decorated helpers |
| `onedrive_rpa/config.py` | Modify | Add `SHARE_SELECTORS` dict + `SHARE_EXPIRY_DAYS = 9` |
| `onedrive_rpa/rpa/reporter.py` | Modify | `build_report_rows()` gains `passwords: dict[str,str] \| None = None` |
| `onedrive_rpa/main.py` | Modify | Pre-generate password map, call `share_folder` after each clean, pass map to reporter, fold share stats into summary |
| `tests/test_sharer.py` | Create | Unit tests for `_format_expiry`, `folder_key`, `ShareStats` aggregation |

## Interfaces / Contracts

```python
# config.py
SHARE_EXPIRY_DAYS: int = 9
SHARE_SELECTORS: dict[str, str] = {
    "share_button": (
        "[data-automationid='shareCommand'], "
        "button[title='Compartir'], button[aria-label='Compartir'], "
        "button[title='Share'], button[aria-label='Share']"
    ),
    "anyone_option": (
        "[data-automationid='anyone'], "
        "[role='radio']:has-text('Cualquier persona'), "
        "[role='menuitemradio']:has-text('Cualquier persona'), "
        "button:has-text('Cualquier persona'), "
        "[role='radio']:has-text('Anyone')"
    ),
    "expiry_input": (
        "input[placeholder*='DD/MM'], "
        "input[aria-label*='expiración'], input[aria-label*='expiration'], "
        "input[aria-label*='caducidad'], input[type='date']"
    ),
    "password_input": (
        "input[placeholder*='contraseña'], input[placeholder*='password'], "
        "input[aria-label*='contraseña'], input[aria-label*='password'], "
        "input[type='password']"
    ),
    "apply_button": (
        "[data-automationid='apply'], "
        "button[title='Aplicar'], button[aria-label='Aplicar'], "
        "button:has-text('Aplicar'), button:has-text('Apply')"
    ),
}

# sharer.py
class ShareError(Exception): ...

@dataclass
class ShareStats:
    shared: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    @property
    def shared_count(self) -> int: ...
    def merge(self, other: "ShareStats") -> None: ...

def folder_key(folder_path: str) -> str: ...        # pure
def _format_expiry(dt: datetime) -> str: ...          # pure → "%d/%m/%Y"

def share_folder(
    page: "Page",
    folder_path: str,
    password: str,
    expiry_date: datetime,
) -> ShareStats:
    """Set Anyone link on folder_path. Non-fatal: catches all,
    records in ShareStats.errors, never raises to caller."""
```

`share_folder` flow: navigate to parent → re-list → `_find_row_by_name(leaf)` → click row checkbox → `_open_share_dialog()` (retry) → select "Cualquier persona" → fill `_format_expiry(expiry_date)` → fill password → `_apply_share_settings()` (retry) → record `shared`. All wrapped in try/except → `ShareError`/`Exception` appended to `stats.errors`, logged `SHARE_ERROR`.

`build_report_rows` change: `pwd = passwords.get(name) if passwords else None; row["password"] = pwd or generate_password()`.

`main.py` flow (pseudocode):
```
passwords = {folder_key(p): generate_password() for p in folder_paths}
expiry = datetime.now() + timedelta(days=config.SHARE_EXPIRY_DAYS)
share_stats = ShareStats()
for folder_path in folder_paths:
    stats = cleaner.clean(folder_path)          # existing
    global_stats.merge(stats)
    if not dry_run:
        s = share_folder(page, folder_path,
                         passwords[folder_key(folder_path)], expiry)
        share_stats.merge(s)
...
run_report(..., passwords=passwords)            # via build_report_rows
_emit_summary(global_stats, share_stats, start_time)
```

## Testing Strategy

| Layer | What to Test | Approach |
|-------|--------------|----------|
| Unit | `_format_expiry` | Fixed datetime → exact "DD/MM/YYYY" string; verify zero-padding |
| Unit | `folder_key` | "a/b/c" → "c"; trailing slash; single segment |
| Unit | `ShareStats.merge` / counts | Aggregation across folders |
| Unit | `build_report_rows(passwords=...)` | Provided map reused; `None` falls back to `generate_password`; partial map mixes both |
| Manual/E2E | dialog selectors, full share flow | Single real folder in authenticated session — verify "Anyone", expiry, password applied |

## Migration / Rollout

No data migration. `build_report_rows()` is backward compatible (new arg defaults `None`). E2E-validate `SHARE_SELECTORS` against one live folder before enabling for the full clean list.

## Open Questions

- [ ] Live-verify all `SHARE_SELECTORS` (dialog DOM unknown) — adjust during probe.
- [ ] Confirm OneDrive expiry input accepts typed `DD/MM/YYYY` vs. requiring a date-picker interaction.
- [ ] Confirm password field appears only after enabling a "set password" toggle (may need an extra `_enable_password` step).
