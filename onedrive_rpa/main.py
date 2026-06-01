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
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

# Permite correr como script directo: python main.py o python onedrive_rpa/main.py
sys.path.insert(0, str(Path(__file__).parent.parent))

import click
from loguru import logger
from playwright.sync_api import sync_playwright

from onedrive_rpa import config
from onedrive_rpa.config import FOLDERS_PATH
from onedrive_rpa.auth.session import (
    load_or_login,
    SessionMissingError,
    SessionExpiredError,
)
from onedrive_rpa.rpa.cleaner import FolderCleaner, CleanStats, FolderNotFoundError
from onedrive_rpa.rpa.logger import configure_logging
from onedrive_rpa.rpa.reporter import generate_password
from onedrive_rpa.rpa.sharer import share_folder, ShareStats, folder_key
from onedrive_rpa.rpa.ui import RPADisplay


# ---------------------------------------------------------------------------
# Config types
# ---------------------------------------------------------------------------


class ConfigError(Exception):
    """Raised when folders.json contains an invalid configuration."""


@dataclass(frozen=True)
class ReportConfig:
    """Configuration for the optional post-clean report step."""

    source_folder: str
    """OneDrive folder whose immediate sub-folders will be enumerated."""

    destination_folder: str
    """OneDrive folder where the generated Excel report will be uploaded."""


