"""
debug_select_all_toolbar.py — Probes what happens to the command bar after
clicking select-all on a large (100+ item) folder. Read-only: clicks
select-all only, never clicks delete/overflow/confirm.

Usage:
    cd onedrive_rpa && python debug_select_all_toolbar.py
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

TARGET_PATH = "camion_2/ADMIN/Bz13ff"


def dump_command_bar(page, label: str) -> None:
    print(f"\n--- Command bar state: {label} ---\n")
    try:
        info = page.evaluate("""() => {
            const result = [];
            document.querySelectorAll(
                "[role='menubar'] button, [role='toolbar'] button, "
                + "[data-automationid], button, [role='button'], [role='link']"
            ).forEach((el) => {
                const txt = (el.innerText || '').trim();
                const aria = el.getAttribute('aria-label') || '';
                const automationid = el.getAttribute('data-automationid') || '';
                if (!txt && !aria && !automationid) return;
                const visible = el.offsetParent !== null;
                if (!visible) return;
                result.push({
                    tag: el.tagName,
                    text: txt.slice(0, 60),
                    aria: aria.slice(0, 60),
                    automationid,
                    disabled: el.disabled || el.getAttribute('aria-disabled') === 'true',
                });
            });
            return result;
        }""")
        seen = set()
        for item in info:
            key = (item['text'], item['aria'], item['automationid'])
            if key in seen:
                continue
            seen.add(key)
            if 'elimina' in item['text'].lower() or 'delete' in item['text'].lower() \
               or 'more' in item['text'].lower() or 'más' in item['text'].lower() \
               or 'select' in item['aria'].lower() or 'selecc' in item['aria'].lower() \
               or item['automationid']:
                print(f"  {item}")
    except Exception as e:
        print(f"  Could not dump command bar: {e}")

    # Any banner/dialog text that might be blocking?
    try:
        banner_texts = page.evaluate("""() => {
            const rx = /seleccion|select|todos los elementos|all items/i;
            const matches = [];
            document.querySelectorAll('body *').forEach((el) => {
                if (el.children.length === 0 && el.innerText && rx.test(el.innerText)) {
                    matches.push(el.innerText.trim().slice(0, 100));
                }
            });
            return [...new Set(matches)].slice(0, 15);
        }""")
        if banner_texts:
            print("\n  Banner/selection-related text found:")
            for t in banner_texts:
                print(f"    {t!r}")
    except Exception as e:
        print(f"  Could not scan banner text: {e}")


def main():
    if not SESSION_PATH.exists():
        print("ERROR: session.json not found.")
        sys.exit(1)

    personal = SHAREPOINT_PERSONAL_PATH.rstrip("/") if SHAREPOINT_PERSONAL_PATH else ""
    url = f"{ONEDRIVE_URL.rstrip('/')}{personal}/Documents/{TARGET_PATH}"
    print(f"\nNavigating to: {url}\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(storage_state=str(SESSION_PATH))
        page = context.new_page()
        page.goto(url, timeout=NAV_TIMEOUT_MS, wait_until="load")
        time.sleep(5)

        try:
            page.wait_for_selector(SELECTORS["folder_row"], timeout=20_000, state="attached")
        except Exception as e:
            print(f"WARNING: rows not attached after 20s: {e}")
            print(f"Current URL: {page.url}")
            print(f"Current title: {page.title()}")
            shot = Path(__file__).parent / "debug_select_all_toolbar_early.png"
            page.screenshot(path=str(shot))
            print(f"Early screenshot saved: {shot}")
            body_text = page.evaluate("() => document.body.innerText.slice(0, 500)")
            print(f"Body text sample: {body_text!r}")

        dump_command_bar(page, "BEFORE select-all")

        print("\nClicking select-all header cell...")
        select_all_cell = page.locator(SELECTORS["select_all"])
        select_all_cell.wait_for(state="visible", timeout=ACTION_TIMEOUT_MS)
        select_all_cell.click(timeout=ACTION_TIMEOUT_MS)

        increments = (1, 2, 3, 4)  # cumulative: 1s, 3s, 6s, 10s
        cumulative = 0
        for inc in increments:
            time.sleep(inc)
            cumulative += inc
            dump_command_bar(page, f"AFTER select-all, +{cumulative}s total")

        screenshot_path = Path(__file__).parent / "debug_select_all_toolbar.png"
        page.screenshot(path=str(screenshot_path), full_page=False)
        print(f"\nScreenshot saved: {screenshot_path}")

        print("\n--- Done. Review output + screenshot. NOT clicking delete. ---")
        input("Press Enter to close the browser...")
        browser.close()


if __name__ == "__main__":
    main()
