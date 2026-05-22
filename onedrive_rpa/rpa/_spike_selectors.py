"""
_spike_selectors.py — Script temporal de verificación de selectores ARIA.

PROPÓSITO:
    Verificar qué selectores CSS/ARIA usa la UI real de OneDrive antes de
    codificarlos en config.py. Este archivo es DESCARTABLE — se elimina en
    Phase 5 (task 5.5).

CÓMO CORRERLO:
    cd C:\\Users\\SoporteQA2
    python -m onedrive_rpa.rpa._spike_selectors

FLUJO:
    1. Abre Chromium en modo visible (headful).
    2. Navega a OneDrive.
    3. Pausa con page.pause() — inspector de Playwright se abre.
    4. El usuario hace login manual y navega hasta una carpeta con archivos.
    5. El usuario presiona "Resume" en el inspector.
    6. El script inspecciona los ítems visibles e imprime resultados.
    7. Muestra un resumen de qué hay que actualizar en config.py.
"""

from __future__ import annotations

import sys
from typing import NamedTuple

from playwright.sync_api import sync_playwright, Page, Locator

# ---------------------------------------------------------------------------
# Constantes de búsqueda — candidatos a probar en orden de probabilidad
# ---------------------------------------------------------------------------

# OneDrive suele usar role="row" con aria-label que empieza con "Folder," o
# "File,". Probamos variantes para cubrir OneDrive Personal y SharePoint.
_CANDIDATE_FOLDER_SELECTORS = [
    "[role='row'][aria-label^='Folder,']",
    "[role='row'][aria-label^='Carpeta,']",          # UI en español
    "[role='listitem'][aria-label^='Folder,']",
    "[data-automationid='DetailsRowFields'][aria-label^='Folder,']",
]

_CANDIDATE_FILE_SELECTORS = [
    "[role='row'][aria-label^='File,']",
    "[role='row'][aria-label^='Archivo,']",          # UI en español
    "[role='listitem'][aria-label^='File,']",
    "[data-automationid='DetailsRowFields'][aria-label^='File,']",
]

_CANDIDATE_CONTEXT_MENU_TRIGGERS = [
    "button[aria-label='Show actions']",
    "button[aria-label='Mostrar acciones']",         # UI en español
    "button[aria-label='More actions']",
    "button[aria-label='More options']",
    "[data-automationid='more-actions-button']",
    "[aria-label='Open context menu']",
]

_CANDIDATE_DELETE_OPTIONS = [
    "[role='menuitem'][aria-label='Delete']",
    "[role='menuitem'][aria-label='Eliminar']",      # UI en español
    "[role='menuitem'][text()='Delete']",
    "button[aria-label='Delete']",
    "[data-automationid='deleteButton']",
]

_CANDIDATE_CONFIRM_DELETE = [
    "button[aria-label='Delete']",
    "button[aria-label='Eliminar']",
    "[data-automationid='confirmButton']",
    "button:has-text('Delete')",
    "button:has-text('Eliminar')",
    "button:has-text('OK')",
]

# Máximo de ítems a inspeccionar en la lista visible
_MAX_ROWS_TO_INSPECT = 15


# ---------------------------------------------------------------------------
# Tipos de resultado
# ---------------------------------------------------------------------------

class SelectorResult(NamedTuple):
    key: str
    working_selector: str | None
    count_found: int
    sample_aria_labels: list[str]
    all_candidates_tried: list[str]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _first_working(page: Page, candidates: list[str], timeout_ms: int = 3000) -> tuple[str | None, int]:
    """
    Prueba cada selector de la lista. Devuelve (selector, count) para el
    primero que encuentre al menos un elemento visible, o (None, 0) si ninguno.
    """
    for selector in candidates:
        try:
            locator: Locator = page.locator(selector)
            count = locator.count()
            if count > 0:
                return selector, count
        except Exception:
            continue
    return None, 0


def _sample_aria_labels(page: Page, selector: str, limit: int = 5) -> list[str]:
    """
    Devuelve hasta `limit` aria-label de los elementos que matchean el selector.
    """
    labels: list[str] = []
    try:
        locator = page.locator(selector)
        total = min(locator.count(), limit)
        for i in range(total):
            label = locator.nth(i).get_attribute("aria-label") or ""
            if label:
                labels.append(label)
    except Exception:
        pass
    return labels


