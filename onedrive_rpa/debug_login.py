"""
debug_login.py — Diagnóstico de la página de login de OneDrive.

Abre el browser, navega a OneDrive y muestra:
- URL final
- Todos los frames (main + iframes)
- Todos los inputs encontrados en cada frame
- Si encontró los selectores del formulario

Uso:
    python debug_login.py
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from playwright.sync_api import sync_playwright
from onedrive_rpa.config import ONEDRIVE_URL, ONEDRIVE_LOGIN_URL, ONEDRIVE_USERNAME, ONEDRIVE_PASSWORD

EMAIL_SELECTORS = ["input[name='loginfmt']", "input[type='email']", "#i0116"]
PASSWORD_SELECTORS = ["input[name='passwd']", "input[type='password']", "#i0118"]

print(f"\n{'='*60}")
print(f"ONEDRIVE_USERNAME = {ONEDRIVE_URL!r}")
print(f"ONEDRIVE_USERNAME loaded = {bool(ONEDRIVE_USERNAME)} ({ONEDRIVE_USERNAME[:4]}***)")
print(f"ONEDRIVE_PASSWORD loaded = {bool(ONEDRIVE_PASSWORD)}")
print(f"{'='*60}\n")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    context = browser.new_context()
    page = context.new_page()

    print(f"[1] Navegando a {ONEDRIVE_LOGIN_URL} ...")
    page.goto(ONEDRIVE_LOGIN_URL, wait_until="domcontentloaded", timeout=60_000)
    print(f"[1] URL tras goto: {page.url}")

    print("[2] Esperando networkidle (max 30s)...")
    try:
        page.wait_for_load_state("networkidle", timeout=30_000)
        print("[2] networkidle alcanzado")
    except Exception as e:
        print(f"[2] networkidle timeout: {e}")

    print(f"[3] URL final: {page.url}")

    print(f"\n[4] Frames en la página ({len(page.frames)} total):")
    for i, frame in enumerate(page.frames):
        label = "(MAIN)" if frame == page.main_frame else f"(iframe {i})"
        print(f"    {label} url={frame.url}")

    print("\n[5] Buscando inputs en cada frame:")
    for i, frame in enumerate(page.frames):
        label = "MAIN" if frame == page.main_frame else f"iframe-{i}"
        try:
            inputs = frame.locator("input").all()
            if inputs:
                print(f"\n  [{label}] {len(inputs)} input(s) encontrados:")
                for inp in inputs:
                    try:
                        attrs = {
                            "name": inp.get_attribute("name"),
                            "type": inp.get_attribute("type"),
                            "id":   inp.get_attribute("id"),
                            "placeholder": inp.get_attribute("placeholder"),
                            "visible": inp.is_visible(),
                        }
                        print(f"    {attrs}")
                    except Exception as e:
                        print(f"    (error leyendo atributos: {e})")
            else:
                print(f"\n  [{label}] sin inputs")
        except Exception as e:
            print(f"\n  [{label}] error: {e}")

    print("\n[6] Probando selectores de email:")
    for sel in EMAIL_SELECTORS:
        for i, frame in enumerate(page.frames):
            label = "MAIN" if frame == page.main_frame else f"iframe-{i}"
            try:
                loc = frame.locator(sel).first
                loc.wait_for(state="visible", timeout=2_000)
                print(f"  ENCONTRADO '{sel}' en {label}")
            except Exception:
                pass

    print("\n[7] Probando selectores de password:")
    for sel in PASSWORD_SELECTORS:
        for i, frame in enumerate(page.frames):
            label = "MAIN" if frame == page.main_frame else f"iframe-{i}"
            try:
                loc = frame.locator(sel).first
                loc.wait_for(state="visible", timeout=2_000)
                print(f"  ENCONTRADO '{sel}' en {label}")
            except Exception:
                pass

    print("\n[8] Browser abierto — cerralo manualmente cuando termines de revisar.")
    input("Presioná ENTER para cerrar el browser y terminar...\n")
    browser.close()

print("Listo.")
