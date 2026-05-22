"""
debug_selectors.py — Inspecciona qué elementos encuentra Playwright en la carpeta.

Uso:
    python debug_selectors.py

Navega a pruebas/archivos_1, espera 5 segundos, y loggea:
  - URL final
  - Título de la página
  - Cantidad de elementos encontrados con los selectores actuales
  - Primeros 3 inner_text de cada selector alternativo
  - Screenshot en debug_screenshot.png
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
)

FOLDER_PATH = "pruebas/archivos_1"

SELECTORS_TO_TEST = {
    "current (DetailsRowFields)": "[data-automationid='DetailsRowFields'][data-is-focusable='true']",
    "DetailsRow":                 "[data-automationid='DetailsRow']",
    "listItem":                   "[role='listitem']",
    "row":                        "[role='row']",
    "gridcell name":              "[data-automationid='name']",
    "ms-List-cell":               ".ms-List-cell",
    "ms-DetailsRow":              ".ms-DetailsRow",
}

def main():
    if not SESSION_PATH.exists():
        print("ERROR: session.json no existe. Corré primero: python main.py --mode manual")
        sys.exit(1)

    personal = SHAREPOINT_PERSONAL_PATH.rstrip("/") if SHAREPOINT_PERSONAL_PATH else ""
    if personal:
        url = f"{ONEDRIVE_URL.rstrip('/')}{personal}/Documents/{FOLDER_PATH}"
    else:
        url = f"{ONEDRIVE_URL.rstrip('/')}/?path=/{FOLDER_PATH}"

    print(f"\nNavegando a: {url}\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(storage_state=str(SESSION_PATH))
        page = context.new_page()

        page.goto(url, timeout=NAV_TIMEOUT_MS)
        page.wait_for_load_state("networkidle", timeout=NAV_TIMEOUT_MS)

        print(f"URL final:  {page.url}")
        print(f"Título:     {page.title()}\n")

        # Esperar un poco más por si SharePoint renderiza lento
        time.sleep(5)

        print("=== Resultados de selectores ===\n")
        for name, selector in SELECTORS_TO_TEST.items():
            try:
                elements = page.locator(selector).all()
                count = len(elements)
                samples = []
                for el in elements[:3]:
                    try:
                        text = el.inner_text(timeout=2_000).strip().replace("\n", " ")[:80]
                        samples.append(f'  "{text}"')
                    except Exception:
                        samples.append('  <no text>')
                print(f"[{count:>3}] {name}")
                for s in samples:
                    print(s)
                if count > 0:
                    print()
            except Exception as exc:
                print(f"[ERR] {name}: {exc}")

        # --- Paso 2: seleccionar el archivo y capturar toolbar ---
        # --- Paso 2: flujo completo de borrado para capturar el modal ---
        print("\n=== Flujo: select-all → overflow → Eliminar → capturar modal ===\n")
        # 1. Select all
        select_all = page.locator("[data-automationid='row-selection-header']")
        try:
            select_all.wait_for(state="visible", timeout=5_000)
            select_all.click(timeout=5_000)
            print("Select-all OK")
            time.sleep(1)
        except Exception as e:
            print(f"Select-all FALLÓ: {e}")

        # 2. Abrir overflow "..."
        overflow = page.locator("[data-automationid='more'], button[aria-label='Más']").first
        try:
            overflow.wait_for(state="visible", timeout=5_000)
            overflow.click(timeout=5_000)
            print("Overflow OK")
            time.sleep(0.5)
        except Exception as e:
            print(f"Overflow FALLÓ: {e}")

        # 3. Click Eliminar en el dropdown
        delete_item = page.locator(
            "[role='menuitem'][aria-label='Eliminar'], "
            "[data-automationid='deleteCommand'], "
            "button[title='Eliminar']"
        ).first
        try:
            delete_item.wait_for(state="visible", timeout=5_000)
            delete_item.click(timeout=5_000)
            print("Eliminar clickeado OK")
            time.sleep(2)
        except Exception as e:
            print(f"Eliminar FALLÓ: {e}")

        # 4. Capturar el modal de confirmación
        print("\n=== HTML del modal de confirmación ===\n")
        for sel in ["[role='dialog']", "[role='alertdialog']", "[data-automationid='dialogMainContainer']"]:
            els = page.locator(sel).all()
            if els:
                print(f"Modal encontrado con selector: {sel}")
                print(els[0].inner_html(timeout=3_000)[:3000])
                break
        else:
            print("No se encontró modal — puede que el borrado ocurrió sin confirmación")

        screenshot_path = Path(__file__).parent / "debug_screenshot.png"
        page.screenshot(path=str(screenshot_path), full_page=True)
        print(f"\nScreenshot guardado en: {screenshot_path}")

        browser.close()


if __name__ == "__main__":
    main()
