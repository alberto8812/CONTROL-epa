# Tasks: onedrive-folder-report

**Total tasks**: 14  
**Sequential chains**: 3 main chains with internal sequential dependencies  
**Parallel opportunities**: Tasks within the same wave can run in parallel

---

## Wave 0 — Foundation (sequential, no deps)

### [x] T-01 · config.py — Add report constants and upload selectors
**Spec refs**: C-5 (password alphabet), C-6 (filename), C-7 (upload selectors)  
**Design refs**: ADR-R4, ADR-R6  
**File**: `onedrive_rpa/config.py`  
**What**:
- Add `REPORT_PASSWORD_LENGTH: int = 24`
- Add `REPORT_PASSWORD_ALPHABET: str` (printable ASCII minus `"` and `'`)
- Add `REPORT_FILENAME_PREFIX: str = "reporte_"`
- Add `REPORT_FILENAME_TIMESTAMP_FORMAT: str = "%Y%m%d_%H%M%S"`
- Add `UPLOAD_TIMEOUT_MS: int = 30_000`
- Add to `SELECTORS`: `toolbar_upload`, `upload_files_menuitem`, `upload_file_input`

**Parallel with**: nothing (T-02 onward depend on this)  
**Estimated lines**: ~30

---

### [x] T-02 · requirements.txt — Add openpyxl
**Spec refs**: C-6  
**File**: `onedrive_rpa/requirements.txt`  
**What**: Append `openpyxl==3.1.2`  
**Depends on**: nothing  
**Parallel with**: T-01  
**Estimated lines**: 1

---

## Wave 1 — Test bootstrap (parallel, both depend only on T-01/T-02 being done first)

### [x] T-03 · Create tests/ directory and test_reporter.py skeleton
**Spec refs**: TDD requirement (pure functions: generate_password, build_report_rows, write_excel, build_report_filename)  
**File**: `tests/__init__.py`, `tests/test_reporter.py`  
**What**:
- Create `tests/` directory with empty `__init__.py`
- Write `test_reporter.py` with stdlib `unittest` test cases (RED — no implementation yet):
  - `TestGeneratePassword`: length=24, chars from alphabet, no `"` or `'`, uses `secrets`
  - `TestBuildReportRows`: given list of subfolder names + count dict → list of dicts with expected keys
  - `TestWriteExcel`: returns `BytesIO`, content is valid XLSX (openpyxl can open it), filename arg used
  - `TestBuildReportFilename`: format matches `reporte_YYYYMMDD_HHMMSS.xlsx`, uses local time

**Depends on**: T-01 (constants referenced in tests), T-02 (openpyxl import in tests)  
**Parallel with**: T-04  
**Estimated lines**: ~100

---

### [x] T-04 · Create tests/test_config_loader.py skeleton
**Spec refs**: C-1, C-2 (FoldersConfig schema), ADR-R3  
**File**: `tests/test_config_loader.py`  
**What**: Write `unittest` test cases (RED):
  - `TestLoadFoldersLegacyArray`: legacy `[{"path": "x"}]` → `FoldersConfig(clean=["x"], report=None)`
  - `TestLoadFoldersNewObject`: `{"clean": [...], "report": {...}}` → `FoldersConfig` with both fields populated
  - `TestLoadFoldersObjectNoReport`: object with only `clean` key → `report=None`
  - `TestLoadFoldersInvalidPath`: absolute path, `..`, empty string → `SystemExit(1)`

**Depends on**: T-01  
**Parallel with**: T-03  
**Estimated lines**: ~80

---

## Wave 2 — Navigation extraction (must complete before cleaner.py refactor)

