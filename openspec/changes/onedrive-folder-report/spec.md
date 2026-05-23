# Spec: OneDrive Folder Report

**Change**: onedrive-folder-report
**Status**: draft
**Date**: 2026-05-22

---

## Delta — What MUST Be True After This Change

---

## 1. Capabilities Table

| ID  | Capability | Type | Trigger |
|-----|-----------|------|---------|
| C-1 | `folders.json` schema migration to object format | Modified | Always on load |
| C-2 | Backward-compatible loader for legacy array format | Modified | On load of old file |
| C-3 | Post-clean report step execution | New | After clean loop in `main.py` completes |
| C-4 | OneDrive subfolder enumeration (immediate children only) | New | Report step |
| C-5 | Password generation without `"` or `'` | New | Report step |
| C-6 | Excel file generation in memory | New | Report step |
| C-7 | Excel upload to `destination_folder` in OneDrive | New | Report step |
| C-8 | Public navigation surface in `cleaner.py` | Modified | Import time |

---

## 2. Capability Specifications

### C-1 — `folders.json` schema migration to object format

New schema:
```json
{
  "clean": [{ "path": "Documents/folder1" }],
  "report": {
    "source_folder": "Documents/registros",
    "destination_folder": "Documents/reportes"
  }
}
```

- `clean` (required): array of objects with `"path"` string — same semantics as current root array.
- `report` (optional): object with `source_folder` and `destination_folder` string fields.

Postconditions: loader returns structured object with `clean` list and `report` config as distinct attributes.

---

### C-2 — Backward-compatible loader for legacy array format

Detection rule: if top-level JSON value is an array, treat it as `clean` list and set `report = None`.

- Legacy format: `clean` list populated; `report = None`.
- New format: both populated per C-1.
- Object missing `clean`: raise `ConfigError` with descriptive message.
- Object missing `report`: `report = None`; report step skipped silently.

Postconditions: callers always access `config.clean` (list) and `config.report` (object or None) without branching on file format.

---

### C-3 — Post-clean report step execution

Trigger: end of clean loop in `main.py`, before the summary is printed.

Preconditions:
- All `clean` folders have been processed.
- `config.report` is not None.
- Valid Playwright `page` is available (session not expired).

Happy path:
1. Navigate to `source_folder` in OneDrive.
2. Enumerate immediate subfolders (names only, no recursion).
3. For each subfolder: generate password, record `creation_date` as current datetime (ISO format).
4. Produce `.xlsx` in memory with columns: `Folder Name`, `Password`, `Creation Date`.
5. Upload `.xlsx` to `destination_folder`.
6. Log summary: row count, upload path, elapsed time.

Skip condition: if `config.report` is None, skip entirely with one DEBUG log line. No local files written to disk (except temp file during upload — see C-7).

---

### C-4 — OneDrive subfolder enumeration (immediate children only)

Inputs: `source_folder` path string, active Playwright `page`.

Happy path: navigate to `source_folder`, list items via `data-automationid` selectors, filter `is_folder == True`, return `list[str]` of folder names.

Edge cases:

| Case | Required behavior |
|------|-------------------|
| `source_folder` not found | Raise `ReportError("source_folder not found: {path}")`. Non-fatal. |
| Zero subfolders | Return empty list. Excel generated with header only. Emit WARNING. |
| DOM virtualization >50 items | V1 limitation: enumerate only initially visible items. Emit WARNING about truncation. |
| Navigation timeout | Raise `ReportError("timeout navigating to source_folder: {path}")`. Non-fatal. |

Outputs: `list[str]` — folder names in DOM order.

---

### C-5 — Password generation without `"` or `'`

Inputs: `length: int` (default 24, minimum 16).

Alphabet: `string.ascii_letters + string.digits + "!@#$%^&*()-_=+[]{}|;:,.<>?"`
- Explicitly excludes `"` (U+0022) and `'` (U+0027).
- Alphabet size: 86 characters.

Behavior: uses `secrets.choice` (CSPRNG). Raises `ValueError` if `length < 16`.

Outputs: `str` of exactly `length` characters, all from the allowed alphabet.

Postconditions: returned string contains no `"` or `'`. Verifiable by unit test over ≥10,000 samples.

Purity: callable without Playwright, browser session, or network access.

---

### C-6 — Excel file generation in memory

Inputs: `rows: list[dict]` with keys `folder_name`, `password`, `creation_date`.

Happy path:
- `openpyxl.Workbook()`, single sheet named `"Report"`.
- Row 1: bold header `["Folder Name", "Password", "Creation Date"]`.
- Rows 2+: one per entry in `rows`.
- Serialized to `BytesIO` buffer (no disk write).
- Filename: `REPORT_FILENAME_PREFIX + UTC ISO8601 compact timestamp + ".xlsx"`.
  Example: `folder_report_20260522T143000Z.xlsx`.

