# Azulito Folders Manager — Specification

## Purpose

New TUI module inside the novahome hub that provides CRUD over `folders.json` (`clean` list + optional `report` section) with input-time path validation. Removes the need for manual JSON editing by non-technical operators.

## Capabilities

| ID | Capability | Type | Module |
|----|-----------|------|--------|
| FM-1 | List configured clean paths | New | `folder_manager.py` |
| FM-2 | Add a valid clean path | New | `folder_manager.py` |
| FM-3 | Remove a clean path | New | `folder_manager.py` |
| FM-4 | Configure report section | New | `folder_manager.py` |
| FM-5 | Clear report section | New | `folder_manager.py` |
| FM-6 | Graceful handling of missing/legacy folders.json | New | `folder_manager.py` |
| FM-7 | Azulito menu entry dispatching to manager | New | `azulito.py` |
| FM-8 | Expose DATA_DIR from _deps.py | New | `_deps.py` |

---

## Requirements

### Requirement: FM-1 List Clean Paths

The system MUST display all entries in the `clean` section as a Rich table with index and path. If the list is empty, a notice MUST be shown instead of an empty table.

#### Scenario: Non-empty list

- GIVEN `folders.json` contains two clean paths
- WHEN the user selects "Ver carpetas configuradas"
- THEN a Rich table shows each path with its 1-based index
- AND the menu returns after display

#### Scenario: Empty list

- GIVEN the `clean` list is empty
- WHEN the user selects "Ver carpetas configuradas"
- THEN a notice indicates no folders are configured

---

### Requirement: FM-2 Add Valid Clean Path

The system MUST validate the input path before appending it. A path MUST be non-empty after stripping whitespace, MUST NOT be absolute, and MUST NOT contain `..` in any path component. On success the path is appended and `folders.json` is written.

#### Scenario: Valid relative path

- GIVEN the manager is open
- WHEN the user enters `pruebas/archivos_1`
- THEN the path is appended to `clean` and persisted

#### Scenario: Absolute path rejected

- GIVEN the manager is open
- WHEN the user enters `/absolute/path`
- THEN a validation error is shown and the user is re-prompted; nothing is written

#### Scenario: Path with `..` rejected

- GIVEN the manager is open
- WHEN the user enters `../sibling`
- THEN a validation error is shown and the user is re-prompted; nothing is written

#### Scenario: Empty input rejected

- GIVEN the manager is open
- WHEN the user submits an empty string
- THEN a validation error is shown and the user is re-prompted; nothing is written

---

### Requirement: FM-3 Remove Clean Path

The system MUST present existing paths as a selectable list. After the user selects one and confirms, the path MUST be removed and `folders.json` written.

#### Scenario: Remove existing path

- GIVEN `clean` has at least one path
- WHEN the user selects it and confirms removal
- THEN the path is removed and `folders.json` is updated

#### Scenario: Empty list blocks removal

- GIVEN `clean` is empty
- WHEN the user selects "Eliminar carpeta de la lista"
- THEN a notice is shown; no prompt is presented

---

### Requirement: FM-4 Configure Report Section

Both `source_folder` and `destination_folder` MUST be set together. A partial state (one field set, one empty) MUST NOT be persisted; the system MUST re-prompt until both are provided or the user cancels.

#### Scenario: Both fields provided

- GIVEN the report sub-flow is active
- WHEN the user supplies both `source_folder` and `destination_folder`
- THEN the `report` section is set and `folders.json` is written

#### Scenario: Partial report rejected

- GIVEN the report sub-flow is active
- WHEN the user provides only one field
- THEN the system re-prompts; no partial state is written

---

### Requirement: FM-5 Clear Report Section

The system MUST allow clearing the `report` section. After confirmation the field MUST be omitted from the written JSON.

#### Scenario: Clear existing report

- GIVEN `folders.json` has a `report` section
- WHEN the user selects "Quitar reporte" and confirms
- THEN the written `folders.json` has no `report` key

---

### Requirement: FM-6 Missing and Legacy folders.json Handling

A missing `folders.json` MUST be treated as an empty config (not an error). A legacy JSON array MUST be read as the `clean` list. Both MUST be written in modern object schema on any save.

#### Scenario: Missing file

- GIVEN `folders.json` does not exist
- WHEN the manager loads
- THEN the in-memory model is `{"clean": [], "report": None}`; no error is raised

#### Scenario: Legacy array format

- GIVEN `folders.json` contains a JSON array of path strings
- WHEN the manager loads and the user saves
- THEN the written file uses the modern object schema `{"clean": [{"path": "..."}]}`

---

### Requirement: FM-7 Empty Clean List Warning

When the user saves with an empty `clean` list, the system MUST display a warning and require explicit confirmation before writing.

#### Scenario: Save empty list with confirmation

- GIVEN `clean` is empty after a removal
- WHEN the user triggers save
- THEN a warning is displayed and the user is asked to confirm
- AND the file is only written after confirmation

---

### Requirement: FM-8 Azulito Menu Entry

`azulito.run()` MUST include a "Gestionar carpetas" choice that dispatches to `folder_manager.run()`. No other existing azulito behavior MUST change.

#### Scenario: Navigate to manager

- GIVEN the azulito TUI is running
- WHEN the user selects "Gestionar carpetas"
- THEN `folder_manager.run()` is called

---

### Requirement: FM-9 DATA_DIR Public Export

`_deps.py` MUST export `DATA_DIR` as a public `Path` constant pointing to the resolved data directory. The private `_DATA_DIR` MUST remain for backward compatibility.

#### Scenario: Import DATA_DIR

- GIVEN `_deps.py` is imported
- WHEN `from novahome.modules._deps import DATA_DIR` is used
- THEN `DATA_DIR` resolves to the same path as `_DATA_DIR`

---

## Non-Functional Requirements

- MUST NOT introduce new runtime dependencies (questionary + rich already present).
- MUST NOT modify any file under `onedrive_rpa/`.
- Validation rules MUST mirror `_validate_clean_entries()` exactly; contract MUST be documented in the module docstring.
- All pure functions (`validate_path`, `load_folders`, `save_folders`) MUST be unit-testable without mocking questionary.

---

## Out of Scope

- Inline path editing (edit = remove + add)
- Reordering or bulk operations
- Importing from `onedrive_rpa` into the hub
- Any change to `onedrive_rpa/` or `_validate_clean_entries()`
