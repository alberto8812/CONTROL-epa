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

from typing import NamedTuple

from playwright.sync_api import Page, Locator, TimeoutError as PlaywrightTimeoutError

from onedrive_rpa.config import (
    ONEDRIVE_URL,
    SHAREPOINT_PERSONAL_PATH,
    SELECTORS,
    NAV_TIMEOUT_MS,
    ACTION_TIMEOUT_MS,
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


@with_retry()
def list_items(page: Page) -> list[ItemInfo]:
    """
    Return all visible items in the current OneDrive folder.

    Distinguishes folders from files by checking the item icon src:
    if the src contains "folder" (case-insensitive) → is a folder.

    Args:
        page: Playwright page at an OneDrive folder view.

    Returns:
        List of ItemInfo instances. Empty list if the folder contains no items.
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

    rows: list[Locator] = page.locator(SELECTORS["folder_row"]).all()
    items: list[ItemInfo] = []

    for row in rows:
        try:
            name_el = row.locator(SELECTORS["item_name"])
            name = name_el.inner_text(timeout=ACTION_TIMEOUT_MS).strip()
            if not name:
                continue

            # Detect folder by icon src / alt / container HTML.
            #
            # SharePoint may render the icon as:
            #   1. <img src="...folder..." alt="Folder|Carpeta"> (classic CDN icon)
            #   2. <i data-icon-name="FolderHorizontal" aria-label="Carpeta"> (Fluent UI)
            #   3. <svg ...> with title/aria-label (rare)
            #
            # We try the img approach first (cheapest), then fall back to inner_html
            # of the whole icon cell so we catch Fluent-UI icon names in the markup.
            icon_src = ""
            icon_alt = ""
            try:
                img_el = row.locator("[data-automationid='field-DocIcon'] img").first
                icon_src = (img_el.get_attribute("src", timeout=2_000) or "").lower()
                icon_alt = (img_el.get_attribute("alt", timeout=2_000) or "").lower()
            except Exception:
                pass

            is_folder = "folder" in icon_src or "carpeta" in icon_alt or "folder" in icon_alt

            if not is_folder:
                # Fallback: scan the entire icon cell's HTML for known folder keywords.
                # Covers Fluent UI icons ("folderhorizontal", "folder") and aria-labels.
                try:
                    container_html = (
                        row.locator("[data-automationid='field-DocIcon']")
                        .first.inner_html(timeout=2_000)
                        .lower()
                    )
                    is_folder = (
                        "folder" in container_html
                        or "carpeta" in container_html
                    )
                except Exception:
                    pass

            items.append(ItemInfo(name=name, is_folder=is_folder))
        except Exception:
            # Stale row or row without a name → skip
            continue

    return items
