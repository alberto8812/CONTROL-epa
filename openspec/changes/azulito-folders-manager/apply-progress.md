# Apply Progress: azulito-folders-manager

**Mode**: Strict TDD (RED → GREEN → REFACTOR)
**Status**: 14/16 tasks complete (6.2 and 6.3 are manual smoke tests)

## TDD Cycle Evidence

| Task | RED (tests written first) | GREEN (implementation) | REFACTOR |
|------|--------------------------|------------------------|----------|
| 2.1 validate_path tests | PASS — 7 tests, all failed against stub | — | — |
| 2.2 load_folders tests | PASS — 6 tests, all failed against stub | — | — |
| 2.3 save_folders tests | PASS — 4 tests, all failed against stub | — | — |
| 3.1 validate_path impl | — | PASS — 7 tests green | N/A |
| 3.2 load_folders impl | — | PASS — 6 tests green | N/A |
| 3.3 save_folders impl | — | PASS — 4 tests green | N/A |
| Full suite (73 tests) | — | PASS — 73/73 | N/A |

## Completed Tasks

- [x] 1.1 `novahome/modules/_deps.py` — Added `DATA_DIR: Path = _DATA_DIR` public alias on line 22
- [x] 1.2 `novahome/modules/folder_manager.py` — Created with `FolderValidationError`, pure function stubs + interaction layer
- [x] 2.1 `tests/test_folder_manager.py` — 7 validate_path tests (RED confirmed: 17 failures)
- [x] 2.2 `tests/test_folder_manager.py` — 6 load_folders tests (RED confirmed)
- [x] 2.3 `tests/test_folder_manager.py` — 4 save_folders tests (RED confirmed)
- [x] 3.1 `validate_path` implemented — strip + is_absolute() + '..' in parts checks
- [x] 3.2 `load_folders` implemented — FileNotFoundError default, legacy array, modern object
- [x] 3.3 `save_folders` implemented — modern schema, report key omitted when None
- [x] 4.1 `_show_folders` implemented — Rich table with # / Path columns, empty notice
- [x] 4.2 `_add_folder` implemented — validate_path loop, re-prompt on FolderValidationError
- [x] 4.3 `_remove_folder` implemented — empty guard, questionary select + confirm
- [x] 4.4 `_report_subflow` implemented — show current, Configurar (both-or-neither), Quitar, Volver
- [x] 4.5 `run()` implemented — top-level select loop, all dispatchers, Ctrl+C handling
- [x] 5.1 `novahome/modules/azulito.py` — Added "Gestionar carpetas" choice + dispatch
- [x] 6.1 `python3 -m pytest tests/test_folder_manager.py -v` — 17/17 passed; full suite 73/73 passed
- [ ] 6.2 Manual smoke test TUI — requires interactive terminal
- [ ] 6.3 Manual folders.json round-trip verification — requires interactive terminal

## Files Changed

| File | Action | Notes |
|------|--------|-------|
| `novahome/modules/_deps.py` | Modified | Added DATA_DIR public alias (1 line) |
| `novahome/modules/folder_manager.py` | Created | Pure functions + interaction layer (~200 lines) |
| `tests/test_folder_manager.py` | Created | 17 unit tests for pure functions |
| `novahome/modules/azulito.py` | Modified | "Gestionar carpetas" menu entry + dispatch |

## Test Results

```
73 passed in 10.85s
```

All automated tasks complete. Tasks 6.2 and 6.3 are manual verification steps.
