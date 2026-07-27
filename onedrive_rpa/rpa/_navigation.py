"""
rpa/_navigation.py — Navigation helpers extracted from cleaner.py (ADR-R1).

These functions were previously private helpers inside cleaner.py. They are
extracted here so that reporter.py (and any future module) can reuse them
without importing the full FolderCleaner class.

Public surface:
    ItemInfo            — NamedTuple replacing the private _ItemInfo
    FolderNotFoundError — exception for missing/unreachable folders
    navigate_to_folder  — navigate Playwright page to an OneDrive folder URL
    list_items          — list visible items in the current OneDrive folder
"""

from __future__ import annotations

import time
from typing import NamedTuple

from loguru import logger
from playwright.sync_api import Page, Locator, TimeoutError as PlaywrightTimeoutError

from onedrive_rpa.config import (
    ONEDRIVE_URL,
    SHAREPOINT_PERSONAL_PATH,
    SELECTORS,
    NAV_TIMEOUT_MS,
    ACTION_TIMEOUT_MS,
    LIST_SCROLL_MAX_PASSES,
    LIST_SCROLL_SETTLE_MS,
    LIST_SCROLL_STABLE_READS,
    LIST_SCROLL_BUDGET_MS,
)
from onedrive_rpa.auth.session import check_session_expired
from onedrive_rpa.rpa._retry import with_retry


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


class ItemInfo(NamedTuple):
    """Represents a single item (file or folder) visible in an OneDrive listing."""
    name: str
    is_folder: bool


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class FolderNotFoundError(Exception):
    """Raised when the target folder does not exist in OneDrive."""


# ---------------------------------------------------------------------------
# Navigation helpers (idempotent → eligible for with_retry)
# ---------------------------------------------------------------------------


@with_retry()
def navigate_to_folder(page: Page, folder_path: str) -> None:
    """
    Navigate to the specified folder from the OneDrive root.

    Constructs the OneDrive URL for the given relative path. If the page
    redirects to login or shows "Page not found", raises FolderNotFoundError.

    Args:
        page: Authenticated Playwright page.
        folder_path: Relative path inside OneDrive, e.g. "Documentos/Reportes".

    Raises:
        FolderNotFoundError: If the folder does not exist.
        SessionExpiredError: If a login redirect is detected.
    """
    base_url = ONEDRIVE_URL.rstrip("/")
    if SHAREPOINT_PERSONAL_PATH:
        # OneDrive for Business: navigate directly to the document library
        personal = SHAREPOINT_PERSONAL_PATH.rstrip("/")
        target_url = f"{base_url}{personal}/Documents/{folder_path.lstrip('/')}"
    else:
        # OneDrive personal
        target_url = f"{base_url}/?path=/{folder_path.lstrip('/')}"

    page.goto(target_url, timeout=NAV_TIMEOUT_MS, wait_until="load")
    # Wait for folder rows to appear (faster than networkidle on SharePoint)
    try:
        page.wait_for_selector(SELECTORS["folder_row"], timeout=ACTION_TIMEOUT_MS, state="attached")
    except PlaywrightTimeoutError:
        pass  # Empty folder is valid

    check_session_expired(page)

    # Detect "Page not found" or equivalent
    if "Page not found" in page.title() or "not found" in page.url.lower():
        raise FolderNotFoundError(f"Folder not found: {folder_path}")


def _read_row(row: Locator) -> ItemInfo | None:
    """
    Extract (name, is_folder) from a single already-attached row Locator.

    Shared by list_items() and _scroll_until_stable() so both walk the DOM
    with exactly one extraction implementation — returns None (instead of
    raising) for a stale/unmounted/nameless row so callers can skip it with
    a plain truthiness check, matching the try/except-per-row tolerance the
    original single-pass list_items() already relied on.
    """
    try:
        name_el = row.locator(SELECTORS["item_name"])
        # Row is already attached — 2 s is more than enough to read text.
        name = name_el.inner_text(timeout=2_000).strip()
        if not name:
            return None

        # Detect folder by icon src / alt / container HTML.
        #
        # SharePoint may render the icon as:
        #   1. <img src="...folder..." alt="Folder|Carpeta"> (classic CDN icon)
        #   2. <i data-icon-name="FolderHorizontal" aria-label="Carpeta"> (Fluent UI)
        #   3. <svg ...> with title/aria-label (rare)
        #
        # Timeouts are tight (500 ms) because rows are already attached —
        # these calls resolve in < 10 ms when the element is present.
        icon_src = ""
        icon_alt = ""
        try:
            img_el = row.locator("[data-automationid='field-DocIcon'] img").first
            icon_src = (img_el.get_attribute("src", timeout=500) or "").lower()
            icon_alt = (img_el.get_attribute("alt", timeout=500) or "").lower()
        except Exception:
            pass

        is_folder = "folder" in icon_src or "carpeta" in icon_alt or "folder" in icon_alt

        if not is_folder:
            # Fallback: scan the entire icon cell's HTML for known folder keywords.
            # Covers Fluent UI icons ("folderhorizontal", "folder") and aria-labels.
            try:
                container_html = (
                    row.locator("[data-automationid='field-DocIcon']")
                    .first.inner_html(timeout=500)
                    .lower()
                )
                is_folder = (
                    "folder" in container_html
                    or "carpeta" in container_html
                )
            except Exception:
                pass

        return ItemInfo(name=name, is_folder=is_folder)
    except Exception:
        # Stale row or row without a name → skip
        return None


