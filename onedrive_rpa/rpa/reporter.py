"""
reporter.py — Report generation, Excel writing, and OneDrive upload.

Pure functions (generate_password, build_report_filename, build_report_rows,
write_excel) have no side effects and are fully unit-testable.

Playwright-bound functions (collect_subfolders, upload_report, run_report)
require an authenticated Playwright page and are integration-tested manually.
"""

import os
import secrets
import tempfile
from dataclasses import dataclass, field as dc_field
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any

from loguru import logger

from onedrive_rpa import config


class ReportError(Exception):
    """Raised when a report operation fails (e.g. folder not found, upload error)."""


# ---------------------------------------------------------------------------
# T-06: generate_password
# ---------------------------------------------------------------------------


def generate_password(length: int = config.REPORT_PASSWORD_LENGTH) -> str:
    """
    Generate a cryptographically random password.

    Args:
        length: Number of characters. Must be >= 16.

    Returns:
        A random string of ``length`` characters drawn from
        ``config.REPORT_PASSWORD_ALPHABET``.

    Raises:
        ValueError: if ``length`` < 16.
    """
    if length < 16:
        raise ValueError(f"Password length must be >= 16, got {length}")
    return "".join(secrets.choice(config.REPORT_PASSWORD_ALPHABET) for _ in range(length))


# ---------------------------------------------------------------------------
# T-07: build_report_filename
# ---------------------------------------------------------------------------


def build_report_filename(now: datetime | None = None) -> str:
    """
    Build the report filename using the configured prefix and timestamp format.

    Args:
        now: Optional datetime to use as the timestamp. Defaults to datetime.now().

    Returns:
        A filename string like ``reporte_20260522_143015.xlsx``.
    """
    ts = (now or datetime.now()).strftime(config.REPORT_FILENAME_TIMESTAMP_FORMAT)
    return f"{config.REPORT_FILENAME_PREFIX}_{ts}.xlsx"


# ---------------------------------------------------------------------------
# T-08: build_report_rows
# ---------------------------------------------------------------------------


def build_report_rows(
    folder_names: list[str],
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """
    Build the list of report row dicts from a list of folder names.

    Each row contains:
        - folder_name: the folder name as-is
        - password: a freshly generated random password
        - creation_date: the ``now`` datetime (or datetime.now())

    Args:
        folder_names: Ordered list of folder names to include in the report.
        now: Optional datetime to stamp as the creation date. Defaults to
             datetime.now(). Injecting a fixed value makes tests deterministic.

    Returns:
        A list of dicts, one per folder name.
    """
    creation_date = now or datetime.now()
    return [
        {
            "folder_name": name,
            "password": generate_password(),
            "creation_date": creation_date,
        }
        for name in folder_names
    ]


# ---------------------------------------------------------------------------
# T-09: write_excel
# ---------------------------------------------------------------------------


def write_excel(rows: list[dict[str, Any]]) -> BytesIO:
    """
    Serialize a list of report rows to an Excel workbook in memory.

    The workbook has a single sheet titled "Report" with a bold header row
    followed by one data row per entry in ``rows``.

    Column order: folder_name, password, creation_date.

    Args:
        rows: List of dicts as produced by :func:`build_report_rows`.

    Returns:
        A :class:`~io.BytesIO` seeked to position 0, ready to be read or
        passed directly to ``openpyxl.load_workbook()``.
    """
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    ws.title = "Report"

    headers = ["Folder Name", "Password", "Creation Date"]
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)

    for row in rows:
        ws.append([row["folder_name"], row["password"], row["creation_date"]])

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


# ---------------------------------------------------------------------------
# T-12: ReportStats dataclass
# ---------------------------------------------------------------------------


@dataclass
class ReportStats:
    """Accumulates metadata about a completed report run."""

    subfolders_found: int = 0
    rows_generated: int = 0
    uploaded_filename: str | None = None
    skipped_reason: str | None = None
    errors: list[str] = dc_field(default_factory=list)


# ---------------------------------------------------------------------------
# T-12: collect_subfolders
# ---------------------------------------------------------------------------


