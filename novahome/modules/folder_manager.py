"""
novahome/modules/folder_manager.py — CRUD TUI for folders.json.

Manages the `clean` list and optional `report` section used by onedrive_rpa.

Validation rules (mirrors _validate_clean_entries in onedrive_rpa/main.py):
  - Path must be non-empty after stripping whitespace.
  - Path must NOT be absolute (Path.is_absolute() must be False).
  - Path must NOT contain '..' in any component (Path.parts must not include '..').

Note: onedrive_rpa is NOT imported here — rules are replicated to keep hub/RPA isolated.

In-memory model (plain dict):
    {
        "clean": list[str],   # validated relative path strings
        "report": dict | None  # {"source_folder": str, "destination_folder": str} or None
    }

folders.json schema written (always modern):
    {
        "clean": [{"path": "..."}, ...],
        "report": {"source_folder": "...", "destination_folder": "..."} | omitted when None
    }

Legacy format (plain JSON array of strings or {"path": ...} objects): read and
upgraded to modern schema on the next save (lossless).
"""
from __future__ import annotations

import json
from pathlib import Path


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class FolderValidationError(ValueError):
    """Raised when a path fails folder validation rules."""


# ---------------------------------------------------------------------------
# Pure functions (no I/O side-effects beyond filesystem read/write)
# ---------------------------------------------------------------------------


def validate_path(raw: str) -> str:
    """Validate and normalise a raw path string.

    Returns:
        The stripped path string if valid.

    Raises:
        FolderValidationError: if empty after strip, absolute, or contains '..'.
    """
    cleaned = raw.strip()
    if not cleaned:
        raise FolderValidationError("Path must not be empty.")
    p = Path(cleaned)
    if p.is_absolute():
        raise FolderValidationError(
            f"Absolute paths are not allowed: {cleaned!r}"
        )
    if ".." in p.parts:
        raise FolderValidationError(
            f"Path must not contain '..': {cleaned!r}"
        )
    return cleaned


def load_folders(path: Path) -> dict:
    """Load folders.json from *path* and return a normalised in-memory model.

    Missing file → empty model (no error).
    Legacy JSON array → treats elements as clean paths, report=None.
    Modern object → normalised (report key ensured).

    Returns:
        {"clean": list[str], "report": dict | None}
    """
    _default: dict = {"clean": [], "report": None}

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return _default

    # Legacy format: plain JSON array
    if isinstance(raw, list):
        clean: list[str] = []
        for item in raw:
            if isinstance(item, dict) and "path" in item:
                clean.append(item["path"])
            elif isinstance(item, str):
                clean.append(item)
        return {"clean": clean, "report": None}

    # Modern object format
    if not isinstance(raw, dict):
        return _default

    clean_entries = raw.get("clean", [])
    clean_paths: list[str] = []
    for entry in clean_entries:
        if isinstance(entry, dict) and "path" in entry:
            clean_paths.append(entry["path"])
        elif isinstance(entry, str):
            clean_paths.append(entry)

    report_raw = raw.get("report", None)
    report: dict | None = None
    if isinstance(report_raw, dict):
        report = report_raw

    return {"clean": clean_paths, "report": report}


