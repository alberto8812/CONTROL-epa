# Design: OneDrive Folder Report (auto post-clean + upload)

**Project**: control-epa
**Change**: onedrive-folder-report
**Phase**: design
**Date**: 2026-05-22

---

## 1. Architectural Approach

- Layered, single-responsibility modules — same pattern as the rest of the codebase.
- `main.py` stays as the single Click command and orchestrator. Gains one new step at the end: "run the report".
- `rpa/cleaner.py` keeps its public surface unchanged. Two private helpers (`_navigate_to_folder`, `_list_items`) are **extracted** into a new module.
- **`rpa/_navigation.py`** (NEW) — shared Playwright navigation primitives.
- **`rpa/reporter.py`** (NEW) — report pipeline.

The reporter does NOT depend on the cleaner. They are siblings, both consumers of `_navigation`.

---

## 2. Architecture Decisions (ADR-style)

### ADR-R1 — Extract navigation helpers to `rpa/_navigation.py`

**Decision**: move `_navigate_to_folder(page, folder_path)` and `_list_items(page) -> list[ItemInfo]` into `rpa/_navigation.py`. Re-export `FolderNotFoundError` from `cleaner.py` for backward compat.

**Rejected**:
- Rename in-place (drop `_`): leaks "navigation" into a module whose name says "cleaner". Bad coupling.
- Re-export aliases from `cleaner.py`: same coupling problem, plus hides the real source.

**Why**: the reporter is a peer use case. Navigation primitives are shared infrastructure — same level as `_retry.py`. Extraction respects Screaming Architecture.

Naming: drop underscore on exported names (`navigate_to_folder`, `list_items`, `ItemInfo`) — intra-package public surface. Module itself keeps `_` prefix.

---

### ADR-R2 — Excel upload uses temp file via `tempfile.NamedTemporaryFile`

**Decision**: `write_excel(rows) -> bytes` returns workbook bytes (in-memory via `BytesIO`). `upload_report(page, excel_bytes, destination_folder, filename)` writes to `NamedTemporaryFile(suffix=".xlsx", delete=False)`, calls `page.set_input_files(hidden_input, temp_path)`, waits for upload confirmation, deletes temp file in `finally`.

**Why**: Playwright's `FilePayload` (in-memory) is unreliable with OneDrive's SPO upload handler. Real path is the conservative, well-understood option.

**Cleanup**: `delete=False` required on Windows (exclusive lock). Close handle first, hand path to Playwright, then `os.unlink` in `finally`.

---

### ADR-R3 — `folders.json` schema migration with backward compatibility

**Decision**: `_load_folders` accepts both array and object shapes, normalizing to:

```python
@dataclass(frozen=True)
class ReportConfig:
    source_folder: str
    destination_folder: str

@dataclass(frozen=True)
class FoldersConfig:
    clean: list[dict]
    report: ReportConfig | None
```

Loader logic:
1. Parse JSON.
2. Root is `list` → legacy mode: `clean = list`, `report = None`. Log INFO about migration.
3. Root is `dict` → modern mode: parse `clean` + optional `report`.
4. Half-configured `report` (one field missing/empty) → `ConfigError` + exit 1.
5. Anything else → `ConfigError` + exit 1.

---

### ADR-R4 — Report filename format

**Decision**: `reporte_{YYYYMMDD}_{HHMMSS}.xlsx` (local time). Example: `reporte_20260522_143052.xlsx`.

**Why**: sorts lexicographically; filesystem-safe; `reporte` matches Spanish-language context.

---

### ADR-R5 — Reporter is opt-in via config, never via CLI

**Decision**: if `folders.json` has no `report` key, report step silently skipped with INFO log. No CLI flag.

- `--dry-run` → skip report. Log `REPORT | SKIPPED | reason=dry_run`.
- `SessionExpiredError` → already exited; report never runs.
- Clean had errors but completed → report still runs.

---

### ADR-R6 — Password generation

**Decision**: 24 chars from `string.ascii_letters + string.digits + "!@#$%^&*()-_=+[]{}|;:,.<>?"` using `secrets.choice`. Hardcoded in `config.py`.

Excluded: `"`, `'`, `\`, backtick. Entropy: ~157 bits.

---

### ADR-R7 — Selectors in `config.py → SELECTORS`

All new upload-related selectors go into existing dict. `data-automationid`-first per codebase convention.

---

## 3. Module Structure & Signatures

### `rpa/_navigation.py` (NEW)

```python
class ItemInfo(NamedTuple):
    name: str
    is_folder: bool