def collect_subfolders(page: "Page", source_folder: str) -> list[str]:  # type: ignore[name-defined]
    """Navigate to source_folder and return immediate subfolder names.

    Args:
        page: Authenticated Playwright page.
        source_folder: Relative OneDrive path to enumerate.

    Returns:
        List of subfolder names (strings) found at the immediate level.

    Note:
        v1 limitation: OneDrive virtualises its list. If the folder contains
        >= 50 items the result may be truncated. A warning is logged when this
        threshold is reached.
    """
    from playwright.sync_api import Page  # local import keeps module loadable without playwright

    from onedrive_rpa.rpa._navigation import navigate_to_folder, list_items, FolderNotFoundError

    try:
        navigate_to_folder(page, source_folder)
    except FolderNotFoundError:
        raise ReportError(f"source_folder not found: {source_folder}")

    # navigate_to_folder already waits for folder_row to be attached.
    # list_items repeats that wait internally — no additional delay needed.
    # networkidle is intentionally avoided: SharePoint continuously fires
    # background telemetry requests and never truly reaches idle, so waiting
    # for it burns the full timeout (15 s) on every call.
    items = list_items(page)
    folders = [item.name for item in items if item.is_folder]

    if len(folders) >= 50:
        logger.warning(
            "REPORT_SUBFOLDERS | count={n} | source={s} | "
            "WARNING: list may be truncated by DOM virtualization (v1 limitation)",
            n=len(folders),
            s=source_folder,
        )

    return folders


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _click_first_matching(page: "Page", selectors: list[str], timeout_ms: int) -> bool:  # type: ignore[name-defined]
    """Try each selector in order and click the first one that resolves. Returns True on success."""
    for sel in selectors:
        sel = sel.strip()
        if not sel:
            continue
        try:
            page.click(sel, timeout=timeout_ms)
            return True
        except Exception:
            continue
    return False


# ---------------------------------------------------------------------------
# T-12: upload_report
# ---------------------------------------------------------------------------


def upload_report(
    page: "Page",  # type: ignore[name-defined]
    excel_bytes: "BytesIO | bytes",
    destination_folder: str,
    filename: str,
) -> None:
    """Upload an Excel file to destination_folder in OneDrive via Playwright.

    Tries Shape A first (hidden file input via set_input_files). Falls back to
    Shape B (toolbar Upload button + file chooser) if Shape A is unavailable.

    Args:
        page: Authenticated Playwright page.
        excel_bytes: Either a BytesIO object or raw bytes.
        destination_folder: Relative OneDrive path for the upload destination.
        filename: The filename the uploaded file should have in OneDrive.

    Raises:
        ReportError: If the upload confirmation selector never appears.
    """
    from onedrive_rpa.rpa._navigation import navigate_to_folder, FolderNotFoundError
    from onedrive_rpa.config import SELECTORS, ACTION_TIMEOUT_MS, UPLOAD_TIMEOUT_MS

    try:
        navigate_to_folder(page, destination_folder)
    except FolderNotFoundError:
        raise ReportError(f"destination_folder not found: {destination_folder}")

    # Resolve bytes from BytesIO if needed
    if hasattr(excel_bytes, "read"):
        data: bytes = excel_bytes.read()
    else:
        data = excel_bytes  # type: ignore[assignment]

    tmp = tempfile.NamedTemporaryFile(
        prefix="onedrive_report_", suffix=".xlsx", delete=False
    )
    target_path: Path | None = None
    try:
        tmp.write(data)
        tmp.close()

        # Rename temp file to the intended filename so SharePoint shows the right name
        target_path = Path(tmp.name).parent / filename
        os.replace(tmp.name, target_path)

        # Shape A: input[type='file'] ya adjunto en el DOM (sin clic previo).
        # En algunas versiones de SharePoint el input está presente al cargar la página.
        shape_a_ok = False
        try:
            hidden_input = page.locator(SELECTORS["upload_file_input"]).first
            hidden_input.wait_for(state="attached", timeout=4_000)
            hidden_input.set_input_files(str(target_path))
            shape_a_ok = True
        except Exception:
            pass

        if not shape_a_ok:
            # Shape B: click "Crear o cargar" → "Carga de archivos".
            # SharePoint triggers a native OS file chooser when the submenu item
            # is clicked.  We MUST register expect_file_chooser BEFORE the click
            # so Playwright intercepts the dialog before it blocks execution.
            # (Earlier attempts with expect_file_chooser failed because the toolbar
            # click was silently failing with an unmatched selector — the dialog
            # never opened.  Now that the toolbar selector is fixed, the OS dialog
            # does open and expect_file_chooser can catch it.)
            _click_first_matching(page, SELECTORS["toolbar_upload"].split(", "), ACTION_TIMEOUT_MS)
            # Wait for the dropdown menu to be visible instead of a fixed pause.
            try:
                page.wait_for_selector("[role='menu'], [role='listbox']", timeout=3_000, state="visible")
            except Exception:
                pass  # proceed anyway — the submenu click will fail and fallback handles it

            try:
                with page.expect_file_chooser(timeout=15_000) as fc_info:
                    _click_first_matching(
                        page, SELECTORS["upload_files_menuitem"].split(", "), 3_000
                    )
                fc_info.value.set_files(str(target_path))
            except Exception:
                # Fallback: some SP versions inject the input without OS dialog
                hidden_input = page.locator(SELECTORS["upload_file_input"]).first
                hidden_input.wait_for(state="attached", timeout=10_000)
                hidden_input.set_input_files(str(target_path))

        # Wait for the uploaded file row to appear as confirmation.
        # Try two selectors: heroField (SharePoint item name) and a broad text match.
        # FieldRenderer-name is unreliable across tenants/versions.
        confirmed = False
        for confirm_sel in [
            f"[data-id='heroField']:has-text('{filename}')",
            f"text={filename}",
        ]:
            try:
                page.wait_for_selector(confirm_sel, timeout=UPLOAD_TIMEOUT_MS, state="visible")
                confirmed = True
                break
            except Exception:
                pass
        if not confirmed:
            raise ReportError(
                f"Upload confirmation not found for '{filename}' within timeout"
            )

    finally:
        for p in [Path(tmp.name), target_path]:
            if p is not None and Path(p).exists():
                try:
                    os.unlink(p)
                except OSError:
                    pass