def _scroll_until_stable(page: Page) -> dict[str, ItemInfo]:
    """
    Nudge-scroll the current OneDrive listing, accumulating every distinct
    item name seen, until a nudge stops surfacing anything new.

    A live DOM probe against a 103-item folder found the mounted-row list is
    a SLIDING WINDOW (rows unmount as new ones mount, e.g. 61 → 43), so raw
    row-count stability is not a valid "seen everything" signal — it can
    shrink even while new items are still being discovered. The probe also
    found ``page.mouse.wheel`` does nothing here (the list container isn't a
    real overflow-scroll element); the gesture that actually mounts more
    rows is calling ``scroll_into_view_if_needed()`` on the last mounted row,
    which is now the primary nudge (``page.mouse.wheel`` is kept only as a
    harmless best-effort fallback attempt).

    Stops when a nudge adds zero new distinct names for
    ``LIST_SCROLL_STABLE_READS`` consecutive nudges, or when either
    ``LIST_SCROLL_MAX_PASSES`` passes or ``LIST_SCROLL_BUDGET_MS`` wall-clock
    time is exceeded — whichever limit is hit first triggers a WARNING log
    instead of a stable exit.

    Args:
        page: Playwright page at an OneDrive folder view.

    Returns:
        Dict mapping every distinct item name seen across all nudges to its
        ItemInfo (last read wins on a name collision, which never changes
        is_folder in practice since names are unique within a folder).
    """
    start = time.monotonic()
    stable_streak = 0
    accumulated: dict[str, ItemInfo] = {}

    def _read_current_rows() -> list[Locator]:
        return page.locator(SELECTORS["folder_row"]).all()

    def _merge(rows: list[Locator]) -> int:
        """Read *rows*, merge into accumulated, return count of NEW names."""
        new_count = 0
        for row in rows:
            item = _read_row(row)
            if item is None:
                continue
            if item.name not in accumulated:
                new_count += 1
            accumulated[item.name] = item
        return new_count

    rows = _read_current_rows()
    _merge(rows)

    for _ in range(LIST_SCROLL_MAX_PASSES):
        elapsed_ms = (time.monotonic() - start) * 1000
        if elapsed_ms >= LIST_SCROLL_BUDGET_MS:
            logger.warning(
                "SCROLL_BUDGET_EXCEEDED | elapsed_ms={elapsed:.0f} | items={n}",
                elapsed=elapsed_ms,
                n=len(accumulated),
            )
            return accumulated

        if not rows:
            # Empty listing — nothing mounted to scroll into view.
            break

        try:
            rows[-1].scroll_into_view_if_needed(timeout=ACTION_TIMEOUT_MS)
        except Exception:
            # Defense-in-depth only — the confirmed-broken gesture, kept in
            # case a future DOM variant makes the container truly scrollable.
            try:
                page.mouse.wheel(0, 2000)
            except Exception:
                pass

        page.wait_for_timeout(LIST_SCROLL_SETTLE_MS)

        rows = _read_current_rows()
        new_count = _merge(rows)

        if new_count == 0:
            stable_streak += 1
            if stable_streak >= LIST_SCROLL_STABLE_READS:
                return accumulated
        else:
            stable_streak = 0

    logger.warning(
        "SCROLL_MAX_PASSES_REACHED | passes={passes} | items={n}",
        passes=LIST_SCROLL_MAX_PASSES,
        n=len(accumulated),
    )
    return accumulated


@with_retry()
def list_items(page: Page, *, exhaustive: bool = True) -> list[ItemInfo]:
    """
    Return all visible items in the current OneDrive folder.

    Distinguishes folders from files by checking the item icon src:
    if the src contains "folder" (case-insensitive) → is a folder.

    Args:
        page: Playwright page at an OneDrive folder view.
        exhaustive: When True (default), calls _scroll_until_stable() before
            the final DOM read so virtualized/paginated listings (Fluent UI
            DetailsList) get a chance to mount all rows, not just the ones
            rendered on first paint. Pass False to keep the old fast
            single-read behavior (e.g. call sites that only need a quick,
            approximate peek and can tolerate truncation on large folders).

    Returns:
        List of ItemInfo instances. Empty list if the folder contains no items.

    Note:
        The @with_retry() decorator here only fires on Playwright exceptions
        (e.g. a stale/detached page). It does NOT retry when the listing
        merely "looks incomplete but is stable" — reconciling that case is
        the caller's responsibility (see cleaner.py's verify-and-redo loop
        around _diff_listing()), not this function's.
    """
    # Wait for at least one row or confirm the listing is empty
    try:
        page.wait_for_selector(
            SELECTORS["folder_row"],
            timeout=ACTION_TIMEOUT_MS,
            state="attached",
        )
    except PlaywrightTimeoutError:
        # Empty folder is valid
        return []

    if exhaustive:
        # _scroll_until_stable() already merges every nudge's DOM read (the
        # final one included) into one accumulated dict — re-reading the DOM
        # here again would just re-derive a subset of what it already saw.
        accumulated = _scroll_until_stable(page)
        return list(accumulated.values())

    rows: list[Locator] = page.locator(SELECTORS["folder_row"]).all()
    items: list[ItemInfo] = []

    for row in rows:
        item = _read_row(row)
        if item is not None:
            items.append(item)

    return items
