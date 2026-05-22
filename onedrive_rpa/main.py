"""
main.py — CLI principal del RPA de limpieza OneDrive.

Uso rápido:
    # Primer login (abre browser):
    python -m onedrive_rpa.main --mode manual

    # Ver qué se borraría sin borrar nada:
    python -m onedrive_rpa.main --dry-run

    # Borrado real (pide confirmación escribiendo DELETE):
    python -m onedrive_rpa.main

    # Borrado real sin confirmación (útil en CI/scripts):
    python -m onedrive_rpa.main --yes

    # Forzar re-login (elimina session.json y reabre browser):
    python -m onedrive_rpa.main --mode manual --relogin

Exit codes:
    0  → éxito (o abortado por usuario en confirmación)
    1  → error de configuración (folders.json inválido, etc.)
    2  → sesión faltante en modo auto (SessionMissingError)
    3  → sesión expirada mid-run (SessionExpiredError)
    130 → KeyboardInterrupt (Ctrl+C)
"""

import json
import sys
import time
from pathlib import Path

# Permite correr como script directo: python main.py o python onedrive_rpa/main.py
sys.path.insert(0, str(Path(__file__).parent.parent))

import click
from loguru import logger
from playwright.sync_api import sync_playwright

from onedrive_rpa.config import FOLDERS_PATH
from onedrive_rpa.auth.session import (
    load_or_login,
    SessionMissingError,
    SessionExpiredError,
)
from onedrive_rpa.rpa.cleaner import FolderCleaner, CleanStats, FolderNotFoundError
from onedrive_rpa.rpa.logger import configure_logging
from onedrive_rpa.rpa.ui import RPADisplay


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.option(
    "--mode",
    type=click.Choice(["manual", "auto"], case_sensitive=False),
    default="auto",
    show_default=True,
    help="manual: abre browser headed para login. auto: usa session.json (headless).",
)
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=False),
    default=str(FOLDERS_PATH),
    show_default=True,
    help="Ruta al archivo folders.json con las carpetas a limpiar.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Recorre las carpetas y loggea WOULD_DELETE sin borrar nada.",
)
@click.option(
    "--yes",
    is_flag=True,
    default=False,
    help="Omite la confirmación interactiva. Útil para scripts/CI.",
)
@click.option(
    "--relogin",
    is_flag=True,
    default=False,
    help="Elimina session.json y fuerza un nuevo login manual.",
)
def main(
    mode: str,
    config_path: str,
    dry_run: bool,
    yes: bool,
    relogin: bool,
) -> None:
    """
    RPA de limpieza de carpetas OneDrive via Playwright.

    Borra todos los archivos de las carpetas listadas en folders.json
    de forma recursiva (DFS). Los subdirectorios NO se eliminan.
    """
    # Configurar logging antes de cualquier operación
    configure_logging()

    start_time = time.monotonic()

    logger.info(
        "RUN START | mode={mode} | dry_run={dry_run} | config={config}",
        mode=mode,
        dry_run=dry_run,
        config=config_path,
    )

    # -----------------------------------------------------------------------
    # 1. Cargar y validar folders.json
    # -----------------------------------------------------------------------
    folders = _load_folders(config_path)
    if not folders:
        logger.error("CONFIG | folders.json está vacío o sin entradas válidas")
        sys.exit(1)

    folder_paths = [f["path"] for f in folders]
    logger.info(
        "CONFIG | folders={n} | paths={paths}",
        n=len(folder_paths),
        paths=folder_paths,
    )

    # -----------------------------------------------------------------------
    # 2. Confirmación interactiva (solo en run real, no en dry-run)
    # -----------------------------------------------------------------------
    if not dry_run and not yes:
        _confirm_destructive_run(folder_paths)

    # -----------------------------------------------------------------------
    # 3. Autenticación
    # -----------------------------------------------------------------------
    browser = None
    global_stats = CleanStats()

    display = RPADisplay(mode=mode, dry_run=dry_run, folders=folder_paths)

    try:
        with display, sync_playwright() as playwright:
            try:
                browser, context, page = load_or_login(
                    playwright,
                    mode=mode,
                    force_relogin=relogin,
                    log_fn=display.log,
                )
            except SessionMissingError as exc:
                logger.error("AUTH | {msg}", msg=str(exc))
                _emit_summary(global_stats, start_time)
                sys.exit(2)
            except SessionExpiredError as exc:
                logger.error("AUTH | {msg}", msg=str(exc))
                _emit_summary(global_stats, start_time)
                sys.exit(3)

            # -----------------------------------------------------------------
            # 4. Limpiar cada carpeta
            # -----------------------------------------------------------------
            cleaner = FolderCleaner(page, dry_run=dry_run, callbacks=display.callbacks)

            for folder_path in folder_paths:
                try:
                    stats = cleaner.clean(folder_path)
                    global_stats.merge(stats)
                except FolderNotFoundError:
                    global_stats.skipped.append(folder_path)
                except SessionExpiredError as exc:
                    logger.error("SESSION_EXPIRED | {msg}", msg=str(exc))
                    _emit_summary(global_stats, start_time)
                    if browser:
                        browser.close()
                    sys.exit(3)
                except KeyboardInterrupt:
                    raise
                except Exception as exc:
                    logger.error(
                        "ERROR | folder={folder} reason={reason}",
                        folder=folder_path,
                        reason=str(exc),
                    )
                    global_stats.errors.append(folder_path)

            if browser:
                browser.close()

    except KeyboardInterrupt:
        logger.warning("INTERRUPTED | Ctrl+C detectado")
        _emit_summary(global_stats, start_time)
        sys.exit(130)

    # -----------------------------------------------------------------------
    # 5. Summary final
    # -----------------------------------------------------------------------
    _emit_summary(global_stats, start_time)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_folders(config_path: str) -> list[dict]:
    """
    Carga y valida folders.json.

    Validaciones:
        - Archivo existe.
        - JSON válido.
        - Es una lista de objetos con clave "path".
        - Cada path: no vacío, no absoluto, no contiene "..".

    Returns:
        Lista de dicts validados.

    Raises:
        SystemExit(1): ante cualquier error de validación.
    """
    path = Path(config_path)

    if not path.exists():
        logger.error("CONFIG | archivo no encontrado: {path}", path=config_path)
        click.echo(f"Error: config file not found: {config_path}", err=True)
        sys.exit(1)

    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.error("CONFIG | JSON inválido en {path}: {err}", path=config_path, err=exc)
        sys.exit(1)

    if not isinstance(data, list):
        logger.error("CONFIG | folders.json debe ser una lista de objetos")
        sys.exit(1)

    validated: list[dict] = []
    for i, entry in enumerate(data):
        if not isinstance(entry, dict) or "path" not in entry:
            logger.error("CONFIG | entry[{i}] no tiene clave 'path'", i=i)
            sys.exit(1)

        folder_path: str = entry["path"]

        if not folder_path or not folder_path.strip():
            logger.error("CONFIG | entry[{i}].path está vacío", i=i)
            sys.exit(1)

        if Path(folder_path).is_absolute():
            logger.error(
                "CONFIG | entry[{i}].path es absoluto: {p} — solo paths relativos",
                i=i, p=folder_path,
            )
            sys.exit(1)

        if ".." in Path(folder_path).parts:
            logger.error(
                "CONFIG | entry[{i}].path contiene '..': {p} — no permitido",
                i=i, p=folder_path,
            )
            sys.exit(1)

        validated.append(entry)

    return validated


