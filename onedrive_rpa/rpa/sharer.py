"""
rpa/sharer.py — Folder sharing via OneDrive's "Compartir" dialog.

After a folder is cleaned, share_folder() creates an "Anyone" sharing link
with a password and expiry date.  Failures are non-fatal: every exception is
caught, logged at ERROR level, and recorded in ShareStats — the run continues.

Pure helpers (folder_key, _format_expiry) have no Playwright dependency and
are fully unit-testable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime

from loguru import logger

from onedrive_rpa.config import (
    SELECTORS,
    SHARE_SELECTORS,
    SHARE_MONTH_NAMES,
    SHARE_CALENDAR_MAX_MONTH_STEPS,
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


_MONTH_YEAR_RE = re.compile(r"([a-záéíóúñ]+)\D*?(\d{4})", re.IGNORECASE)


def _parse_month_year(label: str) -> tuple[int, int]:
    """Parse a localized month/year calendar header into ``(month, year)``.

    Handles both Spanish (``"agosto de 2026"``, ``"agosto 2026"``) and
    English (``"August 2026"``) headers, case-insensitive.

    Args:
        label: The calendar header text.

    Returns:
        ``(month, year)`` where ``month`` is 1-12.

    Raises:
        ShareError: If *label* cannot be parsed into a known month name and a
                    4-digit year.
    """
    match = _MONTH_YEAR_RE.search(label.strip())
    if not match:
        raise ShareError(f"Could not parse calendar header {label!r}")

    month_name = match.group(1).lower()
    year_str = match.group(2)

    month = SHARE_MONTH_NAMES.get(month_name)
    if month is None:
        raise ShareError(f"Unknown month name {month_name!r} in calendar header {label!r}")

    return month, int(year_str)


def _month_delta(from_my: tuple[int, int], to_my: tuple[int, int]) -> int:
    """Return the signed number of months from *from_my* to *to_my*.

    Args:
        from_my: ``(month, year)`` of the starting point.
        to_my: ``(month, year)`` of the target.

    Returns:
        Positive if *to_my* is later, negative if earlier, 0 if equal.
        E.g. ``(2026, 12) -> (2027, 1)`` is ``1``;
             ``(2026, 8) -> (2026, 8)`` is ``0``;
             ``(2027, 1) -> (2026, 12)`` is ``-1``.
    """
    from_month, from_year = from_my
    to_month, to_year = to_my
    return (to_year - from_year) * 12 + (to_month - from_month)


def _expiry_matches(actual: str, expected: datetime) -> bool:
    """Strict semantic comparison between a read-back date string and *expected*.

    Replaces the old loose check (``expiry_str in actual or actual.strip()``)
    which silently accepted ANY non-empty value — including an empty-looking
    string that still had a truthy `.strip()` due to whitespace-adjacent bugs
    — as success. This function requires the string to actually parse to the
    same calendar date as *expected*.

    Args:
        actual: The raw string read back from the expiry input (e.g. via
                ``input_value()``).
        expected: The datetime the input is supposed to represent.

    Returns:
        ``True`` only if *actual* parses (as ``%d/%m/%Y``, zero-padded or
        not) to the same ``.date()`` as *expected*. ``False`` for empty,
        whitespace-only, or unparseable input — including ISO-formatted
        dates, which this input format never produces.
    """
    stripped = actual.strip()
    if not stripped:
        return False

    # %d/%m/%Y already accepts non-zero-padded day/month (e.g. "8/6/2026") in
    # CPython's strptime, so a single attempt covers both the zero-padded and
    # lenient forms. A manual split is kept as a defensive fallback in case
    # that leniency ever changes across Python versions.
    try:
        parsed = datetime.strptime(stripped, "%d/%m/%Y")
        return parsed.date() == expected.date()
    except ValueError:
        pass

    parts = stripped.split("/")
    if len(parts) == 3:
        try:
            day, month, year = (int(p) for p in parts)
            return date(year, month, day) == expected.date()
        except ValueError:
            return False

    # Fluent UI's own input_value() does NOT echo back "DD/MM/YYYY" — it
    # renders the full localized date, e.g. "miércoles, 5 de ago de 2026"
    # (confirmed via live probe against a real share dialog). Extract
    # day/month-token/year regardless of the leading weekday name, then
    # resolve the month token (abbreviated or full, ES or EN) against
    # SHARE_MONTH_NAMES by prefix match (Spanish abbreviations like "ago"
    # are simple prefixes of the full name, e.g. "agosto").
    match = re.search(r"(\d{1,2})\s+de\s+([a-záéíóúñ]+)\.?\s+de\s+(\d{4})", stripped, re.IGNORECASE)
    if match:
        day_str, month_token, year_str = match.groups()
        month_token = month_token.lower().rstrip(".")
        month = SHARE_MONTH_NAMES.get(month_token)
        if month is None:
            for name, num in SHARE_MONTH_NAMES.items():
                if name.startswith(month_token) or month_token.startswith(name):
                    month = num
                    break
        if month is not None:
            try:
                return date(int(year_str), month, int(day_str)) == expected.date()
            except ValueError:
                return False

    return False


def _day_button_selector(day: int, month_name: str, year: int) -> str:
    """Build the Playwright selector for a calendar day-button cell.

    Day cells are ``<button class="fui-CalendarDayGrid__dayButton ...">``
    with an ``aria-label`` in the exact format ``"{day}, {MonthName}, {year}"``
    (e.g. ``"6, Julio, 2026"``) — no leading zero on the day, the fully
    localized month name, and no "de" between the parts.

    Args:
        day: Day of month, 1-31 (no zero-padding — matches the DOM's format).
        month_name: The exact localized month name string as rendered by the
                    tenant (read live from an existing day cell's aria-label —
                    never hardcoded, since it must match the tenant's locale).
        year: Full 4-digit year.

    Returns:
        A CSS attribute selector scoped to ``button.fui-CalendarDayGrid__dayButton``
        so it can never accidentally match the unrelated
        ``.od-ExpirationDatePicker-delete`` ("Quitar fecha de caducidad") button.
    """
    label = f"{day}, {month_name}, {year}"
    return f"button.fui-CalendarDayGrid__dayButton[aria-label='{label}']"


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


def _set_expiry_date(page: "Page", frame: "Frame", expiry_date: datetime) -> None:  # type: ignore[name-defined]
    """Set the sharing link expiry date via real calendar-click navigation.

    The expiry input is a readOnly Fluent UI control: ``.fill()``/``.clear()``
    are rejected and keystrokes typed via ``page.keyboard.type()`` are
    swallowed by the calendar callout it opens — there is no way to set the
    date by typing. The only reliable approach is genuine UI navigation:

        1. Fast path: if the input already shows the target date, return.
        2. Click the input — this opens a calendar callout directly (no
           separate icon click needed).
        3. Read the callout's month/year header, parse it, and compute how
           many months (and which direction) separate it from the target.
        4. Click the correct nav arrow that many times, re-reading the
           header after each click to confirm it actually advanced (a
           disabled arrow would otherwise spin this forever).
        5. Once on the correct month, read the *exact* localized month name
           live from an existing day cell's ``aria-label`` — never assume a
           hardcoded string matches the tenant's rendering — then click the
           day cell built from that string.
        6. Close the callout and strictly verify via ``.input_value()`` +
           ``_expiry_matches()`` (React-controlled input — ``.input_value()``
           reflects live state; ``get_attribute("value")`` can be stale).

    The whole sequence (steps 2-6) is retried up to twice, restarting from
    the input click each time, mirroring the previous retry count.

    Args:
        page: Authenticated Playwright page (keyboard/page-level waits).
        frame: The shareFrame Frame containing the expiry input and calendar.
        expiry_date: The target expiry datetime.

    Raises:
        ShareError: If the date cannot be confirmed as set after all
                    attempts, calendar navigation stalls, or the target month
                    is unreachable within ``SHARE_CALENDAR_MAX_MONTH_STEPS``.
    """
    expiry_str = _format_expiry(expiry_date)
    expiry_input = frame.locator(SHARE_SELECTORS["expiry_input"]).first
    expiry_input.wait_for(state="visible", timeout=ACTION_TIMEOUT_MS)

    # Idempotent fast path — value may already be correct (e.g. a retried
    # outer @with_retry() attempt on _apply_share_settings itself).
    try:
        current = expiry_input.input_value(timeout=2_000)
    except Exception:
        current = ""
    if _expiry_matches(current, expiry_date):
        return

    target_my = (expiry_date.month, expiry_date.year)
    last_actual = current

    for attempt in range(2):
        try:
            expiry_input.click(timeout=ACTION_TIMEOUT_MS)

            month_year_label = frame.locator(SHARE_SELECTORS["expiry_month_year_label"]).first
            month_year_label.wait_for(state="visible", timeout=ACTION_TIMEOUT_MS)

            nav_buttons = frame.locator(SHARE_SELECTORS["expiry_month_nav_buttons"])
            prev_button = nav_buttons.nth(0)
            next_button = nav_buttons.nth(1)

            header_text = month_year_label.inner_text(timeout=ACTION_TIMEOUT_MS)
            current_my = _parse_month_year(header_text)
            delta = _month_delta(current_my, target_my)

            if abs(delta) > SHARE_CALENDAR_MAX_MONTH_STEPS:
                raise ShareError(
                    f"Expiry date {expiry_str!r} requires {abs(delta)} calendar "
                    f"month steps, exceeding SHARE_CALENDAR_MAX_MONTH_STEPS="
                    f"{SHARE_CALENDAR_MAX_MONTH_STEPS}"
                )

            button = next_button if delta > 0 else prev_button
            for _ in range(abs(delta)):
                before = month_year_label.inner_text(timeout=ACTION_TIMEOUT_MS)
                button.click(timeout=ACTION_TIMEOUT_MS)
                page.wait_for_timeout(300)
                after = month_year_label.inner_text(timeout=ACTION_TIMEOUT_MS)
                if after == before:
                    raise ShareError(
                        f"Calendar month header did not advance past {before!r} "
                        f"— nav arrow may be disabled"
                    )

            # Read the exact localized month name from the now-current header
            # text itself (e.g. "Agosto 2026" -> "Agosto"). Do NOT sample the
            # first day-cell button for this: the grid's leading cells are
            # often overflow days from the ADJACENT month (e.g. late-July
            # cells padding the first week of an August view), so ".first"
            # would silently grab the wrong month's name.
            current_header_text = month_year_label.inner_text(timeout=ACTION_TIMEOUT_MS)
            header_parts = current_header_text.rsplit(" ", 1)
            if len(header_parts) != 2:
                raise ShareError(
                    f"Could not parse month name out of calendar header "
                    f"{current_header_text!r}"
                )
            month_name = header_parts[0].strip()

            day_selector = _day_button_selector(expiry_date.day, month_name, expiry_date.year)
            day_button = frame.locator(day_selector).first
            day_button.wait_for(state="visible", timeout=ACTION_TIMEOUT_MS)
            day_button.click(timeout=ACTION_TIMEOUT_MS)

            # Let the callout close/settle before reading the value back.
            try:
                page.keyboard.press("Escape")
            except Exception:
                pass
            page.wait_for_timeout(500)

            try:
                last_actual = expiry_input.input_value(timeout=2_000)
            except Exception:
                last_actual = ""

            if _expiry_matches(last_actual, expiry_date):
                return

            logger.debug(
                "SHARE | expiry date did not land (input shows {v!r}), attempt={a}",
                v=last_actual,
                a=attempt,
            )
        except ShareError as exc:
            logger.debug(
                "SHARE | expiry calendar navigation failed on attempt {a}: {e}",
                a=attempt,
                e=str(exc),
            )

    raise ShareError(
        f"Could not set expiry date {expiry_str!r} via calendar: input shows {last_actual!r}"
    )


@with_retry()
def _apply_share_settings(page: "Page", password: str, expiry_date: datetime) -> None:  # type: ignore[name-defined]
    """Configure the share settings panel (inside shareFrame iframe).

    Decorated with @with_retry() — the settings form overwrites link state on
    each attempt, making the operation idempotent (unlike delete, ADR-7).

    Args:
        page: Authenticated Playwright page.
        password: Plaintext password for the sharing link.
        expiry_date: The target expiry datetime.

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

    # Set expiry date — the input has readonly='' so .fill()/.clear() and
    # page.keyboard.type() are both rejected/swallowed by the calendar popup
    # it opens. _set_expiry_date() drives real calendar-click navigation
    # instead (see its docstring for the full flow).
    _set_expiry_date(page, frame, expiry_date)

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
        _apply_share_settings(page, password, expiry_date)

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
