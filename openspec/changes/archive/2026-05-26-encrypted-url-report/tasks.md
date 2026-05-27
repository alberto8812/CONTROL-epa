# Tasks: Encrypted URL Column in OneDrive Report

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 130–160 |
| 400-line budget risk | Low |
| Chained PRs recommended | No |
| Suggested split | Single PR |
| Delivery strategy | ask-on-risk |
| Chain strategy | N/A |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: size-exception
400-line budget risk: Low

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|-------|
| 1 | All changes + tests | PR 1 | Single PR; ~130–160 lines; well within 400-line budget |

---

## Phase 1: Foundation / Infrastructure

- [x] 1.1 `onedrive_rpa/requirements.txt` — append `cryptography>=42.0.0` after `openpyxl` line
- [x] 1.2 `onedrive_rpa/config.py` — add `SHAREPOINT_PERSONAL_PATH` read (already present); add `_build_fernet(key)` helper: `try: return Fernet(key) except Exception: logger.warning(...); return None`; add `FERNET: Fernet | None = _build_fernet(os.getenv("FOLDERS_ENCRYPTION_KEY", "").encode()) if os.getenv("FOLDERS_ENCRYPTION_KEY") else None`. Import `Fernet` from `cryptography.fernet` and `logger` from `loguru` at top of file. (EU-2, EU-3, EU-6)

## Phase 2: Core Implementation

- [x] 2.1 `onedrive_rpa/rpa/reporter.py` — add `_build_folder_url(source_folder: str, name: str) -> str` helper: join `[config.ONEDRIVE_URL.rstrip('/')]` + `[seg.strip('/') for seg in [config.SHAREPOINT_PERSONAL_PATH, 'Documents', source_folder, name] if seg.strip('/')]` with `/`. Use `urllib.parse.quote` on each path segment (not the scheme/host). (EU-5, spec: URL Assembly, Trailing slash)
- [x] 2.2 `onedrive_rpa/rpa/reporter.py` — update `build_report_rows` signature to `(folder_names, *, now=None, source_folder='', fernet=None)`. Inside body: `active = fernet or config.FERNET`; compute `url = _build_folder_url(source_folder, name)`; set `encrypted_url = active.encrypt(url.encode()).decode('ascii') if active else ''`; include `encrypted_url` key in each row dict. (EU-2, spec: Non-deterministic Encryption, Graceful No-Key Fallback, Backward-Compatible Signature)
- [x] 2.3 `onedrive_rpa/rpa/reporter.py` — update `write_excel`: change `headers` to `["Folder Name", "Password", "Encrypted URL", "Creation Date"]`; update `ws.append` to `[row["folder_name"], row["password"], row.get("encrypted_url", ""), row["creation_date"]]`. (EU-4, spec: Excel Column Order)
- [x] 2.4 `onedrive_rpa/rpa/reporter.py` — update `run_report`: change `build_report_rows(subfolders)` call to `build_report_rows(subfolders, source_folder=source_folder, fernet=config.FERNET)`. (spec: run_report Propagates Context)
- [x] 2.5 `novahome/modules/azulito.py` — in `configure_env()`, after the three existing prompts and before `ENV_PATH.parent.mkdir(...)`: add optional key-gen step using `questionary.confirm`. If `FOLDERS_ENCRYPTION_KEY` already in `existing` → prompt "Key already exists. Regenerate? (default No)" with `default=False`; if confirmed or key absent → generate via `Fernet.generate_key().decode('ascii')` and set `merged["FOLDERS_ENCRYPTION_KEY"] = new_key`; else skip. Import `Fernet` locally inside the step. (EU-7, spec: Wizard Key Generation Step)

## Phase 3: Testing

- [x] 3.1 `tests/test_reporter.py` — add `TestBuildFolderUrl` class: test clean segments produce correct URL (spec: URL assembled correctly); test trailing slash in `source_folder` produces no double-slash (spec: Trailing slash normalised); test empty `source_folder` still produces valid URL
- [x] 3.2 `tests/test_reporter.py` — add `TestBuildReportRowsEncryption` class: test `encrypted_url` key present in each row when valid `Fernet` injected (spec: Encrypted URL column populated); test two calls with same inputs produce different ciphertext (spec: Non-deterministic output); test `fernet=None` yields `encrypted_url == ""` for all rows without raising (spec: No key — column is empty string)
- [x] 3.3 `tests/test_reporter.py` — add `TestBuildReportRowsBackwardCompat` class: verify existing calls without `source_folder`/`fernet` still return rows with `folder_name`, `password`, `creation_date` (spec: Existing call without new kwargs succeeds); verify row count unchanged
- [x] 3.4 `tests/test_reporter.py` — update `TestWriteExcel.test_write_excel_round_trip`: add assertion `assertIn("Encrypted URL", headers)` and verify column-3 (index 2) value in data rows equals `row.get("encrypted_url", "")` (spec: Header row correct, Data row populated)
- [x] 3.5 `tests/test_reporter.py` — add `TestConfigFernet` class: test `config.FERNET is None` when env var absent; test `config.FERNET is None` when env var contains invalid bytes (spec: Invalid key — treated identically to absent key). Use `unittest.mock.patch.dict(os.environ, ...)` and force reimport or test `_build_fernet` directly.

## Phase 4: Cleanup

- [x] 4.1 `onedrive_rpa/config.py` — add docstring to `FERNET` constant and `_build_fernet` explaining fail-open contract (EU-1, EU-3)
- [x] 4.2 Verify `python -m unittest discover -s tests -q` passes green — 30/30 tests, no regressions
