# Verify Report: onedrive-folder-report

**Verdict**: PASS WITH WARNINGS
**Date**: 2026-05-22
**Mode**: Standard (no Strict TDD)
**Tests**: 15/15 PASS
**Critical issues**: 0
**Warnings**: 5
**Suggestions**: 2

---

## Test Results

Command: `python3 -m unittest discover -s tests -q`
Result: Ran 15 tests in ~0.5s — ALL PASS (exit 0)

Tests passing:
- `TestGeneratePassword`: 4 tests (length, alphabet, 10k no-quotes, min-length-raises)
- `TestBuildReportRows`: 3 tests (count, keys, injected-now)
- `TestWriteExcel`: 1 test (round-trip)
- `TestBuildReportFilename`: 1 test (format)
- `TestLoadFoldersLegacyArrayFormat`: 1 test
- `TestLoadFoldersModernObjectFormat`: 3 tests
- `TestLoadFoldersErrorCases`: 2 tests

---

## Task Completion

All 15 tasks marked `[x]` complete in `tasks.md`. Code state matches all task descriptions.

---

## Spec Compliance Matrix

| ID | Requirement | Status | Notes |
|----|-------------|--------|-------|
| C-1 | folders.json object schema with clean + report | PASS | Correct |
| C-2 | Legacy array backward compat, report=None | PASS | Correct |
| C-2 | Half-configured report raises ConfigError | PASS | Test passes |
| C-2 | Missing clean raises ConfigError | PASS | Test passes |
| C-3 | Report hook after clean loop, inside sync_playwright | PASS | Lines 230–247 main.py |
| C-3 | Skipped when report is None | PASS | Implicit (no block runs) |
| C-3 | Skipped when dry_run=True with INFO log | PASS | `logger.info` at line 244 |
| C-3 | DEBUG log when report=None | WARNING | No debug log emitted — see W-4 |
| C-3 | Non-fatal: report errors don't change exit codes | PASS | run_report catches all exceptions |
| C-4 | collect_subfolders uses navigate_to_folder + list_items | PASS | Correct |
| C-4 | Filters is_folder=True only | PASS | Correct |
| C-4 | WARNING log when count >= 50 | PASS | Correct |
| C-4 | FolderNotFoundError → ReportError("source_folder not found: …") | WARNING | See W-3 |
| C-5 | Uses secrets.choice | PASS | Correct |
| C-5 | Alphabet excludes `"` and `'` | PASS | 88 chars, no quotes |
| C-5 | ValueError for length < 16 | PASS | Test passes |
| C-5 | 10 000 no-quotes samples | PASS | Test passes |
| C-6 | openpyxl Workbook, sheet "Report" | PASS | Correct |
| C-6 | Bold header row | PASS | font.bold=True confirmed |
| C-6 | Header values: "Folder Name", "Password", "Creation Date" | WARNING | See W-1 |
| C-6 | Returns BytesIO seeked to 0 | PASS | Correct |
| C-6 | Outputs tuple[BytesIO, str] | WARNING | See W-2 |
| C-7 | Navigates to destination_folder | PASS | Correct |
| C-7 | NamedTemporaryFile(delete=False) + cleanup in finally | PASS | Correct |
| C-7 | Shape A hidden input, Shape B file chooser fallback | PASS | Both present |
| C-7 | Waits for filename in DOM | PASS | wait_for_selector with has-text |
| C-7 | FolderNotFoundError → ReportError("destination_folder not found: …") | WARNING | See W-3 |
| C-8 | navigate_to_folder and list_items in _navigation.py | PASS | Correct |
| C-8 | FolderNotFoundError re-exported from cleaner.py | PASS | Same class, backward compat |
| C-8 | cleaner.py imports from _navigation.py, no duplication | PASS | Verified |
| X | ReportError is non-fatal | PASS | Caught in run_report |
| X | REPORT constants + upload selectors in config.py | PASS | All present |
| X | openpyxl==3.1.2 in requirements.txt | PASS | Present |
| X | 5 report callbacks in RPACallbacks with no-op defaults | PASS | All 5 verified |
| X | REPORT and UPLOAD event categories in ui.py | PASS | Both present |

---

## CRITICAL Issues

**None.**

---

## WARNING Issues

**W-1 — C-6: Excel header case mismatch**
spec.md line 128 specifies bold header `["Folder Name", "Password", "Creation Date"]` (display-friendly title case). Implementation writes `["folder_name", "password", "creation_date"]` (snake_case). Tests validate snake_case. Column headers will be less readable for business users.
- File: `onedrive_rpa/rpa/reporter.py` → `write_excel`
- Fix: Change header list to title-case strings and update the corresponding test assertion.