### [x] T-05 · Create rpa/_navigation.py — extract and expose navigation helpers
**Spec refs**: C-8 (public surface for cleaner helpers), ADR-R1  
**File**: `onedrive_rpa/rpa/_navigation.py` (NEW)  
**What**:
- Define `ItemInfo(NamedTuple)` with `name: str`, `is_folder: bool` (public, replaces `_ItemInfo`)
- Re-export `FolderNotFoundError` (define it here; cleaner.py imports from here)
- Copy `_navigate_to_folder` → `navigate_to_folder` (public, keep `@with_retry`)
- Copy `_list_items` → `list_items` (public, keep `@with_retry`); use `ItemInfo` not `_ItemInfo`
- Keep module docstring explaining the extraction rationale (ADR-R1)

**Depends on**: T-01 (imports SELECTORS + new constants)  
**Parallel with**: T-03, T-04  
**Estimated lines**: ~80

---

## Wave 3 — Pure function implementations (TDD GREEN pass, parallel within wave)

### [x] T-06 · reporter.py — Implement generate_password (TDD GREEN)
**Spec refs**: C-5  
**Design refs**: ADR-R6  
**File**: `onedrive_rpa/rpa/reporter.py` (create file, first function only)  
**What**:
- Create `reporter.py` with module docstring
- Implement `generate_password(length: int = REPORT_PASSWORD_LENGTH) -> str`
  - Uses `secrets.choice`, iterates `length` times over `REPORT_PASSWORD_ALPHABET`

**Depends on**: T-01, T-03 (tests must exist first — TDD)  
**Parallel with**: T-07, T-08, T-09 (after T-03 is done)  
**Estimated lines**: ~20

---

### [x] T-07 · reporter.py — Implement build_report_filename (TDD GREEN)
**Spec refs**: C-6 (filename format)  
**Design refs**: ADR-R4  
**File**: `onedrive_rpa/rpa/reporter.py`  
**What**:
- Implement `build_report_filename(dt: datetime | None = None) -> str`
  - Default: uses `datetime.now()` (local time)
  - Format: `{REPORT_FILENAME_PREFIX}{REPORT_FILENAME_TIMESTAMP_FORMAT}.xlsx`

**Depends on**: T-01, T-03, T-06 (file already created)  
**Parallel with**: T-07 note: T-06 creates the file; T-07 and T-08 append to it — apply sequentially within wave or as one PR  
**Estimated lines**: ~15

---

### [x] T-08 · reporter.py — Implement build_report_rows (TDD GREEN)
**Spec refs**: C-4 (subfolder list), C-6 (report content)  
**File**: `onedrive_rpa/rpa/reporter.py`  
**What**:
- Implement `build_report_rows(subfolders: list[str], file_counts: dict[str, int]) -> list[dict]`
  - Returns list of `{"subfolder": str, "file_count": int}` dicts
  - Orders by subfolder name (alphabetical)

**Depends on**: T-06 (file created), T-03  
**Parallel with**: T-07  
**Estimated lines**: ~15

---

### [x] T-09 · reporter.py — Implement write_excel (TDD GREEN)
**Spec refs**: C-6  
**File**: `onedrive_rpa/rpa/reporter.py`  
**What**:
- Implement `write_excel(rows: list[dict], filename: str) -> BytesIO`
  - Uses `openpyxl`, writes to `BytesIO` (no disk write)
  - Sheet has header row: `Subcarpeta`, `Archivos`
  - Writes each row from `rows`
  - Returns the `BytesIO` seeked to 0

**Depends on**: T-02 (openpyxl), T-06 (file created), T-03  
**Parallel with**: T-07, T-08  
**Estimated lines**: ~30

---

### [x] T-10 · main.py + _load_folders — Implement FoldersConfig and new schema (TDD GREEN)
**Spec refs**: C-1, C-2 (schema migration), ADR-R3  
**Files**: `onedrive_rpa/main.py`  
**What**:
- Define `FoldersConfig(NamedTuple)` or `@dataclass`: `clean: list[str]`, `report: ReportConfig | None`
- Define `ReportConfig`: `folder: str`, `subfolders: list[str]`
- Rewrite `_load_folders(config_path: str) -> FoldersConfig`:
  - If `data` is `list` → legacy: extract paths into `clean`, set `report=None`
  - If `data` is `dict` → new: validate `clean` list + optional `report` block
  - All existing path validations preserved (absolute, `..`, empty)
