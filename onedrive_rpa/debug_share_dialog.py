"""
debug_share_dialog.py — Inspects the DOM of the Compartir share dialog.

Usage:
    cd onedrive_rpa && python debug_share_dialog.py

Steps:
  1. Navigate to pruebas folder
  2. Select archivos_1 (checkbox)
  3. Click the Compartir toolbar button
  4. Wait 4s for the dialog to render
  5. Dump all button attributes in the dialog
  6. Save screenshot
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

PARENT_FOLDER = "pruebas"
TARGET_FOLDER = "archivos_1"


def main():
    if not SESSION_PATH.exists():
        print("ERROR: session.json not found. Run: python main.py --mode manual")
        sys.exit(1)

    personal = SHAREPOINT_PERSONAL_PATH.rstrip("/") if SHAREPOINT_PERSONAL_PATH else ""
    url = f"{ONEDRIVE_URL.rstrip('/')}{personal}/Documents/{PARENT_FOLDER}"

    print(f"\nNavigating to: {url}\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(storage_state=str(SESSION_PATH))
        page = context.new_page()

        page.goto(url, timeout=NAV_TIMEOUT_MS, wait_until="load")
        time.sleep(3)

        print(f"URL: {page.url}")
        print(f"Title: {page.title()}\n")

        # --- Step 1: find archivos_1 row and click its checkbox ---
        rows = page.locator(SELECTORS["folder_row"]).all()
        target_row = None
        for row in rows:
            try:
                name = row.locator(SELECTORS["item_name"]).inner_text(timeout=2000).strip()
                if name == TARGET_FOLDER:
                    target_row = row
                    break
            except Exception:
                continue

        if target_row is None:
            print(f"ERROR: Row '{TARGET_FOLDER}' not found")
            browser.close()
            return

        print(f"Found row: {TARGET_FOLDER}")
        checkbox = target_row.locator(SHARE_SELECTORS["row_checkbox"]).first
        checkbox.click(timeout=ACTION_TIMEOUT_MS)
        print("Checkbox clicked OK")
        time.sleep(1)

        # --- Step 2: click Compartir toolbar button ---
        try:
            page.click(SHARE_SELECTORS["share_button"], timeout=ACTION_TIMEOUT_MS)
            print("Share button clicked OK")
        except Exception as e:
            print(f"Share button FAILED: {e}")
            browser.close()
            return

        # --- Step 3: wait for dialog to render ---
        time.sleep(4)
        screenshot_path = Path(__file__).parent / "debug_share_dialog.png"
        page.screenshot(path=str(screenshot_path))
        print(f"Screenshot saved: {screenshot_path}\n")

        # --- Step 4: probe the shareFrame iframe ---
        print("=== SHARE DIALOG IFRAME (shareFrame) ===\n")

        # Wait for iframe to appear
        try:
            page.wait_for_selector('iframe[name="shareFrame"]', state="visible", timeout=10_000)
            print("iframe[name='shareFrame'] found and visible\n")
        except Exception as e:
            print(f"iframe NOT found: {e}")

        # Access the frame
        frame = page.frame(name="shareFrame")
        if frame is None:
            print("ERROR: page.frame('shareFrame') returned None")
        else:
            print(f"Frame URL: {frame.url}\n")

            # Dump ALL buttons inside the iframe
            print("--- Buttons inside iframe ---\n")
            try:
                btns_in_frame = frame.evaluate("""() => {
                    const result = [];
                    document.querySelectorAll('button, [role=button], [role=radio], [role=option]').forEach((el, i) => {
                        const attrs = {};
                        for (const a of el.attributes) { attrs[a.name] = a.value; }
                        attrs['_tag'] = el.tagName;
                        attrs['_innerText'] = el.innerText.trim().slice(0, 80);
                        attrs['_visible'] = el.offsetParent !== null || el.style.display !== 'none';
                        result.push(attrs);
                    });
                    return result;
                }""")
                for i, btn in enumerate(btns_in_frame):
                    if btn.get("_visible"):
                        print(f"  [{i}] {btn}")
            except Exception as e:
                print(f"Could not enumerate frame buttons: {e}")

            # Dump ALL inputs inside the iframe
            print("\n--- Inputs inside iframe ---\n")
            try:
                inputs_in_frame = frame.evaluate("""() => {
                    const result = [];
                    document.querySelectorAll('input, textarea').forEach((el, i) => {
                        const attrs = {};
                        for (const a of el.attributes) { attrs[a.name] = a.value; }
                        attrs['_tag'] = el.tagName;
                        attrs['_placeholder'] = el.placeholder || '';
                        attrs['_visible'] = el.offsetParent !== null;
                        result.push(attrs);
                    });
                    return result;
                }""")
                for i, inp in enumerate(inputs_in_frame):
                    if inp.get("_visible"):
                        print(f"  [{i}] {inp}")
            except Exception as e:
                print(f"Could not enumerate frame inputs: {e}")

            # --- Step 5: click the gear to open settings panel, then probe it ---
            print("\n--- Clicking gear (Footer-button-settings) to open settings panel ---\n")
            try:
                gear = frame.locator("[data-automationid='Footer-button-settings'], #Footer-button-settings, button[aria-label='Configuración de vínculos']").first
                gear.wait_for(state="visible", timeout=5000)
                gear.click(timeout=5000)
                print("Gear clicked OK")
                time.sleep(3)
            except Exception as e:
                print(f"Gear click FAILED: {e}")

            # Dump buttons in settings panel
            print("\n--- Buttons in settings panel (inside iframe) ---\n")
            try:
                btns2 = frame.evaluate("""() => {
                    const result = [];
                    document.querySelectorAll('button, [role=button], [role=radio], [role=option]').forEach((el, i) => {
                        const attrs = {};
                        for (const a of el.attributes) { attrs[a.name] = a.value; }
                        attrs['_tag'] = el.tagName;
                        attrs['_innerText'] = el.innerText.trim().slice(0, 80);
                        attrs['_visible'] = el.offsetParent !== null || el.style.display !== 'none';
                        result.push(attrs);
                    });
                    return result;
                }""")
                for i, btn in enumerate(btns2):
                    if btn.get("_visible"):
                        print(f"  [{i}] {btn}")
            except Exception as e:
                print(f"Could not enumerate settings panel buttons: {e}")

            # Dump inputs in settings panel
            print("\n--- Inputs in settings panel (inside iframe) ---\n")
            try:
                inputs2 = frame.evaluate("""() => {
                    const result = [];
                    document.querySelectorAll('input, textarea').forEach((el, i) => {
                        const attrs = {};
                        for (const a of el.attributes) { attrs[a.name] = a.value; }
                        attrs['_tag'] = el.tagName;
                        attrs['_placeholder'] = el.placeholder || '';
                        attrs['_type'] = el.type || '';
                        attrs['_visible'] = el.offsetParent !== null;
                        result.push(attrs);
                    });
                    return result;
                }""")
                for i, inp in enumerate(inputs2):
                    if inp.get("_visible"):
                        print(f"  [{i}] {inp}")
            except Exception as e:
                print(f"Could not enumerate settings panel inputs: {e}")

            # Screenshot after clicking gear
            screenshot2 = Path(__file__).parent / "debug_share_settings.png"
            page.screenshot(path=str(screenshot2))
            print(f"\nScreenshot saved: {screenshot2}")

        print("\n--- Done. Check debug_share_dialog.png ---")
        input("Press Enter to close the browser...")
        browser.close()


if __name__ == "__main__":
    main()
