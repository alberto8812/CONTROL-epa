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

    share_urls: dict = field(default_factory=dict)
    """Mapping of folder base_name -> OneDrive sharing URL captured from 'Copiar vínculo'."""


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


def _scan_iframe_for_share_url(frame) -> "str | None":
    """Scan the shareFrame iframe HTML for an OneDrive sharing URL.

    OneDrive sharing URLs always contain ``/:f:/`` (folder) or ``/:b:/`` (file)
    in the path, which distinguishes them from plain SharePoint path URLs that
    require authentication.  Scanning the rendered HTML is more reliable than
    clipboard APIs in headless Playwright because it needs no permissions and is
    unaffected by iframe navigations or async clipboard writes.

    Args:
        frame: The shareFrame Frame object (may be None).

    Returns:
        The first sharing URL found, or ``None`` if not found.
    """
    if frame is None:
        return None
    try:
        result = frame.evaluate("""() => {
            // Primary: regex search across rendered HTML for /:f:/ or /:b:/ pattern
            const html = document.documentElement.innerHTML;
            const re = /https:[^\\s"'<>]+\\/:[fb]:[^\\s"'<>]+/;
            const m = html.match(re);
            if (m) return m[0];

            // Fallback: scan all element attributes for a URL with ?e= (sharing token)
            for (const el of document.querySelectorAll('*')) {
                for (const attr of el.attributes) {
                    const v = attr.value;
                    if (v && v.startsWith('http') && v.includes('sharepoint') &&
                        (v.includes(':f:') || v.includes('?e='))) {
                        return v;
                    }
                }
            }
            return null;
        }""")
        if result and isinstance(result, str) and result.startswith("http"):
            return result
    except Exception:
        pass
    return None


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
      2. Gear icon ⚙️ → "Configuración de vínculos" settings panel (expiry / password).

    URL capture happens AFTER Apply (in ``_click_apply``), once password and expiry are
    configured — so the link used in the report matches the fully-configured share link.

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

    # Wait for invite panel to fully render — gear icon is a reliable proxy for both
    # the gear and the "Copiar vínculo" button being present in the invite panel footer.
    try:
        frame.wait_for_selector(SHARE_SELECTORS["settings_button"], state="visible", timeout=ACTION_TIMEOUT_MS)
    except Exception as exc:
        raise ShareError(f"Invite panel gear icon did not appear for {folder_name!r}: {exc}") from exc

    # Step 2: Click the gear → opens "Configuración de vínculos" settings panel
    # URL capture happens AFTER Apply (in _click_apply), once password and expiry are set.
    try:
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
    # Retry once if the input value does not reflect the typed date afterwards.
    try:
        expiry_input = frame.locator(SHARE_SELECTORS["expiry_input"]).first
        expiry_input.wait_for(state="visible", timeout=ACTION_TIMEOUT_MS)

        for attempt in range(2):
            expiry_input.click(timeout=ACTION_TIMEOUT_MS)
            page.wait_for_timeout(600)  # calendar popup needs time to render
            page.keyboard.type(expiry_str)  # "DD/MM/YYYY"
            page.keyboard.press("Tab")      # confirm selection and close popup
            page.wait_for_timeout(500)

            # Verify the date was accepted — read back the input value.
            try:
                actual = expiry_input.get_attribute("value", timeout=2_000) or ""
            except Exception:
                actual = ""
            if expiry_str in actual or actual.strip():
                break  # date landed — stop retrying
            if attempt == 0:
                logger.debug(
                    "SHARE | expiry date may not have landed (got {v!r}), retrying",
                    v=actual,
                )
    except Exception as exc:
        raise ShareError(f"Could not set expiry date {expiry_str!r}: {exc}") from exc

    # Fill password field — standard input, .fill() works directly.
    try:
        pwd_input = frame.locator(SHARE_SELECTORS["password_input"]).first
        pwd_input.wait_for(state="visible", timeout=ACTION_TIMEOUT_MS)
        pwd_input.fill(password, timeout=ACTION_TIMEOUT_MS)
    except Exception as exc:
        raise ShareError(f"Could not fill password field: {exc}") from exc

    # When the folder already has a sharing link with a password, OneDrive shows
    # "¿Quieres actualizar el vínculo?" with two options: use a new password or keep
    # the existing one.  We always choose "Usar nueva contraseña" so that the password
    # in the Excel report matches the actual link password.
    try:
        frame.wait_for_selector(
            SHARE_SELECTORS["use_new_password_button"],
            state="visible",
            timeout=3_000,
        )
        frame.click(SHARE_SELECTORS["use_new_password_button"], timeout=ACTION_TIMEOUT_MS)
        page.wait_for_timeout(400)
        logger.debug("SHARE | dismissed 'update link?' dialog — chose new password")
    except Exception:
        pass  # dialog didn't appear — normal for first-time shares