def _inspect_raw_rows(page: Page) -> None:
    """
    Fallback: imprime los primeros _MAX_ROWS_TO_INSPECT elements con role=row
    para ayudar al usuario a entender la estructura real de la UI.
    """
    print("\n  [Fallback] Buscando elementos con role='row'...")
    try:
        rows = page.locator("[role='row']")
        count = rows.count()
        print(f"  Encontrados {count} elementos con role='row'")
        for i in range(min(count, _MAX_ROWS_TO_INSPECT)):
            row = rows.nth(i)
            aria = row.get_attribute("aria-label") or "(sin aria-label)"
            tag = row.evaluate("el => el.tagName.toLowerCase()")
            print(f"    [{i}] <{tag}> aria-label={aria!r}")
    except Exception as exc:
        print(f"  Error al inspeccionar rows: {exc}")

    print("\n  [Fallback] Buscando elementos con role='listitem'...")
    try:
        items = page.locator("[role='listitem']")
        count = items.count()
        print(f"  Encontrados {count} elementos con role='listitem'")
        for i in range(min(count, _MAX_ROWS_TO_INSPECT)):
            item = items.nth(i)
            aria = item.get_attribute("aria-label") or "(sin aria-label)"
            print(f"    [{i}] aria-label={aria!r}")
    except Exception as exc:
        print(f"  Error al inspeccionar listitems: {exc}")


def _probe_selector(page: Page, key: str, candidates: list[str]) -> SelectorResult:
    working, count = _first_working(page, candidates)
    samples: list[str] = []
    if working:
        samples = _sample_aria_labels(page, working)
    return SelectorResult(
        key=key,
        working_selector=working,
        count_found=count,
        sample_aria_labels=samples,
        all_candidates_tried=candidates,
    )


# ---------------------------------------------------------------------------
# Inspección principal
# ---------------------------------------------------------------------------

def run_spike(page: Page) -> list[SelectorResult]:
    """
    Ejecuta todas las pruebas de selectores y devuelve los resultados.
    Se llama DESPUÉS de que el usuario reanuda desde page.pause().
    """
    print("\n" + "=" * 60)
    print("SPIKE: Inspeccionando selectores en la página actual...")
    print(f"URL actual: {page.url}")
    print("=" * 60)

    results: list[SelectorResult] = []

    # --- Carpetas ---
    print("\n[1/5] Buscando selector de CARPETAS...")
    r = _probe_selector(page, "folder_row", _CANDIDATE_FOLDER_SELECTORS)
    results.append(r)
    if r.working_selector:
        print(f"  ENCONTRADO: {r.working_selector!r}  ({r.count_found} elemento/s)")
        for lbl in r.sample_aria_labels:
            print(f"    aria-label={lbl!r}")
    else:
        print("  NO encontrado con ningún candidato de carpeta.")

    # --- Archivos ---
    print("\n[2/5] Buscando selector de ARCHIVOS...")
    r = _probe_selector(page, "file_row", _CANDIDATE_FILE_SELECTORS)
    results.append(r)
    if r.working_selector:
        print(f"  ENCONTRADO: {r.working_selector!r}  ({r.count_found} elemento/s)")
        for lbl in r.sample_aria_labels:
            print(f"    aria-label={lbl!r}")
    else:
        print("  NO encontrado con ningún candidato de archivo.")

    # --- Context menu trigger ---
    print("\n[3/5] Buscando TRIGGER del menú contextual...")
    r = _probe_selector(page, "context_menu_trigger", _CANDIDATE_CONTEXT_MENU_TRIGGERS)
    results.append(r)
    if r.working_selector:
        print(f"  ENCONTRADO: {r.working_selector!r}  ({r.count_found} elemento/s)")
    else:
        print("  NO encontrado. (normal si el menú '...' aparece solo en hover)")

    # --- Delete option ---
    print("\n[4/5] Buscando opción DELETE en menú contextual...")
    print("  NOTA: Esta opción puede no ser visible hasta abrir el menú.")
    print("  Si el script no la encuentra, abrí el menú manualmente y volvé a correr.")
    r = _probe_selector(page, "delete_option", _CANDIDATE_DELETE_OPTIONS)
    results.append(r)
    if r.working_selector:
        print(f"  ENCONTRADO: {r.working_selector!r}  ({r.count_found} elemento/s)")
    else:
        print("  NO encontrado en DOM actual (menú probablemente cerrado).")

    # --- Confirm delete button ---
    print("\n[5/5] Buscando botón de CONFIRMACIÓN de borrado...")
    print("  NOTA: Solo aparece cuando hay un diálogo de confirmación abierto.")
    r = _probe_selector(page, "confirm_delete_button", _CANDIDATE_CONFIRM_DELETE)
    results.append(r)
    if r.working_selector:
        print(f"  ENCONTRADO: {r.working_selector!r}  ({r.count_found} elemento/s)")
    else:
        print("  NO encontrado en DOM actual (diálogo probablemente cerrado).")

    # Fallback: si folder_row y file_row no se encontraron, volcamos la estructura cruda
    folder_found = results[0].working_selector is not None
    file_found = results[1].working_selector is not None
    if not folder_found and not file_found:
        _inspect_raw_rows(page)

    return results


