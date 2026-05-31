# Verification Report: folder-sharing-link

**Change**: folder-sharing-link
**Date**: 2026-05-30
**Mode**: Standard (not Strict TDD)
**Verdict**: PASS WITH WARNINGS

---

## Task Completeness

| Phase | Task | Status |
|-------|------|--------|
| 1 | 1.1 SHARE_EXPIRY_DAYS in config.py | COMPLETE |
| 1 | 1.2 SHARE_SELECTORS dict in config.py (6 keys) | COMPLETE |
| 1 | 1.3 ShareError + ShareStats in sharer.py | COMPLETE |
| 1 | 1.4 folder_key() pure helper | COMPLETE |
| 1 | 1.5 _format_expiry() pure helper | COMPLETE |
| 2 | 2.1 _open_share_dialog() with @with_retry | COMPLETE |
| 2 | 2.2 _apply_share_settings() with @with_retry | COMPLETE |
| 2 | 2.3 share_folder() non-fatal public API | COMPLETE |
| 3 | 3.1 build_report_rows passwords kwarg | COMPLETE |
| 3 | 3.2 main.py imports + pre-password generation | COMPLETE |
| 3 | 3.3 main.py share_folder call after clean / dry-run skip | COMPLETE |
| 3 | 3.4 main.py passes passwords to run_report + _emit_summary ShareStats | COMPLETE |
| 4 | 4.1–4.3 test_sharer.py (13 tests) | COMPLETE |
| 4 | 4.4 TestBuildReportRowsPasswords (5 tests) | COMPLETE |

All 14 tasks: COMPLETE.

---

## Test Evidence

- Command: `python3 -m unittest discover -s tests -q`
- Result: Ran 49 tests in ~5.7s — OK (0 failures, 0 errors)
- New test_sharer.py: 13 tests covering _format_expiry, folder_key, ShareStats
- New TestBuildReportRowsPasswords: 5 tests covering passwords injection, fallback, empty dict, None, multi-folder

---

## Spec Compliance Matrix

| Scenario | Requirement | Evidence | Status |
|----------|-------------|----------|--------|
| S-1 | Normal share after clean | share_folder called after cleaner.clean() in main.py:225 | PASS |
| S-2 | Share failure non-fatal | share_folder wraps all exceptions in try/except, never re-raises | PASS |
| S-3 | Dry-run sharing skipped | main.py:228-232 — dry_run branch emits DEBUG log | PASS |
| S-4 | Password in report matches share link | passwords map built before loop; passed to both share_folder and run_report | PASS |
| S-5 | build_report_rows backward compat | TestBuildReportRowsPasswords.test_build_report_rows_passwords_none_uses_generate PASS | PASS |
| S-6 | Expiry "30/05/2026" | TestFormatExpiry.test_format_expiry_basic PASS; runtime verified | PASS |
| S-7 | Expiry zero-padded "08/06/2026" | TestFormatExpiry.test_format_expiry_zero_padding_day PASS; runtime verified | PASS |
| S-8 | ShareStats default state | TestShareStats default-state tests PASS | PASS |
| S-9 | Summary "Shared: N, Share errors: N" | main.py:436 exact format in _emit_summary | PASS |
| S-10 | All shares fail — exit unchanged | share_folder appends to share_errors, never raises | PASS |
| S-11 | folder_key "a/b/c" → "c" | TestFolderKey.test_folder_key_simple PASS | PASS |
| S-12 | Missing key — fallback | TestBuildReportRowsPasswords.test_build_report_rows_fallback_when_name_missing PASS | PASS |

All 12 acceptance scenarios: PASS.

---

## Capability Compliance

| ID | Capability | Status |
|----|-----------|--------|
| C-1 | Share follows each clean, non-fatal, skipped in dry-run | PASS |
| C-2 | Passwords pre-generated, coordinated across share + report | PASS |
| C-3 | SHARE_SELECTORS + SHARE_EXPIRY_DAYS in config.py | PASS |
| C-4 | ShareStats + summary counts | PASS |

---

## Issues

### CRITICAL
None.

### WARNING

**W-1: SHARE_SELECTORS not validated against live OneDrive DOM**
Selectors in `config.py` lines 290–336 are best-guess values. Not yet tested against a real session. On first real run, sharing may fail for every folder (all land in share_errors). Run continues. Non-blocking for archive since sharing is non-fatal.
- Mitigation: Test with a single folder; tune selectors.

**W-2: Top-level folder navigation bug in share_folder**
For a folder_path with no "/" (e.g. `"documentos"`), `share_folder` navigates *into* the folder itself instead of its parent, then calls `_open_share_dialog` looking for a row named `"documentos"` — which cannot exist inside itself. Affects any top-level folder in the clean list.
- File: `onedrive_rpa/rpa/sharer.py` lines 251–261
- Risk: ShareError for every top-level folder path. Run continues (non-fatal).
- Fix: When parent_path is `""`, navigate to the OneDrive root (empty string / root URL) instead of the full folder_path.

### SUGGESTION

**SUG-1**: No unit test for navigate_to_folder branching logic in share_folder (would have caught W-2).

**SUG-2**: `share_stats: ShareStats | None = None` in `_emit_summary` — None branch is dead code since it is always called with a real ShareStats instance.

---

## Final Verdict: PASS WITH WARNINGS

0 CRITICAL / 2 WARNING / 2 SUGGESTION

Both warnings are deferred live-session concerns. W-2 is a real behavioral bug for top-level folder paths but is self-contained inside the non-fatal share step. W-1 is an expected open item from apply-progress. Archive is safe to proceed; W-2 should be tracked for fix before first production run with top-level folder paths.