# ---------------------------------------------------------------------------
# T-12: run_report
# ---------------------------------------------------------------------------


def run_report(
    page: "Page",  # type: ignore[name-defined]
    source_folder: str,
    destination_folder: str,
    *,
    callbacks=None,
) -> ReportStats:
    """Orchestrate collect → build rows → write Excel → upload.

    Non-fatal: all exceptions are caught and surfaced via ReportStats.errors
    so that the caller (main.py) can continue to the summary step.

    Args:
        page: Authenticated Playwright page.
        source_folder: Folder to enumerate immediate subfolders from.
        destination_folder: Folder where the Excel report is uploaded.
        callbacks: Optional RPACallbacks-compatible object. Calls are guarded
                   with hasattr so any subset of callbacks is acceptable.

    Returns:
        ReportStats with counts, filename, and any errors encountered.
    """
    stats = ReportStats()

    try:
        if callbacks and hasattr(callbacks, "on_report_start"):
            callbacks.on_report_start(source_folder, destination_folder)

        subfolders = collect_subfolders(page, source_folder)

        # Exclude the destination folder itself from the report when it lives
        # directly inside source_folder (e.g. source="pruebas", dest="pruebas/registro"
        # → exclude "registro" so the archive folder doesn't appear as a data row).
        source_prefix = source_folder.rstrip("/") + "/"
        if destination_folder.startswith(source_prefix):
            dest_child = destination_folder[len(source_prefix):].split("/")[0]
            subfolders = [f for f in subfolders if f != dest_child]

        stats.subfolders_found = len(subfolders)

        if callbacks and hasattr(callbacks, "on_report_subfolders"):
            callbacks.on_report_subfolders(len(subfolders))

        rows = build_report_rows(subfolders)
        stats.rows_generated = len(rows)

        excel_buf = write_excel(rows)
        filename = build_report_filename()

        upload_report(page, excel_buf, destination_folder, filename)
        stats.uploaded_filename = filename

        if callbacks and hasattr(callbacks, "on_report_uploaded"):
            callbacks.on_report_uploaded(filename)

        logger.info(
            "REPORT_END | rows={n} | uploaded={f} | destination={d}",
            n=len(rows),
            f=filename,
            d=destination_folder,
        )

    except ReportError as exc:
        stats.errors.append(str(exc))
        logger.error("REPORT_ERROR | reason={r}", r=str(exc))
        if callbacks and hasattr(callbacks, "on_report_error"):
            callbacks.on_report_error(str(exc))

    except Exception as exc:
        stats.errors.append(str(exc))
        logger.error("REPORT_ERROR | unexpected | reason={r}", r=str(exc))
        if callbacks and hasattr(callbacks, "on_report_error"):
            callbacks.on_report_error(str(exc))

    return stats