def _confirm_destructive_run(folder_paths: list[str]) -> None:
    """
    Pide al usuario que escriba literalmente `DELETE` para confirmar borrado.

    Si el usuario no escribe `DELETE` exacto → exit 0 sin borrar nada.
    (ADR-10: confirmación con palabra entera, no y/n)
    """
    click.echo("\nCarpetas a limpiar:")
    for p in folder_paths:
        click.echo(f"  - {p}")

    click.echo(
        "\nATENCION: Esta operacion eliminara TODOS los archivos listados arriba."
        "\nEscribi exactamente DELETE para continuar (cualquier otra cosa cancela):"
    )
    user_input = input("> ").strip()

    if user_input != "DELETE":
        click.echo("Operacion cancelada.")
        sys.exit(0)

    click.echo()  # línea en blanco antes del run


def _emit_summary(stats: CleanStats, start_time: float) -> None:
    """
    Emite el resumen de la corrida al finalizar (normal o abortada).
    Spec: audit-logging — run summary on exit.
    """
    elapsed = time.monotonic() - start_time
    logger.info(
        "RUN END | deleted={deleted} | would_delete={would_delete} | "
        "skipped={skipped} | errors={errors} | elapsed={elapsed:.1f}s",
        deleted=len(stats.deleted),
        would_delete=len(stats.would_delete),
        skipped=len(stats.skipped),
        errors=len(stats.errors),
        elapsed=elapsed,
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    main()