@dataclass(frozen=True)
class FoldersConfig:
    """Parsed and validated contents of folders.json."""

    clean: list[str]
    """Ordered list of folder paths to clean (relative, no leading slash)."""

    report: ReportConfig | None
    """Optional report configuration. None when the key is absent or null."""


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
    try:
        folders_config = _load_folders(config_path)
    except ConfigError as exc:
        logger.error("CONFIG | {err}", err=str(exc))
        click.echo(f"Config error: {exc}", err=True)
        sys.exit(1)

    folder_paths = folders_config.clean
    if not folder_paths:
        logger.error("CONFIG | folders.json está vacío o sin entradas válidas")
        sys.exit(1)

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

    # Pre-generate per-folder passwords (single source of truth for share link + report)
    share_passwords: dict[str, str] = {
        folder_key(fp): generate_password()
        for fp in folder_paths
    }
    share_expiry: datetime = datetime.now() + timedelta(days=config.SHARE_EXPIRY_DAYS)
    global_share_stats = ShareStats()

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
                _emit_summary(global_stats, start_time, global_share_stats)
                sys.exit(2)
            except SessionExpiredError as exc:
                logger.error("AUTH | {msg}", msg=str(exc))
                _emit_summary(global_stats, start_time, global_share_stats)
                sys.exit(3)

            # -----------------------------------------------------------------
            # 4. Limpiar cada carpeta
            # -----------------------------------------------------------------
            cleaner = FolderCleaner(page, dry_run=dry_run, callbacks=display.callbacks)

            for folder_path in folder_paths:
                try:
                    stats = cleaner.clean(folder_path)
                    global_stats.merge(stats)
                    # Share the folder after a successful clean (skip in dry-run)
                    if not dry_run:
                        key = folder_key(folder_path)
                        password = share_passwords.get(key, generate_password())
                        share_result = share_folder(page, folder_path, password, share_expiry)
                        global_share_stats.shared.extend(share_result.shared)
                        global_share_stats.share_errors.extend(share_result.share_errors)
                        global_share_stats.share_urls.update(share_result.share_urls)
                        # Emit share result to TUI activity log
                        expiry_str = share_expiry.strftime("%d/%m/%Y")
                        if share_result.shared:
                            display.log("SHARE", f"{folder_path}  ·  vínculo compartido  ·  expira {expiry_str}")
                        if share_result.share_errors:
                            display.log("SHAERR", f"{folder_path}  ·  error al compartir")
                    else:
                        logger.debug(
                            "dry-run: skipping share for {folder_path}",
                            folder_path=folder_path,
                        )
                except FolderNotFoundError:
                    global_stats.skipped.append(folder_path)
                except SessionExpiredError as exc:
                    logger.error("SESSION_EXPIRED | {msg}", msg=str(exc))
                    _emit_summary(global_stats, start_time, global_share_stats)
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

            # -----------------------------------------------------------------
            # 5. Post-clean report (if configured and not dry-run)
            # -----------------------------------------------------------------
            if folders_config.report is not None and not dry_run:
                from onedrive_rpa.rpa.reporter import run_report
                logger.info(
                    "REPORT_BEGIN | source={s} | destination={d}",
                    s=folders_config.report.source_folder,
                    d=folders_config.report.destination_folder,
                )
                run_report(
                    page,
                    folders_config.report.source_folder,
                    folders_config.report.destination_folder,
                    callbacks=display.callbacks,
                    passwords=share_passwords,
                    share_urls=global_share_stats.share_urls,
                )
            elif folders_config.report is not None and dry_run:
                logger.info("REPORT | SKIPPED | reason=dry_run")
                if hasattr(display.callbacks, "on_report_skipped"):
                    display.callbacks.on_report_skipped("dry_run")
            else:
                logger.debug("REPORT | SKIPPED | reason=not_configured")

            if browser:
                browser.close()

    except KeyboardInterrupt:
        logger.warning("INTERRUPTED | Ctrl+C detectado")
        _emit_summary(global_stats, start_time, global_share_stats)
        sys.exit(130)

    # -----------------------------------------------------------------------
    # 5. Summary final
    # -----------------------------------------------------------------------
    _emit_summary(global_stats, start_time, global_share_stats)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_folders(config_path: str) -> FoldersConfig:
    """
    Load and validate folders.json, returning a FoldersConfig.

    Supports two schemas:
        - Legacy: a JSON array of {"path": "..."} objects → report=None
        - Modern: a JSON object with "clean" (array) and optional "report" keys

    Path validation (legacy + modern clean entries):
        - Each entry must have a non-empty "path" key
        - Paths must be relative (not absolute, no ".." components)

    Returns:
        FoldersConfig with validated clean paths and an optional ReportConfig.

    Raises:
        ConfigError: for any invalid configuration (invalid JSON, missing keys, etc.)
        SystemExit(1): if the config file is not found.
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
        raise ConfigError(f"Invalid JSON in {config_path}: {exc}") from exc

    # ------------------------------------------------------------------
    # Legacy array format
    # ------------------------------------------------------------------
    if isinstance(data, list):
        logger.info(
            "CONFIG | LEGACY SCHEMA | report disabled"
            " — migrate folders.json to object schema to enable reports"
        )
        clean_paths = _validate_clean_entries(data)
        return FoldersConfig(clean=clean_paths, report=None)

    # ------------------------------------------------------------------
    # Modern object format
    # ------------------------------------------------------------------
    if not isinstance(data, dict):
        raise ConfigError("folders.json must be a JSON array or object")

    clean_raw = data.get("clean")
    if not clean_raw or not isinstance(clean_raw, list):
        raise ConfigError("folders.json must have a non-empty 'clean' array")

    clean_paths = _validate_clean_entries(clean_raw)

    report_data = data.get("report")
    report: ReportConfig | None = None
    if report_data is not None:
        source = (report_data.get("source_folder") or "").strip()
        destination = (report_data.get("destination_folder") or "").strip()
        if not source or not destination:
            raise ConfigError(
                "report block requires both 'source_folder' and 'destination_folder' "
                "(non-empty strings)"
            )
        report = ReportConfig(source_folder=source, destination_folder=destination)

    return FoldersConfig(clean=clean_paths, report=report)


def _validate_clean_entries(entries: list) -> list[str]:
    """
    Validate a list of clean entry dicts and return their path strings.

    Raises:
        ConfigError: if any entry is malformed or has an invalid path.
    """
    validated: list[str] = []
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict) or "path" not in entry:
            raise ConfigError(f"entry[{i}] is missing the 'path' key")

        folder_path: str = entry["path"]

        if not folder_path or not folder_path.strip():
            raise ConfigError(f"entry[{i}].path is empty")

        if Path(folder_path).is_absolute():
            raise ConfigError(
                f"entry[{i}].path is absolute: {folder_path!r} — only relative paths allowed"
            )

        if ".." in Path(folder_path).parts:
            raise ConfigError(
                f"entry[{i}].path contains '..': {folder_path!r} — not allowed"
            )

        validated.append(folder_path)

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


def _emit_summary(
    stats: CleanStats,
    start_time: float,
    share_stats: ShareStats | None = None,
) -> None:
    """
    Emite el resumen de la corrida al finalizar (normal o abortada).
    Spec: audit-logging — run summary on exit.
    """
    elapsed = time.monotonic() - start_time
    shared_count = len(share_stats.shared) if share_stats else 0
    share_error_count = len(share_stats.share_errors) if share_stats else 0
    logger.info(
        "RUN END | deleted={deleted} | would_delete={would_delete} | "
        "skipped={skipped} | errors={errors} | "
        "Shared: {shared}, Share errors: {share_errors} | elapsed={elapsed:.1f}s",
        deleted=len(stats.deleted),
        would_delete=len(stats.would_delete),
        skipped=len(stats.skipped),
        errors=len(stats.errors),
        shared=shared_count,
        share_errors=share_error_count,
        elapsed=elapsed,
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    main()
