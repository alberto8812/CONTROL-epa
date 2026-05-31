# Spec: folder-sharing-link

**Change**: folder-sharing-link
**Status**: draft
**Date**: 2026-05-30

---

## Capabilities Table

| ID  | Capability | Type | Module(s) |
|-----|-----------|------|-----------|
| C-1 | Share folder after successful clean | New | `rpa/sharer.py`, `main.py` |
| C-2 | Password pre-generation and coordination | Modified | `main.py`, `rpa/reporter.py` |
| C-3 | Sharing link configuration constants | New | `config.py` |
| C-4 | Sharing result tracking (`ShareStats`) | New | `rpa/sharer.py` |

---

## C-1 — Share folder after successful clean

### Requirement: Share attempt follows each clean

After `cleaner.clean(folder_path)` succeeds, the system MUST attempt to share that folder before moving to the next folder in the clean list.

Sharing failures MUST NOT abort the run or change the process exit code. Each per-folder failure MUST be caught, logged at ERROR level via Loguru, and recorded in `ShareStats.share_errors`.

The system MUST NOT attempt sharing if the run is in `--dry-run` mode.

#### Scenario: Sharing succeeds after clean

- GIVEN a folder was cleaned successfully and dry-run mode is off
- WHEN `share_folder(page, folder_path, password, expiry_date)` is called
- THEN the folder receives an "Anyone" sharing link with the given password and expiry
- AND the folder's `base_name` is appended to `ShareStats.shared`

#### Scenario: Sharing fails — run continues

- GIVEN `share_folder` raises `ShareError` for a folder
- WHEN the exception is caught in `main.py`
- THEN the error is logged at ERROR level with folder path and reason
- AND the folder's `base_name` is appended to `ShareStats.share_errors`
- AND the clean loop continues to the next folder with exit code unchanged

#### Scenario: Dry-run mode — sharing skipped

- GIVEN `--dry-run` flag is active
- WHEN the clean loop completes for a folder
- THEN `share_folder` is NOT called
- AND a DEBUG log line is emitted: "dry-run: skipping share for {folder_path}"

---

## C-2 — Password pre-generation and coordination

### Requirement: Passwords pre-generated before clean loop

The system MUST generate per-folder passwords exactly once, before the clean loop starts, producing `passwords: dict[str, str]` keyed by folder `base_name`.

`base_name` MUST be derived as `folder_path.rsplit("/", 1)[-1]`.

This map MUST be passed to `share_folder` (step 4) and to `build_report_rows(..., passwords=passwords)` (step 5), ensuring the password printed in the report is identical to the password on the sharing link.

#### Scenario: Passwords map built before loop

- GIVEN a `folders.json` clean list with N folder paths
- WHEN `main.py` initializes the run (before any clean call)
- THEN `passwords` dict has exactly N entries, one per `base_name`
- AND each value is a `generate_password()`-compliant string (no `"` or `'`)

#### Scenario: Key derivation — nested path

- GIVEN `folder_path = "pruebas/archivos_1"`
- WHEN the base name is derived
- THEN `base_name == "archivos_1"`

#### Scenario: Key derivation — top-level path

- GIVEN `folder_path = "documentos"`
- WHEN the base name is derived
- THEN `base_name == "documentos"`

### Requirement: build_report_rows accepts optional passwords argument

`build_report_rows()` MUST accept an optional `passwords: dict[str, str] | None = None` parameter (keyword-only). When `passwords` is provided and a key matching the folder's `base_name` exists, the pre-generated value MUST be used instead of calling `generate_password()` internally. When `passwords` is `None`, the function MUST fall back to its current internal generation (backward compatible).

#### Scenario: Pre-generated password used in report row

- GIVEN `passwords = {"archivos_1": "AbcXyz!2"}` and folder `base_name = "archivos_1"`
- WHEN `build_report_rows(folder_names, passwords=passwords)` is called
- THEN the row for that folder has `password == "AbcXyz!2"`

#### Scenario: Fallback when passwords is None

- GIVEN `build_report_rows(folder_names)` called without `passwords` argument
- WHEN report rows are built
- THEN each row receives a newly generated password (current behavior, unchanged)

#### Scenario: Missing key in passwords dict

- GIVEN `passwords = {}` (empty) and folder name present
- WHEN `build_report_rows(folder_names, passwords=passwords)` is called
- THEN the function falls back to `generate_password()` for that folder
- AND no error is raised

---

## C-3 — Sharing link configuration constants

### Requirement: SHARE_SELECTORS and SHARE_EXPIRY_DAYS in config.py

`config.py` MUST add:
- `SHARE_EXPIRY_DAYS: int = 9`
- `SHARE_SELECTORS: dict[str, str]` containing all UI selectors required by the sharing dialog flow

Selector values MUST prefer `data-automationid` attributes. Where `data-automationid` is absent, `aria-label` or visible text selectors are acceptable fallbacks.

The sharing dialog flow covers: folder checkbox selection, "Compartir" toolbar action, "Configuración de vínculos" dialog, "Cualquier persona" radio, expiry date field, password field, and "Aplicar" button.

