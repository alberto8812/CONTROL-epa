# Proposal: OneDrive Folder Report

**Updated**: 2026-05-22 — scope corrected after user clarification

## Intent

After the existing OneDrive deletion process completes (all folders in `folders.json` cleaned), the system automatically navigates to a predefined `source_folder`, enumerates its immediate subfolders, generates an Excel report with `folder_name`, a high-security `password` (no `"` or `'`), and `creation_date`, then uploads the Excel directly to a `destination_folder` in OneDrive via Playwright. No manual step, no local file artifact.

## Scope

### In Scope
- Auto-run report step at end of existing clean loop in `main.py` — no new CLI subcommand
- Extend `folders.json` schema with a `report` block (`source_folder`, `destination_folder`)
- Navigate `source_folder` in OneDrive, enumerate immediate subfolders
- Generate Excel in-memory via `openpyxl`: columns Folder Name, Password, Creation Date
- Upload Excel to `destination_folder` via Playwright file upload
- Backward compat: old array-format `folders.json` still works (report step skipped)
- New module `onedrive_rpa/rpa/reporter.py` with pure + Playwright-bound functions

### Out of Scope
- New CLI subcommand or Click group refactor
- Recursive subfolder enumeration (v1: immediate children only)
- Local Excel file artifact (file goes to OneDrive only)
- Integration with NovaHome Hub menu (separate change)
- DOM virtualization workaround for >50 subfolders (v1 limitation, documented)

## folders.json schema extension

```json
{
  "clean": [{"path": "Documents/folder1"}],
  "report": {
    "source_folder": "Documents/registros",
    "destination_folder": "Documents/reportes"
  }
}
```

Backward compat: if root is an array → treat as `{"clean": <array>, "report": null}` and skip report step.

## New module: `rpa/reporter.py`

```
collect_subfolders(page, folder_path) → list[str]        # Playwright-bound
generate_password(length=24) → str                        # secrets, no quotes
build_report_rows(folder_names) → list[dict]              # pure function
write_excel(rows) → bytes                                 # openpyxl, in-memory
upload_report(page, excel_bytes, dest, filename) → None  # Playwright upload
```

## Integration point

`main.py` — after the clean loop, before exit:
```python
if config.report:
    run_report_step(page, config)
```

## Affected Files

| File | Change |
|------|--------|
| `onedrive_rpa/main.py` | Add `run_report_step()` call after clean loop |
| `onedrive_rpa/config.py` | Add `REPORT_FILENAME_PREFIX` constant |
| `onedrive_rpa/rpa/cleaner.py` | Expose navigation helpers as importable |
| `onedrive_rpa/rpa/reporter.py` | **New** — all report logic |
| `onedrive_rpa/requirements.txt` | Add `openpyxl` |
| `onedrive_rpa/folders.json` | Schema migration to object |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| DOM virtualization truncates subfolder list for >50 items | Med | Document as v1 limitation; log warning at threshold |
| Playwright upload requires temp file on disk | Med | Use `NamedTemporaryFile` + cleanup in finally block |
| `cleaner.py` private refactor breaks delete flow | Med | Thin public wrappers; keep internal logic intact |
| Password contains forbidden chars | Low | Explicit alphabet; assert in tests |

## Success Criteria

- [ ] After clean loop completes, Excel is created and uploaded to `destination_folder` automatically
- [ ] Each password is ≥24 chars, no `"` or `'`, unique per row per run
- [ ] Old `folders.json` array format still works (report step silently skipped)
- [ ] `generate_password()` and `build_report_rows()` importable without Playwright