Edge cases:
- Empty `rows`: valid `.xlsx` with header only. No error.
- Folder names with special chars: write as-is; `openpyxl` handles natively.

Outputs: `tuple[BytesIO, str]` — (buffer at position 0, filename string).

Purity: callable without Playwright, browser session, or network access.

---

### C-7 — Excel upload to `destination_folder` in OneDrive

Inputs: `destination_folder` path, file buffer (`BytesIO`), filename string, Playwright `page`.

Happy path:
1. Navigate to `destination_folder`.
2. Trigger upload via `data-automationid` selector for Upload button.
3. Write buffer to OS temp file; use `page.set_input_files`.
4. Delete temp file in `try/finally`.
5. Wait for upload confirmation.
6. Log success.

Edge cases:

| Case | Required behavior |
|------|-------------------|
| `destination_folder` not found | Raise `ReportError("destination_folder not found: {path}")`. Non-fatal. |
| File with same name already exists | Confirm overwrite dialog if present; proceed. No error. |
| Upload timeout | Raise `ReportError("upload timeout for {filename}")`. Non-fatal. |
| Temp file creation fails | Let OS exception propagate to top-level handler. |

Postconditions: temp file deleted regardless of outcome. Session remains navigable.

---

### C-8 — Public navigation surface in `cleaner.py`

Required contract:
- `_navigate_to_folder` and `_list_items` accessible without leading underscore, OR extracted to `rpa/_navigation.py`.
- `FolderCleaner` constructor, `clean(folder)` method, and all exit codes remain byte-identical.
- `reporter.py` can call the shared navigation surface without importing `FolderCleaner`.

---

## 3. Cross-Cutting Constraints

- `ReportError` is a new exception class in `rpa/reporter.py`. Report-step failures are **NON-FATAL** (no exit code change).
- All `ReportError` instances logged at ERROR level via Loguru.
- No new exit codes.
- `config.py` MUST add: `REPORT_FILENAME_PREFIX: str = "folder_report_"`.
- `openpyxl` MUST be added to `requirements.txt`.
- No disk writes for report except the Playwright upload temp file (deleted in `try/finally`).

Unit-testable without Playwright: `generate_password`, `build_report_rows`, `write_xlsx`.

---

## 4. Acceptance Scenarios

| ID | Scenario | Given | When | Then |
|----|----------|-------|------|------|
| S-1 | Normal run — clean then report | New object schema, valid session, source_folder with 3 subfolders, destination_folder exists | main.py runs | Clean executes, then .xlsx uploaded with 4 rows (header + 3), exit code 0 |
| S-2 | Legacy array format — report skipped | folders.json is a JSON array | main.py runs | Clean runs, report skipped silently, exit code 0 |
| S-3 | Object format without report key | folders.json object with only clean | main.py runs | Clean runs, report skipped silently, exit code 0 |
| S-4 | source_folder not found | report config present, source_folder missing | report step runs | ReportError logged at ERROR, clean summary still prints, exit code unchanged |
| S-5 | source_folder empty | source_folder exists with zero subfolders | report step runs | WARNING logged, Excel with header-only uploaded, no error |
| S-6 | destination_folder not found | destination_folder missing | upload step runs | ReportError logged at ERROR, non-fatal |
| S-7 | DOM virtualization | source_folder has >50 immediate subfolders | enumeration runs | Only N visible collected, WARNING logged, Excel with N rows uploaded |
| S-8 | Password alphabet compliance | generate_password(24) called 10,000 times | — | No result contains `"` or `'`, all 24 chars, all from allowed alphabet |
| S-9 | Upload file already exists | Same filename in destination_folder | upload runs | Overwrite confirmed, file overwritten, no error |
| S-10 | Session expiry during clean | SessionExpiredError fires mid-clean | main.py handles exception | Report step NOT attempted, exit code 3 (unchanged) |

---

## 5. Out of Scope (V1)

- Recursive subfolder traversal
- Scroll-to-load for >50 subfolder DOM virtualization
- Storing/encrypting passwords outside Excel
- Non-Playwright upload mechanisms (no OneDrive Graph API)
- Email delivery
- Modifications to clean flow flags or exit codes
- New CLI flags for report step (config via `folders.json` only)

---

## 6. Files Affected

| File | Change type | Contract |
|------|-------------|----------|
| `onedrive_rpa/folders.json` | Modified | Object schema with `clean` + `report` |
| `onedrive_rpa/main.py` | Modified | Read new schema; run report step after clean loop |
| `onedrive_rpa/rpa/reporter.py` | New | `collect_subfolders`, `generate_password`, `build_report_rows`, `write_xlsx`, `upload_file`, `ReportError` |
| `onedrive_rpa/rpa/cleaner.py` | Modified | Expose public navigation surface (C-8) |
| `onedrive_rpa/config.py` | Modified | Add `REPORT_FILENAME_PREFIX` |
| `onedrive_rpa/requirements.txt` | Modified | Add `openpyxl` |
