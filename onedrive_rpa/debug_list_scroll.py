"""
debug_list_scroll.py — Probes OneDrive's virtualized/paginated list DOM to
confirm the real scroll/lazy-load mechanics for large folders (100+ items).

This is READ-ONLY / non-destructive: it only lists, scrolls, and selects
(select-all) to inspect the resulting selection-count text. It explicitly
does NOT click any delete/toolbar-delete action.

Usage:
    cd onedrive_rpa && python debug_list_scroll.py

Answers needed (see plan at ~/.claude/plans/el-proyecto-tiene-un-merry-cake.md):
  1. How many rows mount on initial load vs. the folder's real item count?
  2. Which scroll gesture actually loads more rows (mouse wheel / scroll last
     row into view / keyboard End / a "load more" element)?
  3. Does the row count monotonically converge to the real total?
  4. Does the header "select all" checkbox select ALL items (server-side) or
     only the rows currently rendered in the DOM?
  5. Is an authoritative "N elementos" count readable from inside the folder
     view itself (not just the parent view)?
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from playwright.sync_api import sync_playwright
from onedrive_rpa.config import (
    ONEDRIVE_URL,
    SHAREPOINT_PERSONAL_PATH,
    SESSION_PATH,
    NAV_TIMEOUT_MS,
    ACTION_TIMEOUT_MS,
    SELECTORS,
)

TARGET_PATH = "camion_2/ADMIN/Bz13ff"  # known to have 103 items in the OneDrive UI
EXPECTED_COUNT_HINT = 103


def row_count(page) -> int:
    return page.locator(SELECTORS["folder_row"]).count()


def dump_scroll_container(page) -> None:
    print("\n--- Candidate scrollable containers (data-automationid / class / overflow) ---\n")
    try:
        info = page.evaluate("""() => {
            const result = [];
            const candidates = document.querySelectorAll(
                "[data-automationid='DetailsList'], [data-automation-id='DetailsList'], "
                + ".ms-DetailsList, .ms-List, [role='grid'], [role='presentation']"
            );
            candidates.forEach((el) => {
                const style = window.getComputedStyle(el);
                result.push({
                    tag: el.tagName,
                    id: el.id || '',
                    cls: el.className || '',
                    automationid: el.getAttribute('data-automationid') || '',
                    overflowY: style.overflowY,
                    scrollHeight: el.scrollHeight,
                    clientHeight: el.clientHeight,
                    isScrollable: el.scrollHeight > el.clientHeight,
                });
            });
            return result;
        }""")
        for i, c in enumerate(info):
            print(f"  [{i}] {c}")
        if not info:
            print("  (no candidates found matching the placeholder selector list)")
    except Exception as e:
        print(f"Could not enumerate scroll containers: {e}")


def dump_item_count_hint(page) -> None:
    print("\n--- Looking for an authoritative item-count string inside the folder view ---\n")
    try:
        texts = page.evaluate("""() => {
            const rx = /\\d+\\s*(elemento|item)/i;
            const matches = [];
            document.querySelectorAll('body *').forEach((el) => {
                if (el.children.length === 0 && el.innerText && rx.test(el.innerText)) {
                    matches.push(el.innerText.trim().slice(0, 60));
                }
            });
            return [...new Set(matches)].slice(0, 20);
        }""")
        if texts:
            for t in texts:
                print(f"  candidate text: {t!r}")
        else:
            print("  (no 'N elementos/items' text found in the DOM)")
    except Exception as e:
        print(f"Could not search for item-count text: {e}")


def main():
    if not SESSION_PATH.exists():
        print("ERROR: session.json not found. Run: python main.py --mode manual")
        sys.exit(1)

    personal = SHAREPOINT_PERSONAL_PATH.rstrip("/") if SHAREPOINT_PERSONAL_PATH else ""
    url = f"{ONEDRIVE_URL.rstrip('/')}{personal}/Documents/{TARGET_PATH}"

    print(f"\nNavigating to: {url}\n")
    print(f"Expected item count (per user-reported OneDrive UI badge): ~{EXPECTED_COUNT_HINT}\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(storage_state=str(SESSION_PATH))
        page = context.new_page()

        page.goto(url, timeout=NAV_TIMEOUT_MS, wait_until="load")
        time.sleep(3)

        print(f"URL: {page.url}")
        print(f"Title: {page.title()}\n")

        try:
            page.wait_for_selector(SELECTORS["folder_row"], timeout=ACTION_TIMEOUT_MS, state="attached")
        except Exception as e:
            print(f"ERROR: no rows appeared at all: {e}")
            browser.close()
            return

        initial = row_count(page)
        print(f"=== Q1: Initial mounted row count (no scroll yet): {initial} ===\n")

        dump_scroll_container(page)
        dump_item_count_hint(page)

        # --- Q2/Q3: try each scroll gesture in turn, measuring convergence ---
        print("\n=== Q2/Q3: Testing scroll gestures ===\n")

        print("--- Gesture A: page.mouse.wheel(0, 2000) x10 ---")
        for i in range(10):
            page.mouse.wheel(0, 2000)
            time.sleep(0.6)
            c = row_count(page)
            print(f"  after wheel #{i+1}: rows={c}")
            if c >= EXPECTED_COUNT_HINT:
                print("  -> reached/exceeded expected count, stopping this gesture test")
                break

        after_wheel = row_count(page)

        print("\n--- Gesture B: scroll_into_view_if_needed() on last currently-mounted row ---")
        for i in range(10):
            rows = page.locator(SELECTORS["folder_row"])
            n = rows.count()
            if n == 0:
                break
            try:
                rows.nth(n - 1).scroll_into_view_if_needed(timeout=ACTION_TIMEOUT_MS)
            except Exception as e:
                print(f"  scroll_into_view_if_needed failed: {e}")
                break
            time.sleep(0.6)
            c = row_count(page)
            print(f"  after scroll-into-view #{i+1}: rows={c}")
            if c >= EXPECTED_COUNT_HINT or c == n:
                if c == n:
                    print("  -> row count did not grow, likely converged or gesture ineffective")
                break

        after_scroll_into_view = row_count(page)

        print("\n--- Gesture C: keyboard 'End' key (after clicking a row for focus) ---")
        try:
            page.locator(SELECTORS["folder_row"]).first.click(timeout=ACTION_TIMEOUT_MS)
            for i in range(5):
                page.keyboard.press("End")
                time.sleep(0.6)
                c = row_count(page)
                print(f"  after End #{i+1}: rows={c}")
        except Exception as e:
            print(f"  keyboard End gesture failed: {e}")

        final_count = row_count(page)
        print(f"\n=== Row count summary: initial={initial}, after_wheel={after_wheel}, "
              f"after_scroll_into_view={after_scroll_into_view}, final={final_count}, "
              f"expected~={EXPECTED_COUNT_HINT} ===\n")

        # --- Q4: does select-all cover all items or just rendered rows? ---
        print("=== Q4: Clicking header select-all, then reading the toolbar selection-count text ===\n")
        try:
            page.click(SELECTORS["select_all"], timeout=ACTION_TIMEOUT_MS)
            time.sleep(1)
            # OneDrive typically shows "N seleccionados" / "N selected" in the command bar area.
            selection_text = page.evaluate("""() => {
                const rx = /\\d+\\s*(seleccionad|selected)/i;
                const matches = [];
                document.querySelectorAll('body *').forEach((el) => {
                    if (el.children.length === 0 && el.innerText && rx.test(el.innerText)) {
                        matches.push(el.innerText.trim().slice(0, 80));
                    }
                });
                return [...new Set(matches)];
            }""")
            if selection_text:
                for t in selection_text:
                    print(f"  selection-count text found: {t!r}")
            else:
                print("  (no 'N seleccionados/selected' text found — inspect screenshot manually)")
            rows_selected_in_dom = page.locator(
                f"{SELECTORS['folder_row']}[aria-selected='true'], "
                f"{SELECTORS['folder_row']}.is-selected"
            ).count()
            print(f"  rows with aria-selected/is-selected in current DOM: {rows_selected_in_dom} "
                  f"(mounted rows at this point: {row_count(page)})")
        except Exception as e:
            print(f"  select-all click failed: {e}")

        screenshot_path = Path(__file__).parent / "debug_list_scroll.png"
        page.screenshot(path=str(screenshot_path))
        print(f"\nScreenshot saved: {screenshot_path}")

        # Deselect before closing — do NOT leave a bulk selection dangling, and
        # never click delete from this script (read-only probe).
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass

        print("\n--- Done. Review the output above and debug_list_scroll.png ---")
        input("Press Enter to close the browser...")
        browser.close()


if __name__ == "__main__":
    main()
