# Proposal: Azulito Folders Manager

## Intent

Editing the list of folders the RPA cleans (`folders.json`) currently means opening the file by hand, knowing its JSON schema, and respecting validation rules (relative paths, no `..`) that are only enforced at RPA startup — too late, after a typo. Non-technical operators cannot safely change the target folders. This change adds an in-TUI manager inside **azulito** to list, add, and remove `clean` paths (and manage the optional `report` section) with validation at input time, removing manual file editing.

## Scope

### In Scope
- New `novahome/modules/folder_manager.py` with a `run()` entry point (CRUD over `folders.json`)
- New "Gestionar carpetas" option in the azulito menu, dispatching to the manager
- List view (Rich table: index + path), add path, remove path for the `clean` section
- Configure/clear the optional `report` section (`source_folder` + `destination_folder`, both-or-neither)
- Input-time path validation replicated locally: non-empty, relative, no `..` components
- Data-dir resolution reused from `_deps.py` (expose `DATA_DIR`); writes the modern object schema
- New `tests/test_folder_manager.py` for pure validation + read/write logic

### Out of Scope
- Any change to the RPA itself (`onedrive_rpa/`), Playwright logic, or `_validate_clean_entries()`
- Importing `onedrive_rpa` from the hub (isolation rule — validation is replicated, not imported)
- Inline path editing (edit = remove + add), reordering, or multi-select bulk operations
- New runtime dependencies

## Capabilities

### New Capabilities
- `azulito-folders-manager`: TUI CRUD over `folders.json` (`clean` list + optional `report` section) with input-time validation and shared data-dir resolution

### Modified Capabilities
- None — `azulito-launcher` only gains a menu entry; no existing requirement changes

## Approach

Approach B from exploration: a dedicated, single-responsibility module mirroring the `instalaciones.py` pattern. `azulito.run()` adds "Gestionar carpetas" and calls `folder_manager.run()`. The module locates `folders.json` via `DATA_DIR` exported from `_deps.py`, reads it (treating a missing file or legacy array as empty/upgradeable), and presents a questionary menu: view / add / remove / configure report / volver. Pure functions (validate path, load, save) are split from the questionary interaction layer so they unit-test without mocking prompts. Saves always write the modern object format. A missing-file or empty-`clean` state warns but does not block, since reconfiguration is multi-step.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `novahome/modules/folder_manager.py` | New | Full CRUD manager + pure validation/IO functions |
| `novahome/modules/azulito.py` | Modified | Add "Gestionar carpetas" choice; call `folder_manager.run()` |
| `novahome/modules/_deps.py` | Modified | Expose `DATA_DIR` (publicly) so manager finds `folders.json` |
| `tests/test_folder_manager.py` | New | Unit tests for validation + read/write |
| `folders.json` (dev or `~/.novahold/`) | Read/Written | Edited via manager; modern object schema only |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Validation drifts from RPA `_validate_clean_entries()` | Medium | Replicate exact rules; cover with tests; document the shared contract in the module docstring |
| Empty `clean` list saved → RPA `sys.exit(1)` later | Medium | Warn before saving empty list; allow it (multi-step reconfig) |
| Partial `report` section (only one field) written | Medium | Validate both-or-neither; never persist partial state |
| `folders.json` missing on first run | Low | Treat as empty config, not an error; create on first save |
| Legacy JSON array on disk | Low | Read it, silently upgrade to object format on save |
| Wrong data dir (dev vs pipx) | Low | Reuse `_deps.DATA_DIR` — single source of truth, no duplicated logic |

## Rollback Plan

Delete `novahome/modules/folder_manager.py` and `tests/test_folder_manager.py`, revert the azulito menu entry, and revert the `_deps.py` rename. No data migration; user `folders.json` files keep working since the modern object schema is unchanged.

## Dependencies

- None new. Uses existing `questionary` and `rich`.
- Reads `DATA_DIR` from `novahome/modules/_deps.py` (one-line export change).

## Success Criteria

- [ ] Azulito menu shows "Gestionar carpetas"; selecting it opens the manager
- [ ] User can list, add, and remove `clean` paths and see changes persisted to `folders.json`
- [ ] Invalid paths (absolute, containing `..`, empty) are rejected at input time with a clear message
- [ ] `report` section can be set or cleared; partial state is never written
- [ ] Manager writes to the correct `folders.json` in both dev and pipx-installed modes
- [ ] Missing/legacy `folders.json` is handled gracefully (no crash; upgraded on save)
- [ ] Zero changes to `onedrive_rpa/`; tests pass