class FolderNotFoundError(Exception): ...

@with_retry()
def navigate_to_folder(page: Page, folder_path: str) -> None: ...

@with_retry()
def list_items(page: Page) -> list[ItemInfo]: ...
```

`cleaner.py` re-exports `FolderNotFoundError` to preserve existing imports in `main.py`.

---

### `rpa/reporter.py` (NEW)

```python
@dataclass
class ReportStats:
    subfolders_found: int = 0
    rows_generated: int = 0
    uploaded_filename: str | None = None
    skipped_reason: str | None = None
    errors: list[str] = field(default_factory=list)

# Pure — unit-testable without Playwright
def generate_password(length: int = REPORT_PASSWORD_LENGTH) -> str: ...
def build_report_rows(folder_names: list[str], *, now: datetime | None = None) -> list[dict]: ...
def write_excel(rows: list[dict]) -> bytes: ...
def build_report_filename(now: datetime | None = None) -> str: ...

# Playwright-bound
def collect_subfolders(page: Page, source_folder: str) -> list[str]: ...
def upload_report(page: Page, excel_bytes: bytes, destination_folder: str, filename: str) -> None: ...

# Orchestrator
def run_report(page: Page, source_folder: str, destination_folder: str, *, callbacks: RPACallbacks | None = None) -> ReportStats: ...
```

---

### `main.py` changes (surgical)

1. `_load_folders` returns `FoldersConfig` instead of `list[dict]`.
2. `folder_paths = [f["path"] for f in folders_config.clean]`.
3. After clean loop, before `_emit_summary`:

```python
if folders_config.report is not None and not dry_run:
    report_stats = run_report(page, folders_config.report.source_folder,
                               folders_config.report.destination_folder,
                               callbacks=display.callbacks)
    _emit_report_summary(report_stats)
elif folders_config.report is not None and dry_run:
    logger.info("REPORT | SKIPPED | reason=dry_run")
```

Report errors do NOT change the exit code.

---

### `config.py` additions

```python
REPORT_PASSWORD_LENGTH: int = 24
REPORT_PASSWORD_ALPHABET: str = (
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "abcdefghijklmnopqrstuvwxyz"
    "0123456789"
    "!@#$%^&*()-_=+[]{}|;:,.<>?"
)
REPORT_FILENAME_PREFIX: str = "reporte"
REPORT_FILENAME_TIMESTAMP_FORMAT: str = "%Y%m%d_%H%M%S"
UPLOAD_TIMEOUT_MS: int = 60_000
```

---

## 4. Data Flow

```
folders.json
    |
    v
_load_folders --> FoldersConfig{clean=[...], report=ReportConfig|None}
    |
    v
main.py:
    1. confirm (if not dry_run, not --yes)
    2. load_or_login() --> (browser, context, page)
    3. for folder in clean:
          FolderCleaner.clean(folder) --> CleanStats
    4. if report and not dry_run:
          run_report(page, source, destination)
    5. _emit_summary + _emit_report_summary

run_report(page, source, destination):
    collect_subfolders(page, source)
        -> navigate_to_folder(page, source)
        -> list_items(page) -> filter is_folder -> [names]
    build_report_rows(names)
        -> [{folder_name, generate_password(), creation_date=datetime.now()}]
    write_excel(rows) -> bytes (BytesIO)
    build_report_filename() -> str
    upload_report(page, bytes, destination, filename)
        -> navigate_to_folder(page, destination)
        -> NamedTemporaryFile(suffix=".xlsx") -> path
        -> click "Upload" toolbar button
        -> page.set_input_files(hidden_input, path)
        -> wait for row with name=filename
        -> os.unlink(path) in finally
    return ReportStats(...)
```

---

## 5. Upload Flow — Playwright Steps

**Shape A** (preferred — direct hidden input):

```python
def upload_report(page, excel_bytes, destination_folder, filename):
    navigate_to_folder(page, destination_folder)

    tmp = tempfile.NamedTemporaryFile(prefix="onedrive_report_", suffix=".xlsx", delete=False)
    target_tmp = None
    try:
        tmp.write(excel_bytes)
        tmp.close()
        target_tmp = Path(tmp.name).with_name(filename)
        os.replace(tmp.name, target_tmp)

        hidden_input = page.locator(SELECTORS["upload_file_input"])
        hidden_input.wait_for(state="attached", timeout=ACTION_TIMEOUT_MS)
        hidden_input.set_input_files(str(target_tmp))

        page.wait_for_selector(
            f'{SELECTORS["folder_row"]}:has({SELECTORS["item_name"]}:text-is("{filename}"))',
            timeout=UPLOAD_TIMEOUT_MS,
            state="visible",
        )
    finally:
        for p in (Path(tmp.name), target_tmp):
            if p and Path(p).exists():
                try: os.unlink(p)
                except OSError: pass
