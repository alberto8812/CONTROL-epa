# Tasks: Azulito Folders Manager

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~180–220 |
| 400-line budget risk | Low |
| Chained PRs recommended | No |
| Suggested split | Single PR |
| Delivery strategy | single-pr |
| Chain strategy | size-exception (not needed — within budget) |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: size-exception
400-line budget risk: Low

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|-------|
| 1 | All 4 files (Foundation → Tests → Integration) | PR 1 (single) | ~200 lines, well within budget |

---

## Phase 1: Foundation

- [x] 1.1 `novahome/modules/_deps.py` — Add `DATA_DIR: Path = _DATA_DIR` after line 21 (keep `_DATA_DIR` for backward compat). Satisfies FM-8 / FM-9.
  - **Blocked by**: nothing
  - **Accept**: `from novahome.modules._deps import DATA_DIR` resolves to same path as `_DATA_DIR`

- [x] 1.2 `novahome/modules/folder_manager.py` — Define `FolderValidationError(ValueError)` and pure function stubs with docstrings: `validate_path(raw: str) -> str`, `load_folders(path: Path) -> dict`, `save_folders(path: Path, model: dict) -> None`. No interaction code yet.
  - **Blocked by**: 1.1
  - **Accept**: File importable; stubs defined (can be empty bodies)

---

## Phase 2: Tests (RED — write failing tests before implementation)

- [x] 2.1 `tests/test_folder_manager.py` — `validate_path` tests: valid relative path returns stripped path; absolute path raises `FolderValidationError`; path with `..` in any component raises `FolderValidationError`; empty/whitespace-only input raises `FolderValidationError`. Satisfies FM-2 scenarios.
  - **Blocked by**: 1.2
  - **Accept**: All 4 tests are red (fail) with stub

- [x] 2.2 `tests/test_folder_manager.py` — `load_folders` tests (use `tmp_path`): missing file → `{"clean": [], "report": None}`; legacy JSON array → `clean` list, `report=None`; modern object with report → full model; modern object without report → `report=None`. Satisfies FM-1, FM-6.
  - **Blocked by**: 1.2
  - **Accept**: All 4 tests are red

- [x] 2.3 `tests/test_folder_manager.py` — `save_folders` tests (use `tmp_path`): round-trip always writes modern object schema `{"clean": [{"path": "..."}]}`; `report=None` → key omitted in written JSON; `report` dict → key present. Satisfies FM-6 (upgrade-on-save).
  - **Blocked by**: 1.2
  - **Accept**: All 3 tests are red

---

## Phase 3: Core Logic (GREEN — make tests pass)

- [x] 3.1 `novahome/modules/folder_manager.py` — Implement `validate_path`: strip whitespace, raise `FolderValidationError` if empty, if `Path(raw).is_absolute()`, or if `'..'` in `Path(raw).parts`. Return cleaned string. Satisfies FM-2.
  - **Blocked by**: 2.1
  - **Accept**: Task 2.1 tests go green

- [x] 3.2 `novahome/modules/folder_manager.py` — Implement `load_folders`: return default model on `FileNotFoundError`; detect legacy array (`isinstance(data, list)`) → build modern model; otherwise normalize object (ensure `report` key). Satisfies FM-1, FM-6.
  - **Blocked by**: 2.2
  - **Accept**: Task 2.2 tests go green

- [x] 3.3 `novahome/modules/folder_manager.py` — Implement `save_folders`: serialize to `{"clean": [{"path": p} for p in model["clean"]], "report": ...}`, omit `report` key when value is `None`, write UTF-8 JSON with `indent=2`. Satisfies FM-6 (modern schema).
  - **Blocked by**: 2.3
  - **Accept**: Task 2.3 tests go green; `python -m pytest tests/test_folder_manager.py` passes

---

## Phase 4: Interaction Layer

- [x] 4.1 `novahome/modules/folder_manager.py` — Implement `_show_folders(model)`: Rich table with columns `#` and `Path`; if `model["clean"]` is empty print notice. Satisfies FM-1.
  - **Blocked by**: 3.2
  - **Accept**: function importable; no questionary dependency

- [x] 4.2 `novahome/modules/folder_manager.py` — Implement `_add_folder(model, data_path)`: questionary text prompt → `validate_path` loop (red error + re-prompt on `FolderValidationError`) → append → `save_folders`. Satisfies FM-2.
  - **Blocked by**: 3.1, 3.3

- [x] 4.3 `novahome/modules/folder_manager.py` — Implement `_remove_folder(model, data_path)`: guard empty list → notice + return; questionary select → confirm → remove → `save_folders`. Satisfies FM-3.
  - **Blocked by**: 3.3

- [x] 4.4 `novahome/modules/folder_manager.py` — Implement `_report_subflow(model, data_path)`: show current; Configurar branch prompts both fields, re-prompts until both non-empty or both empty; Quitar branch confirms then sets `report=None`; Ctrl+C returns to parent. Satisfies FM-4, FM-5.
  - **Blocked by**: 3.3

- [x] 4.5 `novahome/modules/folder_manager.py` — Implement `run()`: top-level questionary select loop with choices `["Ver carpetas configuradas", "Agregar carpeta a limpiar", "Eliminar carpeta de la lista", "Configurar sección de reportes", "Volver"]`; dispatch to sub-functions; on save with empty `clean` show yellow warning + `questionary.confirm` before writing. Satisfies FM-1 through FM-7.
  - **Blocked by**: 4.1, 4.2, 4.3, 4.4

---

## Phase 5: Integration

- [x] 5.1 `novahome/modules/azulito.py` — In `run()` at line 167, update `choices` list to `["Eliminar archivos OneDrive", "Gestionar carpetas", "Volver"]`; add branch `if choice == "Gestionar carpetas": from novahome.modules import folder_manager; folder_manager.run()`. Satisfies FM-7 / FM-8.
  - **Blocked by**: 4.5
  - **Accept**: No other branch in `run()` modified; existing behavior untouched

---

## Phase 6: Verification

- [x] 6.1 Run `python -m pytest tests/test_folder_manager.py -v` — all tests green.
  - **Blocked by**: Phase 3 complete

- [ ] 6.2 Smoke test TUI path: launch hub, navigate to azulito → "Gestionar carpetas", exercise each menu option manually once.
  - **Blocked by**: 5.1

- [ ] 6.3 Verify `folders.json` round-trip: start with legacy array format, run Add + Remove, confirm written file uses modern object schema.
  - **Blocked by**: 5.1