def _click_apply(page: "Page") -> "str | None":  # type: ignore[name-defined]
    """Click Apply, capture the sharing URL from 'Copiar vínculo', then close the dialog.

    After clicking Apply, OneDrive returns to the invite panel (the shareFrame iframe
    stays open). The sharing URL is captured by injecting a clipboard interceptor into
    the iframe before clicking "Copiar vínculo", then reading the intercepted value.
    Falls back to a DOM scan if the interceptor misses. Both strategies are fail-open:
    any exception returns None without raising.

    Args:
        page: Authenticated Playwright page.

    Returns:
        The OneDrive sharing URL (the one from "Copiar vínculo"), or None if capture fails.

    Raises:
        ShareError: If the Apply button cannot be clicked.
    """
    frame = _get_share_frame(page)

    try:
        frame.click(SHARE_SELECTORS["apply_button"], timeout=ACTION_TIMEOUT_MS)
    except Exception as exc:
        raise ShareError(f"Could not click apply button: {exc}") from exc

    # After clicking Apply, OneDrive may show "¿Quieres actualizar el vínculo?"
    # when the link already has a password configured from a previous run.
    # This dialog blocks the invite panel — it MUST be dismissed before the
    # "Copiar vínculo" button becomes accessible.
    try:
        frame.wait_for_selector(
            SHARE_SELECTORS["use_new_password_button"],
            state="visible",
            timeout=4_000,
        )
        frame.click(SHARE_SELECTORS["use_new_password_button"], timeout=ACTION_TIMEOUT_MS)
        page.wait_for_timeout(500)
        logger.debug("SHARE | dismissed 'update link?' dialog after Apply")
    except Exception:
        pass  # dialog didn't appear — first-time share or no existing password

    # Now the invite panel is (or will be) visible with "Copiar vínculo".
    # The iframe is stable here — the Apply navigation (settings → invite panel) has
    # already completed, so an injected interceptor will NOT be destroyed by navigation.
    #
    # Strategy: inject a writeText interceptor BEFORE clicking the copy button.
    # Reading via navigator.clipboard.readText() is intentionally avoided — it triggers
    # the browser's native "¿Quieres compartir el portapapeles?" permission dialog
    # (Bloquear / Permitir) in headed mode, which blocks the automation.
    share_url: "str | None" = None
    try:
        frame.wait_for_selector(
            SHARE_SELECTORS["copy_link_button"],
            state="visible",
            timeout=ACTION_TIMEOUT_MS,
        )

        # Inject interceptor into the now-stable invite panel context.
        frame.evaluate("""() => {
            window.__capturedUrl = null;
            if (navigator.clipboard && navigator.clipboard.writeText) {
                const _orig = navigator.clipboard.writeText.bind(navigator.clipboard);
                navigator.clipboard.writeText = function(text) {
                    window.__capturedUrl = text;
                    return _orig(text);
                };
            }
            if (document.execCommand) {
                const _origExec = document.execCommand.bind(document);
                document.execCommand = function(cmd) {
                    if (cmd === 'copy') {
                        const sel = window.getSelection();
                        if (sel && sel.toString()) window.__capturedUrl = sel.toString();
                    }
                    return _origExec.apply(document, arguments);
                };
            }
        }""")

        # Click "Copiar vínculo" — OneDrive calls writeText() → interceptor captures URL.
        frame.click(SHARE_SELECTORS["copy_link_button"], timeout=ACTION_TIMEOUT_MS)

        # Wait dynamically until the interceptor captures the URL (up to 5s).
        # A fixed 500ms sleep misses on slow connections — the writeText() call
        # may not have fired yet when we read __capturedUrl.
        try:
            frame.wait_for_function(
                "() => window.__capturedUrl !== null",
                timeout=5_000,
            )
        except Exception:
            pass  # timed out — read whatever's there, then fall back to DOM scan

        # Read captured URL — no clipboard.readText(), no browser permission prompt.
        captured = frame.evaluate("() => window.__capturedUrl")
        if captured and isinstance(captured, str) and captured.startswith("http"):
            share_url = captured

        # Fallback: scan iframe HTML for /:f:/ sharing URL pattern.
        if not share_url:
            share_url = _scan_iframe_for_share_url(frame)

        if share_url:
            logger.debug("SHARE | URL captured from invite panel after Apply")
        else:
            logger.debug("SHARE | URL capture failed — reporter will use fallback URL")
    except Exception:
        logger.debug("SHARE | copy-link URL capture failed — reporter will use fallback URL")

    # Close the dialog by pressing Escape.
    try:
        page.keyboard.press("Escape")
        page.wait_for_selector(
            SHARE_SELECTORS["share_iframe"], state="detached", timeout=ACTION_TIMEOUT_MS
        )
    except Exception:
        logger.debug("SHARE | share iframe still present after apply — proceeding anyway")

    return share_url


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

        # Configure share settings (retried) — handles "¿Quieres actualizar?" dialog
        _apply_share_settings(page, password, expiry_str)

        # Click Apply, capture URL from "Copiar vínculo" in the re-shown invite panel
        # (after password and expiry are set), then close the dialog.
        share_url = _click_apply(page)
        if share_url:
            stats.share_urls[key] = share_url

        stats.shared.append(key)
        logger.info(
            "SHARE_OK | folder={folder} | expiry={expiry} | url_captured={captured}",
            folder=key,
            expiry=expiry_str,
            captured=bool(share_url),
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