```

**Shape B** (fallback — `expect_file_chooser` when hidden input isn't pre-mounted):
Try Shape A first; if `hidden_input.wait_for(timeout=3_000)` fails, fall through to Shape B via `page.expect_file_chooser()` while clicking the Upload menu item.

**Why wait for the row by name**: SPO returns 200 before list-virtualization refreshes. Visible row is the only reliable "upload done" signal.

---

## 6. New Selectors

```python
"toolbar_upload": (
    "[data-automationid='uploadCommand'], "
    "button[name='Cargar'], button[name='Upload'], "
    "button[aria-label='Cargar'], button[aria-label='Upload']"
),
"upload_files_menuitem": (
    "[role='menuitem'][name='Archivos'], "
    "[role='menuitem'][name='Files'], "
    "[data-automationid='uploadFilesCommand']"
),
"upload_file_input": "input[type='file']",
```

---

## 7. `folders.json` Migration Examples

**Legacy** (report disabled):
```json
[{"path": "pruebas/archivos_1"}, {"path": "pruebas/archivos_2"}]
```

**Modern** (report enabled):
```json
{
  "clean": [{"path": "pruebas/archivos_1"}, {"path": "pruebas/archivos_2"}],
  "report": {
    "source_folder": "Documents/registros",
    "destination_folder": "Documents/reportes"
  }
}
```

**Modern, explicit opt-out**:
```json
{"clean": [{"path": "pruebas/archivos_1"}], "report": null}
```

---

## 8. Testing Strategy

| Function | Bound to | Test type |
|---|---|---|
| `generate_password` | stdlib | Unit: length, alphabet membership, no `"`/`'` in 10k samples |
| `build_report_rows` | none | Unit: row count, password unique, `creation_date` == injected `now` |
| `write_excel` | openpyxl | Unit: round-trip via `load_workbook(BytesIO(bytes))`, header + rows |
| `build_report_filename` | none | Unit: regex `^reporte_\d{8}_\d{6}\.xlsx$` |
| `_load_folders` | filesystem | Unit: fixtures, assert `FoldersConfig` shape (legacy + modern) |
| `collect_subfolders` | Playwright | Manual integration |
| `upload_report` | Playwright | Manual integration |
| `run_report` | Playwright | Manual integration |

Pure functions are strictly TDD during apply. Playwright-bound functions: manual integration only (no test infra exists).

---

## 9. RPACallbacks Integration

New callbacks (defaults = no-ops, backward compatible):

```python
on_report_start:      Callable[[str, str], None]   # source, destination
on_report_subfolders: Callable[[int], None]         # count
on_report_uploaded:   Callable[[str], None]         # filename
on_report_skipped:    Callable[[str], None]         # reason
on_report_error:      Callable[[str], None]         # message
```

New TUI event categories: `REPORT` (icon `▣`), `UPLOAD` (icon `↑`).

Loguru log lines:
```
REPORT_BEGIN | source={s} | destination={d}
REPORT_SUBFOLDERS | count={n} | source={s}
REPORT_UPLOADED | filename={f} | destination={d}
REPORT_SKIPPED | reason={r}
REPORT_ERROR | reason={r}
REPORT_END | rows={n} | uploaded={bool} | elapsed={s:.1f}s
```

---

## 10. Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| List virtualization truncates `collect_subfolders` for >50 subfolders | Med | Silent under-report | WARN at >= 50; v2: scroll-to-load |
| `uploadCommand` selector missing on tenant | Med | Blocks upload | Multi-selector with `aria-label` fallback |
| `set_input_files` fails (no hidden input mounted) | Med | Blocks upload | Shape B fallback via `expect_file_chooser` |
| OneDrive renames file on conflict (`reporte_..._1.xlsx`) | Low | Wrong wait selector | Search by prefix, not exact name |
| User keeps legacy `folders.json` | Med | Report silently skipped | Loud INFO log; document in README |
| Temp file leak on SIGKILL | Low | Disk leak | OS temp dir; auto-cleaned next boot |

---

## 11. Out of Scope

- Recursive subfolder enumeration
- Scroll-to-load for >50 subfolders
- File encryption at rest
- Email delivery
- `--no-report` CLI flag
- `creation_date` from OneDrive metadata (uses `datetime.now()`)