- Update call sites in `main()` to use `FoldersConfig.clean` for the clean loop

**Depends on**: T-04 (tests must exist first — TDD), T-01  
**Parallel with**: T-06–T-09 (different file)  
**Estimated lines**: ~80

---

## Wave 4 — cleaner.py refactor (after _navigation.py exists)

### [x] T-11 · cleaner.py — Remove extracted helpers, import from _navigation.py
**Spec refs**: C-8  
**Design refs**: ADR-R1  
**File**: `onedrive_rpa/rpa/cleaner.py`  
**What**:
- Remove `_ItemInfo`, `_navigate_to_folder`, `_list_items` definitions
- Add `from onedrive_rpa.rpa._navigation import ItemInfo, navigate_to_folder, list_items, FolderNotFoundError`
- Remove `FolderNotFoundError` definition (now imported)
- Update all internal references: `_ItemInfo` → `ItemInfo`, `_navigate_to_folder` → `navigate_to_folder`, `_list_items` → `list_items`
- Keep `__all__` or re-export `FolderNotFoundError` so existing imports from `cleaner` still work

**Depends on**: T-05 (_navigation.py must exist and be complete)  
**Parallel with**: T-10 (different file)  
**Estimated lines**: ~-70 net (deletes more than adds)

---

## Wave 5 — Playwright-bound reporter functions (no unit tests, after all pure functions)

### [x] T-12 · reporter.py — Implement ReportStats, ReportError, collect_subfolders, upload_report, run_report
**Spec refs**: C-3, C-4, C-7  
**Design refs**: ADR-R2, ADR-R5  
**File**: `onedrive_rpa/rpa/reporter.py`  
**What**:
- Add `ReportError(Exception)` 
- Add `ReportStats` dataclass: `uploaded: bool`, `filename: str`, `password: str`, `subfolder_count: int`, `truncated: bool`
- Implement `collect_subfolders(page, folder_path, config) -> list[str]`: uses `list_items` from `_navigation.py`, immediate children only, raises `ReportError` if folder missing, emits warning if >50 subfolders (truncation)
- Implement `upload_report(page, xlsx_bytes, filename) -> None`: `NamedTemporaryFile(delete=False)`, `set_input_files` via Shape A, `expect_file_chooser` fallback Shape B (ADR-R2), cleanup in `try/finally`
- Implement `run_report(page, config, callbacks) -> ReportStats`: orchestrates collect → build rows → write_excel → upload, returns `ReportStats`, non-fatal (catches `ReportError` internally and calls `callbacks.on_report_error`)

**Depends on**: T-05 (_navigation.py), T-06, T-07, T-08, T-09 (all pure functions)  
**Parallel with**: T-11 (different file)  
**Estimated lines**: ~120

---

## Wave 6 — UI callbacks (extends existing RPACallbacks)

### [x] T-13 · rpa/ui.py — Add report callbacks to RPACallbacks
**Spec refs**: C-3 (report is non-fatal, TUI must show progress)  
**Design refs**: new callbacks: `on_report_start`, `on_report_subfolders`, `on_report_uploaded`, `on_report_skipped`, `on_report_error`  
**File**: `onedrive_rpa/rpa/ui.py`  
**What**:
- Add 5 new `Callable` fields to `RPACallbacks` dataclass (all default to `lambda *_: None`)
- Add `REPORT` event category to `_EVENTS` dict (icon + color)
- Implement handlers in `RPADisplay` that call `self._emit("REPORT", ...)` for each new callback

**Depends on**: T-12 (need to know exact callback signatures from `run_report`)  
**Parallel with**: T-14 (can stub callbacks in main.py in parallel if needed)  
**Estimated lines**: ~40

---

## Wave 7 — Integration and folders.json migration

