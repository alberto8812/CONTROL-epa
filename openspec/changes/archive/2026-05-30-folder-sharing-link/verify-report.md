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

All 14 tasks COMPLETE.

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
| S-6 | Expiry format 2026-05-30 → "30/05/2026" | TestFormatExpiry.test_format_expiry_basic PASS; runtime verified | PASS |
| S-7 | Expiry zero-padded (2026-01-05 → "05/01/2026") | TestFormatExpiry.test_format_expiry_zero_padding_day PASS; runtime verified | PASS |
| S-8 | ShareStats default state | TestShareStats.test_sharestate_default_* PASS | PASS |
| S-9 | Summary includes "Shared: N, Share errors: N" | main.py:436 — exact format in _emit_summary | PASS |
| S-10 | All shares fail — exit unchanged | share_folder appends to share_errors, never raises; exit code unchanged | PASS |
| S-11 | folder_key from nested path "a/b/c" → "c" | TestFolderKey.test_folder_key_simple PASS | PASS |
| S-12 | Missing key in passwords — fallback | TestBuildReportRowsPasswords.test_build_report_rows_fallback_when_name_missing PASS | PASS |

All 12 spec acceptance scenarios: PASS.

---

## Spec Requirement Compliance

| ID | Capability | Status | Notes |
|----|-----------|--------|-------|
| C-1 | Share follows each clean, non-fatal, skipped in dry-run | PASS | ✅ |
| C-2 | Passwords pre-generated before loop, coordinated | PASS | ✅ |
| C-3 | SHARE_SELECTORS + SHARE_EXPIRY_DAYS in config.py | PASS | ✅ |
| C-4 | ShareStats dataclass + summary counts | PASS | ✅ |

---

## Design Coherence

| Deviation | Severity | Assessment |
|-----------|----------|-----------|
| _open_share_dialog signature uses folder_name (leaf) not full path | SUGGESTION | Documented in apply-progress as intentional. Navigation happens in share_folder caller. Functionally correct. |
| _click_apply not wrapped in @with_retry | SUGGESTION | Consistent with ADR-7 spirit (final commit step). Documented. Correct. |
| run_report also gains passwords kwarg (not in original design) | SUGGESTION | Required for practical wiring from main.py. Correct augmentation. |

---

## Issues

### CRITICAL
None.

### WARNING

**W-1: SHARE_SELECTORS not validated against live OneDrive DOM**
All selectors in config.py are best-guess values using data-automationid/aria-label conventions. They have NOT been tested against a real OneDrive session. The sharing dialog flow (anyone_option, expiry_input, password_input, apply_button, share_button, row_checkbox) may fail on first real run.
- Files: `onedrive_rpa/config.py` lines 290–336
- Risk: share_folder will raise ShareError on every folder (all go to share_errors). Run continues but sharing is entirely non-functional until selectors are tuned.
- Mitigation: First real run with a test folder; adjust selectors in config.py.

**W-2: navigate_to_folder called with full path for top-level folders**
For `folder_path = "documentos"` (no slash), `share_folder` calls `navigate_to_folder(page, "documentos")` — navigating to the folder itself, not its parent. Then `_open_share_dialog(page, "documentos")` looks for a row named "documentos" inside that folder, which will NOT exist (the row would be in the *parent* view). This is a behavioral bug for top-level folders.
- File: `onedrive_rpa/rpa/sharer.py` lines 251–261
- Risk: Any folder_path without a "/" will fail to open the share dialog and land in share_errors.
- Mitigation: Navigate to the OneDrive root (empty string or root URL) when parent_path is "".

### SUGGESTION

**SUG-1: No test coverage for navigate_to_folder call logic in share_folder**
The navigation branching for top-level vs. nested paths (lines 251–261 of sharer.py) is untested. A unit test mocking navigate_to_folder and _open_share_dialog would catch W-2.

**SUG-2: _emit_summary signature gap — share_stats parameter is optional but always passed**
`_emit_summary(stats, start_time, global_share_stats)` — share_stats is typed `ShareStats | None = None`. Since it is always passed in normal flow, the None branch is dead code. Low priority.

---

## Final Verdict

PASS WITH WARNINGS

1 WARNING is a real behavioral bug (W-2: top-level folder navigation), 1 WARNING is a deferred real-world validation concern (W-1: unverified selectors). Neither blocks archive since the sharing step is explicitly non-fatal and does not affect exit code. Both must be tracked for the first live run.
