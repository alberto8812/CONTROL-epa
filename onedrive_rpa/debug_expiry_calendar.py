"""
debug_expiry_calendar.py — Inspects the DOM of the expiry-date calendar
callout inside the "Configuración de vínculos" (share settings) panel.

Read-only: opens the share dialog, the settings gear, and the expiry
calendar popup, then dumps the month/year header, nav arrows, and day
cells. Never clicks Apply — no real change is made to any sharing link.

Usage:
    cd onedrive_rpa && python debug_expiry_calendar.py

Mirrors debug_share_dialog.py's flow (reuse session.json, headed Chromium).
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
    SHARE_SELECTORS,
)

TARGET_PATH = "camion_2/ADMIN/Bz13ff"


def main():
    if not SESSION_PATH.exists():
        print("ERROR: session.json not found. Run: python main.py --mode manual")
        sys.exit(1)

    personal = SHAREPOINT_PERSONAL_PATH.rstrip("/") if SHAREPOINT_PERSONAL_PATH else ""
    url = f"{ONEDRIVE_URL.rstrip('/')}{personal}/Documents/{TARGET_PATH}"
    print(f"\nNavigating to: {url}\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(storage_state=str(SESSION_PATH))
        page = context.new_page()
        page.goto(url, timeout=NAV_TIMEOUT_MS, wait_until="load")
        time.sleep(3)

        print(f"URL: {page.url}")
        print(f"Title: {page.title()}\n")

        # --- Select the folder itself (row for the current folder isn't
        # listed inside itself; go up one level and select TARGET's last segment).
        parent_url = url.rsplit("/", 1)[0]
        target_name = TARGET_PATH.rsplit("/", 1)[-1]
        print(f"Navigating to parent to select the folder row: {parent_url}\n")
        page.goto(parent_url, timeout=NAV_TIMEOUT_MS, wait_until="load")
        time.sleep(3)

        rows = page.locator(SELECTORS["folder_row"]).all()
        target_row = None
        for row in rows:
            try:
                name = row.locator(SELECTORS["item_name"]).inner_text(timeout=2000).strip()
                if name == target_name:
                    target_row = row
                    break
            except Exception:
                continue

        if target_row is None:
            print(f"ERROR: Row '{target_name}' not found in parent listing")
            browser.close()
            return

        print(f"Found row: {target_name}")
        checkbox = target_row.locator(SHARE_SELECTORS["row_checkbox"]).first
        checkbox.click(timeout=ACTION_TIMEOUT_MS)
        time.sleep(1)

        try:
            page.click(SHARE_SELECTORS["share_button"], timeout=ACTION_TIMEOUT_MS)
            print("Share button clicked OK")
        except Exception as e:
            print(f"Share button FAILED: {e}")
            browser.close()
            return

        time.sleep(4)

        try:
            page.wait_for_selector('iframe[name="shareFrame"]', state="visible", timeout=10_000)
        except Exception as e:
            print(f"iframe NOT found: {e}")
            browser.close()
            return

        frame = page.frame(name="shareFrame")
        if frame is None:
            print("ERROR: page.frame('shareFrame') returned None")
            browser.close()
            return

        print("\n--- Clicking gear to open settings panel ---\n")
        try:
            gear = frame.locator(SHARE_SELECTORS["settings_button"]).first
            gear.wait_for(state="visible", timeout=5000)
            gear.click(timeout=5000)
            time.sleep(3)
        except Exception as e:
            print(f"Gear click FAILED: {e}")
            browser.close()
            return

        print("\n--- Clicking expiry input to open calendar callout ---\n")
        try:
            expiry_input = frame.locator(SHARE_SELECTORS["expiry_input"]).first
            expiry_input.wait_for(state="visible", timeout=10_000)
            attrs = frame.evaluate(
                """(el) => ({
                    readOnly: el.readOnly,
                    value: el.value,
                    ariaLabel: el.getAttribute('aria-label'),
                    placeholder: el.placeholder,
                    id: el.id,
                })""",
                expiry_input.element_handle(),
            )
            print(f"Expiry input attrs: {attrs}")
            expiry_input.click(timeout=ACTION_TIMEOUT_MS)
            time.sleep(1.5)
        except Exception as e:
            print(f"Expiry input click FAILED: {e}")
            browser.close()
            return

        print("\n--- Dumping calendar callout DOM (buttons, header, day cells) ---\n")
        try:
            callout_html = frame.evaluate("""() => {
                const candidates = document.querySelectorAll(
                    "[class*='DatePicker'], [class*='Callout'], [role='dialog'], [role='grid']"
                );
                let best = null;
                candidates.forEach((el) => {
                    if (el.querySelector('table') || el.querySelectorAll("[role='gridcell']").length > 0) {
                        if (!best || el.outerHTML.length < best.outerHTML.length) best = el;
                    }
                });
                return best ? best.outerHTML.slice(0, 4000) : '(no calendar callout root found)';
            }""")
            print("Callout root outerHTML (truncated 4000 chars):\n")
            print(callout_html)
        except Exception as e:
            print(f"Could not dump callout HTML: {e}")

        print("\n--- Month/year header candidates ---\n")
        try:
            headers = frame.evaluate("""() => {
                const result = [];
                document.querySelectorAll(
                    "[class*='monthAndYear'], [class*='MonthAndYear'], [aria-live], [role='heading']"
                ).forEach((el) => {
                    if (el.offsetParent !== null && el.innerText.trim()) {
                        result.push({
                            tag: el.tagName, cls: el.className,
                            automationid: el.getAttribute('data-automationid') || '',
                            text: el.innerText.trim().slice(0, 40),
                        });
                    }
                });
                return result;
            }""")
            for h in headers:
                print(f"  {h}")
        except Exception as e:
            print(f"Could not find header: {e}")

        print("\n--- Nav arrow candidates (prev/next month, broad search) ---\n")
        try:
            arrows = frame.evaluate("""() => {
                const result = [];
                document.querySelectorAll("button, [role='button']").forEach((el) => {
                    if (el.offsetParent === null) return;
                    const aria = (el.getAttribute('aria-label') || '');
                    const cls = el.className || '';
                    const icon = el.querySelector('[class*="Icon"], svg, i');
                    const isDayButton = cls.includes('dayButton') || cls.includes('DayGrid');
                    if (isDayButton) return;
                    // Any button near the CalendarDayGrid table that isn't a day cell
                    result.push({
                        cls: cls.split(' ').filter(c => !c.match(/^f[0-9a-z]{5,8}$/) && c !== '___' ).slice(0,3).join(' '),
                        automationid: el.getAttribute('data-automationid') || '',
                        aria,
                        hasIcon: !!icon,
                        iconCls: icon ? icon.className : '',
                        text: el.innerText.trim().slice(0, 20),
                    });
                });
                return result.slice(0, 30);
            }""")
            for a in arrows:
                print(f"  {a}")
        except Exception as e:
            print(f"Could not find nav arrows: {e}")

        print("\n--- Day cell candidates (sample) ---\n")
        try:
            days = frame.evaluate("""() => {
                const result = [];
                document.querySelectorAll("[role='gridcell'], td button, .ms-DatePicker-day button")
                    .forEach((el) => {
                        if (el.offsetParent !== null) {
                            const btn = el.tagName === 'BUTTON' ? el : el.querySelector('button');
                            const cls = (btn || el).className || '';
                            result.push({
                                cls, text: (btn || el).innerText.trim().slice(0, 10),
                                ariaLabel: (btn || el).getAttribute('aria-label') || '',
                                ariaSelected: (btn || el).getAttribute('aria-selected') || '',
                            });
                        }
                    });
                return result.slice(0, 45);
            }""")
            for d in days:
                print(f"  {d}")
        except Exception as e:
            print(f"Could not find day cells: {e}")

        screenshot_path = Path(__file__).parent / "debug_expiry_calendar.png"
        page.screenshot(path=str(screenshot_path))
        print(f"\nScreenshot saved: {screenshot_path}")

        print("\n--- Done. NOT clicking Apply — no real change made. ---")
        input("Press Enter to close the browser...")
        browser.close()


if __name__ == "__main__":
    main()