# ---------------------------------------------------------------------------
# Reporte final
# ---------------------------------------------------------------------------

def print_report(results: list[SelectorResult]) -> None:
    print("\n" + "=" * 60)
    print("RESUMEN — Qué actualizar en config.py")
    print("=" * 60)

    all_found = True
    for r in results:
        status = "OK " if r.working_selector else "---"
        print(f"\n  [{status}] SELECTORS[{r.key!r}]")
        if r.working_selector:
            print(f"         Valor sugerido: {r.working_selector!r}")
            if r.sample_aria_labels:
                print(f"         Ejemplo aria-label: {r.sample_aria_labels[0]!r}")
        else:
            all_found = False
            print(f"         SIN MATCH — candidatos probados:")
            for c in r.all_candidates_tried:
                print(f"           - {c!r}")
            print(f"         Acción: abrir DevTools, inspeccionar el elemento")
            print(f"         manualmente y agregar el selector correcto a config.py.")

    print("\n" + "-" * 60)
    if all_found:
        print("Todos los selectores encontrados. Copialos a config.py SELECTORS.")
    else:
        keys_missing = [r.key for r in results if not r.working_selector]
        print(f"Selectores incompletos: {keys_missing}")
        print("Para los faltantes:")
        print("  1. Abri DevTools en el browser (F12).")
        print("  2. Usa el inspector de elementos para identificar el aria-label")
        print("     o selector CSS del elemento faltante.")
        print("  3. Actualiza SELECTORS en config.py con el valor correcto.")
        print("  4. Para delete_option y confirm_delete_button, puede ser necesario")
        print("     abrir el menú contextual o el diálogo antes de correr el spike.")
    print("-" * 60)
    print("\nArchivo a editar: onedrive_rpa/config.py  →  dict SELECTORS")
    print("=" * 60 + "\n")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    print("=" * 60)
    print("Spike: Verificación de selectores ARIA en OneDrive")
    print("=" * 60)
    print()
    print("INSTRUCCIONES:")
    print("  1. El browser se va a abrir en modo visible.")
    print("  2. Se abre el inspector de Playwright (page.pause).")
    print("  3. Hacé login con tu cuenta de Microsoft si es necesario.")
    print("  4. Navegá hasta una carpeta que tenga archivos Y subcarpetas.")
    print("  5. Una vez que veas los ítems en la lista, presioná RESUME")
    print("     (botón verde ▶ en el inspector de Playwright).")
    print("  6. El script inspecciona la página y muestra los resultados.")
    print()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        print(f"Navegando a OneDrive...")
        try:
            page.goto("https://onedrive.live.com", timeout=30_000)
        except Exception as exc:
            print(f"Error al navegar: {exc}")
            print("Continuando de todas formas (podés navegar manualmente en el browser).")

        print()
        print(">> PAUSANDO — Completá el login y la navegación en el browser.")
        print(">> Cuando estés en la carpeta correcta, presioná RESUME en el inspector.")
        print()

        try:
            page.pause()
        except KeyboardInterrupt:
            print("\nInterrumpido por el usuario. Saliendo.")
            browser.close()
            sys.exit(0)

        # El usuario reanudó — inspeccionamos la página actual
        results = run_spike(page)
        print_report(results)

        print("Podés cerrar el browser manualmente o esperar 5 segundos.")
        try:
            page.wait_for_timeout(5_000)
        except Exception:
            pass

        browser.close()

    print("Spike finalizado.")


if __name__ == "__main__":
    main()
