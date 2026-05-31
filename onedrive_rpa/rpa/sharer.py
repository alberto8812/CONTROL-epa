"""
rpa/sharer.py — Folder sharing via OneDrive's "Compartir" dialog.

After a folder is cleaned, share_folder() creates an "Anyone" sharing link
with a password and expiry date.  Failures are non-fatal: every exception is
caught, logged at ERROR level, and recorded in ShareStats — the run continues.

Pure helpers (folder_key, _format_expiry) have no Playwright dependency and
are fully unit-testable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from loguru import logger

from onedrive_rpa.config import (
    SELECTORS,
    SHARE_SELECTORS,
    ACTION_TIMEOUT_MS,
    NAV_TIMEOUT_MS,
)
from onedrive_rpa.rpa._retry import with_retry
from onedrive_rpa.rpa._navigation import navigate_to_folder


# ---------------------------------------------------------------------------
# Exceptions and data types
# ---------------------------------------------------------------------------


class ShareError(Exception):
    """Raised when a sharing dialog interaction fails."""


@dataclass
class ShareStats:
    """Accumulates per-run sharing outcome."""

    shared: list[str] = field(default_factory=list)
    """base_name of each folder successfully shared."""

    share_errors: list[str] = field(default_factory=list)
    """base_name of each folder where sharing failed."""


# ---------------------------------------------------------------------------
# Pure helpers — no Playwright dependency
# ---------------------------------------------------------------------------


def folder_key(folder_path: str) -> str:
    """Derive the base folder name from a path string.

    Args:
        folder_path: Relative OneDrive path, e.g. ``"pruebas/archivos_1"``
                     or ``"documentos"``.

    Returns:
        The last path segment with trailing slashes stripped.
        ``"pruebas/archivos_1"`` → ``"archivos_1"``
        ``"documentos"``         → ``"documentos"``
        ``"a/b/"``               → ``"b"``
    """
    return folder_path.rstrip("/").rsplit("/", 1)[-1]


def _format_expiry(dt: datetime) -> str:
    """Format *dt* as ``DD/MM/YYYY`` for the OneDrive expiry date input.

    Args:
        dt: The expiry datetime.

    Returns:
        Zero-padded date string, e.g. ``"08/06/2026"``.
    """
    return dt.strftime("%d/%m/%Y")


# ---------------------------------------------------------------------------
# Private Playwright helpers
# ---------------------------------------------------------------------------


def _get_share_frame(page: "Page"):  # type: ignore[name-defined]
    """Return the shareFrame Frame object, or raise ShareError if not found.

    The Compartir dialog is rendered inside an <iframe name="shareFrame">.
    All interactions with the dialog content (gear, expiry, password, Apply)
    must go through this frame object, not through ``page`` directly.

    Raises:
        ShareError: If the iframe is not present in the page.
    """
    from playwright.sync_api import Page  # local import — keeps module importable without playwright
    frame = page.frame(name="shareFrame")
    if frame is None:
        raise ShareError("Share dialog iframe (shareFrame) not found — dialog may not be open")
    return frame


def _find_row_by_name(page: "Page", name: str) -> "Locator | None":  # type: ignore[name-defined]
    """Return the row locator whose heroField text matches *name*, or None.

    Iterates all currently-visible folder rows and compares inner text.
    This is a minimal inline re-implementation to keep sharer.py decoupled
    from the private internals of cleaner.py.

    Args:
        page: Authenticated Playwright page.
        name: Exact folder name to match (case-sensitive).

    Returns:
        Playwright Locator for the matching row, or ``None`` if not found.
    """
    rows = page.locator(SELECTORS["folder_row"]).all()
    for row in rows:
        try:
            cell_text = row.locator(SELECTORS["item_name"]).inner_text(timeout=2_000).strip()
            if cell_text == name:
                return row
        except Exception:
            continue
    return None


@with_retry()
def _open_share_dialog(page: "Page", folder_name: str) -> None:  # type: ignore[name-defined]
    """Select the folder row and navigate to the link-settings panel.

    OneDrive opens a two-step share flow:
      1. "Compartir" toolbar button → people-invite panel (name / email input)
      2. Gear icon ⚙️ inside that panel → "Configuración de vínculos" settings panel
         (where expiry date and password fields live)

    Decorated with @with_retry() — idempotent (unlike delete, ADR-7).

    Args:
        page: Authenticated Playwright page.
        folder_name: Base name of the folder to select (leaf segment).

    Raises:
        ShareError: If the row is not found or either dialog step fails.
    """
    row = _find_row_by_name(page, folder_name)
    if row is None:
        raise ShareError(f"Folder row not found in DOM: {folder_name!r}")

    # Click the row's selection checkbox container (.first avoids strict mode if
    # the selector ever matches more than one element within the row)
    checkbox = row.locator(SHARE_SELECTORS["row_checkbox"]).first
    checkbox.click(timeout=ACTION_TIMEOUT_MS)

    # Step 1: Click the "Compartir" toolbar button → opens the people-invite panel
    try:
        page.click(SHARE_SELECTORS["share_button"], timeout=ACTION_TIMEOUT_MS)
    except Exception as exc:
        raise ShareError(f"Could not click share button for {folder_name!r}: {exc}") from exc

    # Wait for the shareFrame iframe to become visible on the main page
    try:
        page.wait_for_selector(
            SHARE_SELECTORS["share_iframe"], state="visible", timeout=ACTION_TIMEOUT_MS
        )
    except Exception as exc:
        raise ShareError(f"Share iframe did not appear for {folder_name!r}: {exc}") from exc

    # All further dialog interactions happen inside the iframe
    frame = _get_share_frame(page)

    # Step 2: Wait for the gear icon inside the iframe, then click it
    try:
        frame.wait_for_selector(SHARE_SELECTORS["settings_button"], state="visible", timeout=ACTION_TIMEOUT_MS)
        frame.click(SHARE_SELECTORS["settings_button"], timeout=ACTION_TIMEOUT_MS)
    except Exception as exc:
        raise ShareError(f"Could not click settings gear for {folder_name!r}: {exc}") from exc

    # Wait for Apply button inside the iframe — proxy that settings panel is open
    try:
        frame.wait_for_selector(
            SHARE_SELECTORS["apply_button"], state="visible", timeout=ACTION_TIMEOUT_MS
        )
    except Exception as exc:
        raise ShareError(f"Link-settings panel did not open for {folder_name!r}: {exc}") from exc


@with_retry()
def _apply_share_settings(page: "Page", password: str, expiry_str: str) -> None:  # type: ignore[name-defined]
    """Configure the share settings panel (inside shareFrame iframe).

    Decorated with @with_retry() — the settings form overwrites link state on
    each attempt, making the operation idempotent (unlike delete, ADR-7).

    Args:
        page: Authenticated Playwright page.
        password: Plaintext password for the sharing link.
        expiry_str: Date string in ``DD/MM/YYYY`` format.

    Raises:
        ShareError: If a required selector cannot be found or interacted with.
    """
    frame = _get_share_frame(page)

    # Select "Cualquier persona" / "Anyone" — DOM-confirmed: role=radio data-key='2'.
    # It may already be selected; click is a no-op in that case.
    try:
        frame.click(SHARE_SELECTORS["anyone_option"], timeout=ACTION_TIMEOUT_MS)
    except Exception:
        logger.debug("SHARE | anyone_option not clickable — may already be selected")

    # Set expiry date — the input has readonly='' so .fill()/.clear() are rejected.
    # Strategy: click to focus (may open a calendar popup), then type the date
    # string char-by-char via keyboard events. Fluent UI DatePicker processes
    # keydown events even on readonly inputs to update its internal state.
    # Press Tab to confirm and close any popup before moving on.
    try:
        expiry_input = frame.locator(SHARE_SELECTORS["expiry_input"]).first
        expiry_input.wait_for(state="visible", timeout=ACTION_TIMEOUT_MS)
        expiry_input.click(timeout=ACTION_TIMEOUT_MS)
        page.wait_for_timeout(400)  # let calendar popup render if it opens
        page.keyboard.type(expiry_str)  # "DD/MM/YYYY"
        page.keyboard.press("Tab")      # confirm selection and close popup
        page.wait_for_timeout(300)
    except Exception as exc:
        raise ShareError(f"Could not set expiry date {expiry_str!r}: {exc}") from exc

    # Fill password field — standard input, .fill() works directly.
    try:
        pwd_input = frame.locator(SHARE_SELECTORS["password_input"]).first
        pwd_input.wait_for(state="visible", timeout=ACTION_TIMEOUT_MS)
        pwd_input.fill(password, timeout=ACTION_TIMEOUT_MS)
    except Exception as exc:
        raise ShareError(f"Could not fill password field: {exc}") from exc


def _click_apply(page: "Page") -> None:  # type: ignore[name-defined]
    """Click the Apply button inside shareFrame and wait for the iframe to close.

    Args:
        page: Authenticated Playwright page.

    Raises:
        ShareError: If the Apply button cannot be clicked.
    """
    frame = _get_share_frame(page)

    try:
        frame.click(SHARE_SELECTORS["apply_button"], timeout=ACTION_TIMEOUT_MS)
    except Exception as exc:
        raise ShareError(f"Could not click apply button: {exc}") from exc

    # Wait for the iframe itself to detach — more reliable than waiting for a
    # button inside the frame to disappear (the frame may navigate or close).
    try:
        page.wait_for_selector(
            SHARE_SELECTORS["share_iframe"], state="detached", timeout=ACTION_TIMEOUT_MS
        )
    except Exception:
        logger.debug("SHARE | share iframe still present after apply — proceeding anyway")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def share_folder(
    page: "Page",  # type: ignore[name-defined]
    folder_path: str,
    password: str,
    expiry_date: datetime,
) -> ShareStats:
    """Share *folder_path* on OneDrive with an "Anyone" link, password, and expiry.

    This function is NON-FATAL: all exceptions are caught, logged at ERROR
    level, and recorded in ``ShareStats.share_errors``.  It never re-raises.

    Flow:
        1. Navigate to the parent folder.
        2. Find the folder row by base name and click its checkbox.
        3. Open the share dialog (with retry).
        4. Configure: Anyone link, expiry date, password (with retry).
        5. Click Apply and wait for the dialog to close.

    Args:
        page: Authenticated Playwright page.
        folder_path: Relative OneDrive path to the folder to share.
        password: Pre-generated password for the sharing link.
        expiry_date: Expiry datetime (will be formatted as ``DD/MM/YYYY``).

    Returns:
        ShareStats with the folder base name in either ``shared`` or
        ``share_errors`` depending on outcome.
    """
    stats = ShareStats()
    key = folder_key(folder_path)
    expiry_str = _format_expiry(expiry_date)

    try:
        # Derive parent path and leaf name for navigation + row lookup
        parts = folder_path.rstrip("/").rsplit("/", 1)
        if len(parts) == 2:
            parent_path, leaf_name = parts[0], parts[1]
        else:
            parent_path, leaf_name = "", parts[0]

        # Navigate to the parent folder so the target row is visible.
        # parent_path="" navigates to root Documents — correct for top-level paths.
        navigate_to_folder(page, parent_path)

        # Open share dialog (retried)
        _open_share_dialog(page, leaf_name)

        # Configure share settings (retried)
        _apply_share_settings(page, password, expiry_str)

        # Click Apply and wait for dialog close
        _click_apply(page)

        stats.shared.append(key)
        logger.info(
            "SHARE_OK | folder={folder} | expiry={expiry}",
            folder=key,
            expiry=expiry_str,
        )

    except ShareError as exc:
        stats.share_errors.append(key)
        logger.error(
            "SHARE_ERROR | folder={folder} | reason={reason}",
            folder=key,
            reason=str(exc),
        )
    except Exception as exc:
        stats.share_errors.append(key)
        logger.error(
            "SHARE_ERROR | folder={folder} | unexpected | reason={reason}",
            folder=key,
            reason=str(exc),
        )

    return stats