#### Scenario: Expiry date computed from config

- GIVEN `SHARE_EXPIRY_DAYS = 9` and today is `2026-05-30`
- WHEN expiry is computed
- THEN expiry string is `"08/06/2026"` (DD/MM/YYYY format)

#### Scenario: Expiry date format — single-digit day and month

- GIVEN today is `2026-01-05` and `SHARE_EXPIRY_DAYS = 9`
- WHEN expiry is computed
- THEN expiry string is `"14/01/2026"` (zero-padded DD/MM/YYYY)

---

## C-4 — Sharing result tracking (ShareStats)

### Requirement: ShareStats dataclass captures per-run sharing outcome

`rpa/sharer.py` MUST define `ShareStats` as a dataclass with:
- `shared: list[str]` — `base_name` of each successfully shared folder
- `share_errors: list[str]` — `base_name` of each folder where sharing failed

`main.py` MUST include sharing outcome in the run summary log, showing count of shared folders and count of sharing errors.

#### Scenario: Summary includes sharing counts

- GIVEN a run with 3 folders cleaned, 2 shared successfully, 1 with ShareError
- WHEN the run summary is logged
- THEN it includes "Shared: 2, Share errors: 1"

#### Scenario: All sharing fails — summary still complete

- GIVEN every `share_folder` call raises `ShareError`
- WHEN the run completes
- THEN exit code is 0 (if no other errors), clean summary present
- AND share stats show `shared=[]`, `share_errors=[N folders]`

#### Scenario: ShareStats initial state

- GIVEN a newly instantiated `ShareStats`
- WHEN accessed before any operations
- THEN `shared == []` and `share_errors == []`

---

## Out of Scope

- Revoking existing sharing links
- Sending email or notification after sharing
- Sharing with specific named people
- `--dry-run` simulation of sharing (skip entirely, no mock)
- CLI flags for scope or expiry (fixed constants this change)
- Idempotency checks for already-shared folders

---

## Cross-Cutting Constraints

- `ShareError` is a new exception in `rpa/sharer.py`. It MUST NOT propagate past the per-folder boundary in `main.py`.
- Sharing step MUST NOT be wrapped in `@with_retry` (consistent with ADR-7: non-idempotent UI actions).
- All `ShareError` instances logged at ERROR via Loguru.
- No new exit codes.
- `share_folder` is a pure Playwright interaction — unit tests in `tests/test_sharer.py` cover helpers (expiry formatter, base_name extractor, ShareStats). Browser-dependent flow requires live probe.

---

## Acceptance Scenarios

| ID   | Scenario | Given | When | Then |
|------|----------|-------|------|------|
| S-1  | Normal share after clean | 2 folders, valid session, dry-run off | main.py runs full loop | Both folders shared; ShareStats.shared has 2 entries; exit 0 |
| S-2  | Share failure — non-fatal | `share_folder` raises ShareError | main.py handles error | folder in share_errors; clean summary printed; exit 0 |
| S-3  | Dry-run — sharing skipped | `--dry-run` active | main.py runs | `share_folder` never called; DEBUG log emitted; exit 0 |
| S-4  | Password in report matches share link | passwords map built before loop | report rows + share both consume map | Row password == link password for every folder |
| S-5  | build_report_rows backward compat | called without passwords arg | build_report_rows(folder_names) | Internal generate_password used; no TypeError |
| S-6  | Expiry format correct | SHARE_EXPIRY_DAYS=9, today=2026-05-30 | expiry computed | "08/06/2026" |
| S-7  | Expiry zero-padded | today=2026-01-05, SHARE_EXPIRY_DAYS=9 | expiry computed | "14/01/2026" |
| S-8  | ShareStats default state | ShareStats() instantiated | fields accessed | shared=[], share_errors=[] |
| S-9  | Summary reports counts | 2 shared, 1 error | run ends | Log line includes "Shared: 2, Share errors: 1" |
| S-10 | All shares fail — exit unchanged | Every share_folder raises | run completes | exit 0; summary shows share_errors count |
| S-11 | base_name from nested path | folder_path = "a/b/c" | base_name derived | base_name == "c" |
| S-12 | Missing key in passwords — fallback | passwords={}, folder name present | build_report_rows called | generate_password() used; no error |

---

## Files Affected

| File | Change type | Contract |
|------|-------------|----------|
| `onedrive_rpa/rpa/sharer.py` | New | `share_folder(page, folder_path, password, expiry_date)`, `ShareStats`, `ShareError` |
| `onedrive_rpa/config.py` | Modified | Add `SHARE_SELECTORS: dict`, `SHARE_EXPIRY_DAYS: int = 9` |
| `onedrive_rpa/rpa/reporter.py` | Modified | `build_report_rows()` gains optional `passwords: dict[str, str] | None = None` |
| `onedrive_rpa/main.py` | Modified | Pre-generate passwords; call sharer post-clean; pass map to reporter; include ShareStats in summary |
| `tests/test_sharer.py` | New | Unit tests: expiry formatter, base_name extractor, ShareStats aggregation, passwords map coordination |
