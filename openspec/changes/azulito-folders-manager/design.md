# Design: Azulito Folders Manager

## Technical Approach

Approach B from exploration: a dedicated `novahome/modules/folder_manager.py` mirroring the `instalaciones.py` module shape (own `run()`, called from the azulito router). The module splits into two layers: **pure functions** (validation + load/save, no I/O prompts) and an **interaction layer** (questionary/Rich) that calls them. `_deps.py` exposes the already-resolved data dir publicly so the manager writes the exact `folders.json` the RPA reads. Validation rules from `onedrive_rpa/main.py::_validate_clean_entries()` are replicated locally (no cross-import) to keep hub/RPA isolated. The module always writes the modern object schema; it reads legacy arrays and silently upgrades on save.

## Architecture Decisions

| Decision | Choice | Rejected | Rationale |
|----------|--------|----------|-----------|
| Module placement | New `folder_manager.py` | Inline in `azulito.py` (A); extend `configure_env()` (C) | CRUD surface > a wizard; matches `instalaciones.py` per-feature module pattern; testable in isolation |
| Validation source | Replicate rules locally as pure fns | Import `_validate_clean_entries` from `onedrive_rpa` | Hub must not depend on RPA package (isolation); rules are 3 lines, contract documented + tested |
| Data dir | Reuse `_deps` resolved dir | Re-resolve locally | Single source of truth; already correct for dev + pipx |
| Pure/interaction split | `validate_path/load_folders/save_folders` pure, prompts separate | One monolithic flow fn | Unit-test pure logic with plain asserts, no questionary mocking |
| Schema written | Always modern object | Preserve legacy array | RPA report feature needs object schema; upgrade-on-save is lossless |
| Empty `clean` | Warn (confirm) but allow save | Block save | User may save mid-reconfig; RPA enforces non-empty at startup (exit 1) |
| `report` partial | Reject; both-or-neither | Persist partial | Mirrors RPA `_load_folders` contract (both non-empty or absent) |

## Data Flow

```
azulito.run() ─"Gestionar carpetas"─→ folder_manager.run()
                                          │
        interaction layer (questionary/Rich)
                                          │
            ┌─────────────┴─────────────┐
       load_folders(path)          save_folders(path, model)
            │  (pure)                    │  (pure)
            ▼                            ▼
   _deps.DATA_DIR / "folders.json"  ←────┘   (same file RPA reads)
```

In-memory model (plain dict, no new types needed):

```python
# FoldersModel
{
  "clean": ["pruebas/archivos_1", ...],        # list[str] of validated relative paths
  "report": {"source_folder": str, "destination_folder": str} | None,
}
```

`load_folders` normalizes both schemas into this shape; `save_folders` serializes back to the modern object form: `{"clean": [{"path": p} for p in clean], "report": report_or_omitted}`.

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `novahome/modules/folder_manager.py` | Create | Pure fns (`validate_path`, `load_folders`, `save_folders`) + interaction `run()` and sub-flows |
| `novahome/modules/_deps.py` | Modify | Add `DATA_DIR: Path = _DATA_DIR` public alias (keep `_DATA_DIR` for back-compat) |
| `novahome/modules/azulito.py` | Modify | Add `"Gestionar carpetas"` choice in `run()`; on select call `folder_manager.run()` |
| `tests/test_folder_manager.py` | Create | Unit tests for pure fns only |

`_deps.py` exact line (after L21 `_DATA_DIR` assignment): `DATA_DIR: Path = _DATA_DIR`.

`azulito.py` exact spot: in `run()` (L166) change choices to `["Eliminar archivos OneDrive", "Gestionar carpetas", "Volver"]`; add branch `if choice == "Gestionar carpetas": from novahome.modules import folder_manager; folder_manager.run()`.

## Interfaces / Contracts

```python
class FolderValidationError(ValueError): ...

def validate_path(raw: str) -> str:
    """Strip + validate one clean path. Rules (mirror RPA _validate_clean_entries):
    non-empty after strip, relative (not Path.is_absolute()), no '..' in Path.parts.
    Returns the cleaned path or raises FolderValidationError."""

def load_folders(path: Path) -> dict:
    """Return FoldersModel. Missing file → {"clean": [], "report": None}.
    Legacy array → clean paths, report=None. Object → clean+report normalized.
    Pure read; never exits."""

def save_folders(path: Path, model: dict) -> None:
    """Serialize FoldersModel to modern object schema, write UTF-8 JSON (indent=2)."""
```

`report` validation in interaction layer: both `source_folder` and `destination_folder` non-empty after strip → set; both empty → `report = None`; one of two → re-prompt (never persist partial).

## UX Flow (questionary)

```
Gestionar carpetas — folders.json:
  > Ver carpetas configuradas        (Rich table: # | path; then return)
  > Agregar carpeta a limpiar        (text → validate_path → append → save)
  > Eliminar carpeta de la lista     (select from list → confirm → save)
  > Configurar sección de reportes   (sub-flow below)
  > Volver
```

Report sub-flow: show current; offer "Configurar" (prompt both fields), "Quitar reporte" (set None), "Volver". `None` from `.ask()` (Ctrl+C) returns to parent menu at every level. Empty `clean` on save → `confirm("La lista está vacía. ¿Guardar igual?")`.

## Error Handling

| Case | Behavior |
|------|----------|
| Absolute / `..` / empty path | Reject inline, show red message, re-prompt; nothing saved |
| Empty `clean` list | Yellow warning + confirm; save allowed if confirmed |
| Partial `report` (one field) | Re-prompt; never write partial |
| Missing `folders.json` | Treated as empty model; created on first save |
| Legacy array | Read, upgraded to object schema on next save |
| Ctrl+C (`.ask()` → None) | Return to previous menu, no write |

## Testing Strategy

| Layer | What | Approach |
|-------|------|----------|
| Unit | `validate_path` accept/reject (absolute, `..`, empty, valid relative) | Plain asserts, no mocks |
| Unit | `load_folders` (missing file, legacy array, object, object w/o report) | `tmp_path` fixture |
| Unit | `save_folders` round-trip → always modern schema; report omitted when None | `tmp_path` + reload + assert dict |
| Skipped | Interaction layer (`run`, sub-flows) | No questionary mocking — pure/interaction split keeps logic testable without it |

## Migration / Rollout

No migration. Existing `folders.json` keeps working (legacy upgrades on save). Rollback: delete `folder_manager.py` + test, revert the `_deps.py` line and `azulito.py` menu entry.

## Open Questions

- None blocking.