### [x] T-14 · main.py — Add post-clean report hook
**Spec refs**: C-3 (auto-run after clean, non-fatal), ADR-R5 (--dry-run skips report)  
**File**: `onedrive_rpa/main.py`  
**What**:
- Import `run_report` from `reporter.py`
- After the clean loop (inside `with display, sync_playwright()` block), add:
  ```python
  if not dry_run and folders_config.report:
      run_report(page, folders_config.report, callbacks=display.callbacks)
  ```
- Handle `ReportError` as WARNING (non-fatal, no sys.exit)
- Verify `_load_folders` return type is now `FoldersConfig` (should be done by T-10)

**Depends on**: T-10 (FoldersConfig), T-12 (run_report), T-13 (callbacks)  
**Parallel with**: nothing (final integration)  
**Estimated lines**: ~20

---

### [x] T-15 · folders.json — Migrate to new object schema
**Spec refs**: C-1, C-2  
**Design refs**: ADR-R3  
**File**: `onedrive_rpa/folders.json`  
**What**:
- Migrate from legacy `[{"path": "..."}]` array to new object schema:
  ```json
  {
    "clean": [
      {"path": "pruebas/archivos_1"},
      {"path": "pruebas/archivos_2"}
    ],
    "report": {
      "folder": "Reportes",
      "subfolders": ["archivos_1", "archivos_2"]
    }
  }
  ```
- Adjust `report.folder` and `report.subfolders` to real tenant values

**Depends on**: T-14 (all code must be working before migrating live config)  
**Parallel with**: nothing (last task — do not migrate until everything is verified)  
**Estimated lines**: ~12

---

## Dependency Graph

```
T-01 ──┬──────────────────────────────────────────────────┐
       │                                                  │
T-02 ──┤                                                  │
       │                                                  ▼
       ├──► T-03 ──► T-06 ─┐                        T-10 ──► T-14 ──► T-15
       │         ├──► T-07 ─┤
       │         ├──► T-08 ─┴──► T-12 ──► T-13 ──► T-14
       │         └──► T-09 ─┘      ▲
       │                           │
       ├──► T-04 ──► T-10 ──────────┘
       │
       └──► T-05 ──► T-11
                └──► T-12
```

## Parallel waves summary

| Wave | Tasks | Can parallelize? |
|------|-------|-----------------|
| 0 | T-01, T-02 | Yes (independent) |
| 1 | T-03, T-04, T-05 | Yes (all depend only on W0) |
| 2 | T-06, T-07, T-08, T-09, T-10 | Yes (different concerns; T-06 must precede T-07/T-08/T-09 — same file) |
| 3 | T-11, T-12 | Yes (different files) |
| 4 | T-13 | Sequential (needs T-12 signatures) |
| 5 | T-14 | Sequential (needs T-10 + T-12 + T-13) |
| 6 | T-15 | Sequential, last (live config migration) |

---

## Review Workload Forecast

| Metric | Estimate |
|--------|----------|
| New files | 4 (`_navigation.py`, `reporter.py`, `tests/test_reporter.py`, `tests/test_config_loader.py`) |
| Modified files | 5 (`config.py`, `requirements.txt`, `cleaner.py`, `main.py`, `rpa/ui.py`) + `folders.json` |
| Net lines added | ~580 |
| Net lines removed | ~90 (cleaner.py extraction) |
| **Net changed** | **~490** |
| 400-line budget risk | **High** |
| Chained PRs recommended | **Yes** |
| Decision needed before apply | **Yes** |

### Suggested PR slices (if chaining)

**PR 1 — Foundation + Navigation**  
T-01, T-02, T-03, T-04, T-05, T-11 (config + test skeletons + extract navigation + cleaner refactor)  
~190 lines, low risk, no functional change

**PR 2 — Pure functions (TDD green)**  
T-06, T-07, T-08, T-09, T-10 (all pure implementations + FoldersConfig)  
~210 lines, all unit-tested

**PR 3 — Integration (Playwright + UI + folders.json)**  
T-12, T-13, T-14, T-15 (Playwright reporter + callbacks + main hook + config migration)  
~180 lines, requires manual integration testing