**W-2 — C-6: write_excel return type**
spec.md line 138 declares `Outputs: tuple[BytesIO, str]`. Implementation returns `BytesIO` only; filename comes from a separate `build_report_filename()` call in `run_report`. Functional behavior is correct but the standalone contract of `write_excel` deviates from the spec. Documented in apply-progress as deviation #3.
- File: `onedrive_rpa/rpa/reporter.py` → `write_excel`, `run_report`

**W-3 — C-4/C-7: FolderNotFoundError not wrapped as ReportError**
Spec C-4 requires `ReportError("source_folder not found: {path}")` and C-7 requires `ReportError("destination_folder not found: {path}")`. The implementation lets `FolderNotFoundError` propagate from `collect_subfolders` and `upload_report` up to `run_report`'s generic `except Exception` handler. Non-fatal behavior is preserved but the error type and message format deviate from the spec contract.
- File: `onedrive_rpa/rpa/reporter.py` → `collect_subfolders`, `upload_report`
- Fix: Wrap `FolderNotFoundError` in `collect_subfolders` and `upload_report` with `raise ReportError(f"source_folder not found: {source_folder}") from exc`.

**W-4 — C-3: Missing DEBUG log when report=None**
Spec cross-cutting says "skip entirely with one DEBUG log line" when `config.report is None`. Implementation silently skips (no log emitted). Minor observability gap.
- File: `onedrive_rpa/main.py` (~line 230)
- Fix: Add `logger.debug("REPORT | SKIPPED | reason=report_not_configured")` in the implicit else path.

**W-5 — REPORT_FILENAME_PREFIX value vs spec**
Spec cross-cutting says `REPORT_FILENAME_PREFIX: str = "folder_report_"`. Tasks.md T-01 says `"reporte_"`. Implementation uses `"reporte"` (no trailing underscore). The spec example shows `folder_report_20260522T143000Z.xlsx`; actual output is `reporte_20260522_143015.xlsx`. Noted in apply-progress as deviation #2. Not a runtime error but spec and implementation are misaligned.
- File: `onedrive_rpa/config.py` (REPORT_FILENAME_PREFIX)

---

## SUGGESTION Items

**S-1 — Dead code with missing SELECTORS keys**
`_delete_item()` in `cleaner.py` references `SELECTORS["context_menu_trigger"]` and `SELECTORS["delete_option"]` which are not defined in `config.py`. The function is dead code (never called by the current bulk-delete path) so this does not impact runtime. Consider either adding the selectors to `config.py` or removing the unreachable function.
- Files: `onedrive_rpa/rpa/cleaner.py`, `onedrive_rpa/config.py`

**S-2 — tasks.md header count error**
`tasks.md` header says "Total tasks: 14" but contains 15 tasks (T-01 through T-15). No functional impact.
- File: `openspec/changes/onedrive-folder-report/tasks.md`

---

## Design Coherence

| ADR | Decision | Status |
|-----|----------|--------|
| ADR-R1 | Navigation extraction to _navigation.py | COMPLIANT — cleaner.py imports, no duplication |
| ADR-R5 | Non-fatal report step | COMPLIANT — no exit code changes |
| ADR-R6 | secrets.choice for password generation | COMPLIANT |
| TDD | Pure functions tested first | COMPLIANT — all 9 pure-function tests pass |
| Manual | Playwright-bound functions have no unit tests | ACCEPTABLE per spec |

---

## Manual Integration Testing Required

These paths require a live OneDrive session and cannot be verified by unit tests:
- `collect_subfolders`: needs real folder with subfolders
- `upload_report` (Shape A/B): needs live OneDrive + file input selector
- `run_report` end-to-end: needs both above
- `folders.json` report paths need real tenant values before production use

---

## Documented Deviations (apply-progress)

All 5 apply-progress deviations confirmed by code inspection:

| # | Deviation | Verdict |
|---|-----------|---------|
| 1 | UPLOAD_TIMEOUT_MS=60_000 (orchestrator) vs 30_000 (tasks.md) | OK — orchestrator authoritative |
| 2 | REPORT_FILENAME_PREFIX="reporte" no trailing underscore | WARNING W-5 |
| 3 | write_excel returns BytesIO not tuple[BytesIO, str] | WARNING W-2 |
| 4 | creation_date stored as datetime object not isoformat | ACCEPTABLE — openpyxl handles datetime natively (better for Excel) |
| 5 | _load_folders raises ConfigError (not sys.exit(1)) | CORRECT — main() catches ConfigError and calls sys.exit(1) |
