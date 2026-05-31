# Tasks: folder-sharing-link

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 200–260 |
| 400-line budget risk | Low |
| Chained PRs recommended | No |
| Suggested split | Single PR |
| Delivery strategy | single-pr |
| Chain strategy | size-exception (N/A — under budget) |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: size-exception
400-line budget risk: Low

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|-------|
| 1 | All tasks below | PR 1 | Single PR; ~200–260 lines; under 400-line budget |

---

## Phase 1: Foundation — Config + Pure Helpers

- [x] 1.1 `onedrive_rpa/config.py` — Add `SHARE_EXPIRY_DAYS: int = 9` constant
- [x] 1.2 `onedrive_rpa/config.py` — Add `SHARE_SELECTORS: dict[str, str]` with best-guess CSS lists for `share_button`, `anyone_option`, `expiry_input`, `password_input`, `apply_button` (data-automationid first, aria/text fallbacks). **SELECTOR SPIKE**: these selectors are unverified against live DOM — apply must probe and adjust before wiring up the full flow.
- [x] 1.3 `onedrive_rpa/rpa/sharer.py` (NEW) — Define `ShareError(Exception)` and `@dataclass ShareStats(shared: list[str], share_errors: list[str])` with `field(default_factory=list)` defaults
- [x] 1.4 `onedrive_rpa/rpa/sharer.py` — Add pure `folder_key(folder_path: str) -> str` = `folder_path.rstrip("/").rsplit("/", 1)[-1]` (satisfies C-2 key derivation + S-7 path→key design decision)
- [x] 1.5 `onedrive_rpa/rpa/sharer.py` — Add pure `_format_expiry(dt: datetime) -> str` = `dt.strftime("%d/%m/%Y")` (satisfies C-3 expiry format + S-4)

## Phase 2: Core Implementation — Playwright Module

- [x] 2.1 `onedrive_rpa/rpa/sharer.py` — Add `@with_retry()` private helper `_open_share_dialog(page, folder_path)`: navigate to parent folder, re-list DOM, call `_find_row_by_name(leaf)`, click row checkbox, click share toolbar button using `SHARE_SELECTORS["share_button"]`
- [x] 2.2 `onedrive_rpa/rpa/sharer.py` — Add `@with_retry()` private helper `_apply_share_settings(page, password, expiry_str)`: select "Cualquier persona" radio via `SHARE_SELECTORS["anyone_option"]`, fill expiry field, fill password field, click apply button via `SHARE_SELECTORS["apply_button"]`
- [x] 2.3 `onedrive_rpa/rpa/sharer.py` — Add public `share_folder(page, folder_path: str, password: str, expiry_date: datetime) -> ShareStats`: call `_open_share_dialog`, call `_apply_share_settings`, append `folder_key(folder_path)` to `stats.shared` on success; on `ShareError` / `Exception` append to `stats.share_errors` and log at ERROR — never re-raises (satisfies C-1 non-fatal contract)

## Phase 3: Integration — reporter.py + main.py

- [x] 3.1 `onedrive_rpa/rpa/reporter.py` — Add `passwords: dict[str, str] | None = None` keyword-only param to `build_report_rows()`; inside row loop: `pwd = passwords.get(name) if passwords else None; row["password"] = pwd or generate_password()` (satisfies C-2 backward-compat + acceptance S-5, S-12)
- [x] 3.2 `onedrive_rpa/main.py` — Import `sharer`, `ShareStats`, `folder_key` from `rpa/sharer`; before clean loop build `passwords = {folder_key(p): generate_password() for p in folder_paths}` and `expiry = datetime.now() + timedelta(days=config.SHARE_EXPIRY_DAYS)` (satisfies C-2 pre-generation + S-4)
- [x] 3.3 `onedrive_rpa/main.py` — After each `cleaner.clean(folder_path)` success and `if not dry_run`, call `share_folder(page, folder_path, password=passwords[key], expiry_date=expiry)` and merge result into `share_stats`; skip + emit DEBUG log when `dry_run=True` (satisfies C-1, S-3)
- [x] 3.4 `onedrive_rpa/main.py` — Pass `passwords=passwords` to `build_report_rows()`; include `ShareStats` counts in run summary log: `"Shared: {n}, Share errors: {n}"` (satisfies C-2 coordination + C-4 + S-9)

## Phase 4: Tests

- [x] 4.1 `tests/test_sharer.py` (NEW) — `TestFormatExpiry`: fixed datetime `2026-05-30` → `"30/05/2026"`, zero-padding `2026-01-05` → `"05/01/2026"` (covers S-6, S-7)
- [x] 4.2 `tests/test_sharer.py` — `TestFolderKey`: `"pruebas/archivos_1"` → `"archivos_1"`, `"documentos"` → `"documentos"`, trailing slash `"a/b/"` → `"b"` (covers S-11, C-2 key derivation)
- [x] 4.3 `tests/test_sharer.py` — `TestShareStats`: default state `shared==[], share_errors==[]`; append to each list and verify counts (covers C-4, S-8)
- [x] 4.4 `tests/test_reporter.py` — `TestBuildReportRowsPasswords`: with injected map → row password matches map value (S-4); without arg → `generate_password()` path hit (S-5); empty dict → fallback (S-12)