def save_folders(path: Path, model: dict) -> None:
    """Persist *model* to *path* using the modern object schema.

    Always writes:
        {"clean": [{"path": p}, ...], "report": {...}}
    The "report" key is omitted entirely when model["report"] is None.
    Writes UTF-8 JSON with indent=2.
    """
    payload: dict = {"clean": [{"path": p} for p in model["clean"]]}
    if model.get("report") is not None:
        payload["report"] = model["report"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# Interaction helpers (questionary/Rich — not unit-tested)
# ---------------------------------------------------------------------------


def _show_folders(model: dict) -> None:
    """Display the clean list as a Rich table (or a notice if empty)."""
    from rich.console import Console
    from rich.table import Table
    from rich.text import Text

    console = Console()

    if not model["clean"]:
        console.print(Text("  No hay carpetas configuradas.", style="yellow3"))
        return

    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("#", style="dim", width=4)
    table.add_column("Path")
    for i, p in enumerate(model["clean"], start=1):
        table.add_row(str(i), p)
    console.print(table)


def _add_folder(model: dict, data_path: Path) -> None:
    """Prompt user for a new path, validate, append, and save."""
    import questionary
    from rich.console import Console
    from rich.text import Text

    console = Console()

    while True:
        raw = questionary.text("Path relativo a agregar:").ask()
        if raw is None:
            return  # Ctrl+C → back to parent menu
        try:
            cleaned = validate_path(raw)
        except FolderValidationError as exc:
            console.print(Text(f"  Error: {exc}", style="bold red"))
            continue
        model["clean"].append(cleaned)
        save_folders(data_path, model)
        console.print(Text(f"  Carpeta '{cleaned}' agregada.", style="bold green"))
        return


def _remove_folder(model: dict, data_path: Path) -> None:
    """Present existing paths as a selectable list, confirm, remove, and save."""
    import questionary
    from rich.console import Console
    from rich.text import Text

    console = Console()

    if not model["clean"]:
        console.print(Text("  No hay carpetas configuradas para eliminar.", style="yellow3"))
        return

    choice = questionary.select(
        "Seleccioná la carpeta a eliminar:",
        choices=model["clean"] + ["Cancelar"],
    ).ask()

    if choice is None or choice == "Cancelar":
        return

    confirmed = questionary.confirm(f"  ¿Eliminar '{choice}'?", default=False).ask()
    if not confirmed:
        return

    model["clean"].remove(choice)
    if not model["clean"]:
        console.print(Text("  Advertencia: la lista quedará vacía. El RPA fallará al iniciarse.", style="bold yellow"))
        if not questionary.confirm("  ¿Guardás con la lista vacía?", default=False).ask():
            model["clean"].append(choice)
            return
    save_folders(data_path, model)
    console.print(Text(f"  Carpeta '{choice}' eliminada.", style="bold green"))


def _report_subflow(model: dict, data_path: Path) -> None:
    """Sub-flow for configuring or clearing the report section."""
    import questionary
    from rich.console import Console
    from rich.text import Text

    console = Console()

    while True:
        current = model.get("report")
        if current:
            console.print(
                Text(
                    f"  Reporte actual:\n"
                    f"    source_folder:      {current['source_folder']}\n"
                    f"    destination_folder: {current['destination_folder']}",
                    style="cyan",
                )
            )
        else:
            console.print(Text("  No hay sección de reporte configurada.", style="yellow3"))

        action = questionary.select(
            "Configurar reportes:",
            choices=["Configurar", "Quitar reporte", "Volver"],
        ).ask()

        if action is None or action == "Volver":
            return

        if action == "Quitar reporte":
            confirmed = questionary.confirm("  ¿Eliminar sección de reporte?", default=False).ask()
            if confirmed:
                model["report"] = None
                save_folders(data_path, model)
                console.print(Text("  Sección de reporte eliminada.", style="bold green"))
            return

        if action == "Configurar":
            # Both-or-neither — re-prompt until both fields are provided or cancelled
            while True:
                src = questionary.text(
                    "source_folder:",
                    default=(current or {}).get("source_folder", ""),
                ).ask()
                if src is None:
                    return  # Ctrl+C

                dst = questionary.text(
                    "destination_folder:",
                    default=(current or {}).get("destination_folder", ""),
                ).ask()
                if dst is None:
                    return  # Ctrl+C

                src = src.strip()
                dst = dst.strip()

                if src and dst:
                    model["report"] = {"source_folder": src, "destination_folder": dst}
                    save_folders(data_path, model)
                    console.print(Text("  Sección de reporte guardada.", style="bold green"))
                    return
                elif not src and not dst:
                    model["report"] = None
                    save_folders(data_path, model)
                    console.print(Text("  Sección de reporte eliminada (ambos vacíos).", style="yellow3"))
                    return
                else:
                    console.print(
                        Text(
                            "  Ambos campos deben completarse o dejarse vacíos. Re-ingresá.",
                            style="bold red",
                        )
                    )


def run() -> None:
    """Entry point called from azulito.run()."""
    import questionary
    from rich.console import Console
    from rich.text import Text

    from novahome.modules._deps import DATA_DIR

    console = Console()
    data_path = DATA_DIR / "folders.json"
    model = load_folders(data_path)

    while True:
        choice = questionary.select(
            "Gestionar carpetas — folders.json:",
            choices=[
                "Ver carpetas configuradas",
                "Agregar carpeta a limpiar",
                "Eliminar carpeta de la lista",
                "Configurar sección de reportes",
                "Volver",
            ],
        ).ask()

        if choice is None or choice == "Volver":
            return

        if choice == "Ver carpetas configuradas":
            _show_folders(model)

        elif choice == "Agregar carpeta a limpiar":
            _add_folder(model, data_path)

        elif choice == "Eliminar carpeta de la lista":
            # Re-check if empty after potential removals
            if not model["clean"]:
                console.print(Text("  No hay carpetas configuradas.", style="yellow3"))
            else:
                _remove_folder(model, data_path)

        elif choice == "Configurar sección de reportes":
            _report_subflow(model, data_path)
