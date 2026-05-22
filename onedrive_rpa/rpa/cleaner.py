"""
rpa/cleaner.py — Limpieza recursiva de carpetas OneDrive via Playwright.

Estrategia: DFS in-place (ADR-4).
    1. Listar items visibles en la carpeta actual.
    2. Para cada item:
       - Si es carpeta → entrar, recursión, volver.
       - Si es archivo → borrar item-por-item (ADR-5), loggear.
    3. Re-listar tras cada delete para compensar re-render del DOM (lista virtualizada).

Borrado NO se reintenta (ADR-7). Navegación y listing SÍ (via with_retry).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import NamedTuple

from loguru import logger
from playwright.sync_api import Page, Locator, TimeoutError as PlaywrightTimeoutError

import time as _time

from onedrive_rpa.config import (
    ONEDRIVE_URL,
    SHAREPOINT_PERSONAL_PATH,
    SELECTORS,
    NAV_TIMEOUT_MS,
    ACTION_TIMEOUT_MS,
)
from onedrive_rpa.auth.session import check_session_expired, SessionExpiredError
from onedrive_rpa.rpa._retry import with_retry
from onedrive_rpa.rpa.ui import RPACallbacks


# ---------------------------------------------------------------------------
# Tipos de datos
# ---------------------------------------------------------------------------


@dataclass
class CleanStats:
    """Resultado de una limpieza de carpeta."""
    deleted: list[str] = field(default_factory=list)
    would_delete: list[str] = field(default_factory=list)  # dry-run
    skipped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def deleted_count(self) -> int:
        return len(self.deleted)

    @property
    def error_count(self) -> int:
        return len(self.errors)

    def merge(self, other: "CleanStats") -> None:
        """Fusiona las stats de otra limpieza en esta instancia."""
        self.deleted.extend(other.deleted)
        self.would_delete.extend(other.would_delete)
        self.skipped.extend(other.skipped)
        self.errors.extend(other.errors)


class _ItemInfo(NamedTuple):
    name: str
    is_folder: bool


# ---------------------------------------------------------------------------
# Excepciones
# ---------------------------------------------------------------------------


class FolderNotFoundError(Exception):
    """La carpeta configurada no existe en OneDrive."""


# ---------------------------------------------------------------------------
# FolderCleaner
# ---------------------------------------------------------------------------


class FolderCleaner:
    """
    Navega y limpia carpetas OneDrive de forma recursiva (DFS in-place).

    Args:
        page: Página Playwright autenticada.
        dry_run: Si True, loggea WOULD_DELETE sin borrar nada.
        callbacks: Callbacks opcionales para actualizar la UI en tiempo real.
    """

    def __init__(
        self,
        page: Page,
        *,
        dry_run: bool = False,
        callbacks: RPACallbacks | None = None,
    ) -> None:
        self._page = page
        self._dry_run = dry_run
        self._cb = callbacks or RPACallbacks()

    def clean(self, folder_path: str) -> CleanStats:
        """
        Limpia todos los archivos dentro de folder_path de forma recursiva.

        Los subdirectorios se procesan antes de los archivos del nivel actual (DFS).
        Los directorios en sí NO se eliminan.

        Args:
            folder_path: Ruta relativa dentro de OneDrive, p. ej. "Documentos/Reportes".

        Returns:
            CleanStats con el resultado de la operación.

        Raises:
            FolderNotFoundError: Si la carpeta no se encuentra; el llamador debe
                loggear WARNING y continuar con la siguiente carpeta.
            SessionExpiredError: Si se detecta redirect a login mid-run.
        """
        stats = CleanStats()

        logger.info("BEGIN CLEAN | folder={folder}", folder=folder_path)
        self._cb.on_folder_start(folder_path)

        try:
            _navigate_to_folder(self._page, folder_path)
        except FolderNotFoundError:
            logger.warning("SKIP | folder={folder} reason=not_found", folder=folder_path)
            raise

        self._process_items(folder_path, stats)

        self._cb.on_folder_done(folder_path, len(stats.deleted), len(stats.errors))
        return stats

    def _process_items(self, current_path: str, stats: CleanStats) -> None:
        """
        Lista items visibles y los procesa en orden DFS.

        Re-lista tras cada delete para compensar virtualización del DOM.
        """
        check_session_expired(self._page)

        items = _list_items(self._page)

        # Separar carpetas y archivos para procesar carpetas primero (DFS)
        folders = [i for i in items if i.is_folder]
        files = [i for i in items if not i.is_folder]

        # Primero: entrar en cada subcarpeta
        for item in folders:
            child_path = f"{current_path}/{item.name}"
            try:
                _enter_folder(self._page, item.name)
                self._process_items(child_path, stats)
                _go_back(self._page, current_path)
            except FolderNotFoundError:
                logger.warning(
                    "SKIP | path={path} reason=folder_disappeared",
                    path=child_path,
                )
                stats.skipped.append(child_path)
            except SessionExpiredError:
                raise
            except Exception as exc:
                logger.error(
                    "ERROR | path={path} reason={reason}",
                    path=child_path,
                    reason=str(exc),
                )
                stats.errors.append(child_path)

        # Luego: borrar archivos del nivel actual con select-all + toolbar delete
        check_session_expired(self._page)
        current_items = _list_items(self._page)
        current_files = [i for i in current_items if not i.is_folder]

        if not current_files:
            return

        if self._dry_run:
            for item in current_files:
                item_path = f"{current_path}/{item.name}"
                logger.info("WOULD_DELETE | {path}", path=item_path)
                stats.would_delete.append(item_path)
                self._cb.on_file_would_delete(item_path)
        else:
            try:
                _bulk_delete_files(self._page, len(current_files))
                for item in current_files:
                    item_path = f"{current_path}/{item.name}"
                    logger.info("DELETED | {path}", path=item_path)
                    stats.deleted.append(item_path)
                    self._cb.on_file_deleted(item_path)
            except SessionExpiredError:
                raise
            except Exception as exc:
                for item in current_files:
                    item_path = f"{current_path}/{item.name}"
                    logger.error(
                        "ERROR | path={path} reason={reason}",
                        path=item_path,
                        reason=str(exc),
                    )
                    stats.errors.append(item_path)
                    self._cb.on_error(item_path, str(exc))


# ---------------------------------------------------------------------------
# Funciones de navegación (idempotentes → elegibles para with_retry)
# ---------------------------------------------------------------------------


@with_retry()
def _navigate_to_folder(page: Page, folder_path: str) -> None:
    """
    Navega a la carpeta indicada desde la raíz de OneDrive.

    Construye la URL de OneDrive con el path relativo. Si la página redirige
    a login o no encuentra la carpeta (title "Page not found"), levanta
    FolderNotFoundError.

    Raises:
        FolderNotFoundError: Si la carpeta no existe.
        SessionExpiredError: Si se detecta redirect a login.
    """
    # Construir URL: OneDrive for Business usa path en la URL
    # Ejemplo: https://tenant-my.sharepoint.com/personal/user/.../Documentos/Reportes
    # Como ONEDRIVE_URL puede ser la raíz, navegamos por click en breadcrumb/URL
    # Para simplicidad: navegar a la raíz y luego hacer click en la ruta
    base_url = ONEDRIVE_URL.rstrip("/")
    if SHAREPOINT_PERSONAL_PATH:
        # OneDrive for Business: navegar directo a la biblioteca de documentos
        personal = SHAREPOINT_PERSONAL_PATH.rstrip("/")
        target_url = f"{base_url}{personal}/Documents/{folder_path.lstrip('/')}"
    else:
        # OneDrive personal
        target_url = f"{base_url}/?path=/{folder_path.lstrip('/')}"

    page.goto(target_url, timeout=NAV_TIMEOUT_MS)
    page.wait_for_load_state("networkidle", timeout=NAV_TIMEOUT_MS)

    check_session_expired(page)

    # Detectar "Page not found" o equivalente
    if "Page not found" in page.title() or "not found" in page.url.lower():
        raise FolderNotFoundError(f"Carpeta no encontrada: {folder_path}")


@with_retry()
def _list_items(page: Page) -> list[_ItemInfo]:
    """
    Devuelve la lista de items visibles en la carpeta actual.

    Distingue carpetas de archivos usando el selector item_type:
    si el texto contiene "folder" (case-insensitive) → es carpeta.
    """
    # Esperar a que haya al menos un row o que la lista esté vacía
    try:
        page.wait_for_selector(
            SELECTORS["folder_row"],
            timeout=ACTION_TIMEOUT_MS,
            state="attached",
        )
    except PlaywrightTimeoutError:
        # Lista vacía es válido
        return []

    rows: list[Locator] = page.locator(SELECTORS["folder_row"]).all()
    items: list[_ItemInfo] = []

    for row in rows:
        try:
            name_el = row.locator(SELECTORS["item_name"])
            name = name_el.inner_text(timeout=ACTION_TIMEOUT_MS).strip()
            if not name:
                continue

            # Detectar carpeta por el src del ícono (más estable que aria-label o itemtype)
            icon_el = row.locator(SELECTORS["item_type_icon"])
            icon_src = (icon_el.get_attribute("src", timeout=ACTION_TIMEOUT_MS) or "").lower()
            is_folder = "folder" in icon_src

            items.append(_ItemInfo(name=name, is_folder=is_folder))
        except Exception:
            # Row stale o sin nombre → ignorar
            continue

    return items


@with_retry()
def _enter_folder(page: Page, folder_name: str) -> None:
    """
    Hace doble click en la fila de la carpeta indicada para entrar.

    Raises:
        FolderNotFoundError: Si no se encuentra la fila con ese nombre.
    """
    row = _find_row_by_name(page, folder_name)
    if row is None:
        raise FolderNotFoundError(f"Carpeta '{folder_name}' no encontrada en el DOM")

    # Click en el nombre (heroField) navega dentro de la carpeta en SharePoint
    name_el = row.locator(SELECTORS["item_name"])
    name_el.click(timeout=ACTION_TIMEOUT_MS)
    page.wait_for_load_state("networkidle", timeout=NAV_TIMEOUT_MS)
    check_session_expired(page)


@with_retry()
def _go_back(page: Page, parent_path: str) -> None:
    """
    Vuelve a la carpeta padre usando el botón Back del browser.
    """
    page.go_back(timeout=NAV_TIMEOUT_MS)
    page.wait_for_load_state("networkidle", timeout=NAV_TIMEOUT_MS)
    check_session_expired(page)


# ---------------------------------------------------------------------------
# Borrado bulk: select-all + toolbar Eliminar (enfoque principal)
# ---------------------------------------------------------------------------


def _bulk_delete_files(page: Page, file_count: int) -> None:
    """
    Selecciona todos los ítems y los elimina via la barra de comandos.

    Flujo:
        1. Click en la celda header del select-all (el div, no el input).
        2. Click en "Eliminar" de la barra de comandos.
           Si no está visible, primero abre el overflow "..." y luego hace click en Eliminar.
        3. Si aparece modal de confirmación → click en confirmar.
    """
    # 1. Seleccionar todo — click en el div del header (el <span> interno intercepta clics)
    select_all_cell = page.locator(SELECTORS["select_all"])
    select_all_cell.wait_for(state="visible", timeout=ACTION_TIMEOUT_MS)
    select_all_cell.click(timeout=ACTION_TIMEOUT_MS)
    _time.sleep(0.8)  # Esperar que el toolbar actualice tras la selección

    # 2. Toolbar Eliminar — directo o via overflow "..."
    toolbar_delete = page.locator(SELECTORS["toolbar_delete"]).first
    try:
        toolbar_delete.wait_for(state="visible", timeout=3_000)
        toolbar_delete.click(timeout=ACTION_TIMEOUT_MS)
    except PlaywrightTimeoutError:
        # Eliminar no está visible → abrir overflow "..." primero
        overflow = page.locator(SELECTORS["toolbar_overflow"]).first
        overflow.wait_for(state="visible", timeout=ACTION_TIMEOUT_MS)
        overflow.click(timeout=ACTION_TIMEOUT_MS)
        _time.sleep(0.3)
        toolbar_delete.wait_for(state="visible", timeout=ACTION_TIMEOUT_MS)
        toolbar_delete.click(timeout=ACTION_TIMEOUT_MS)

    # 3. Modal de confirmación
    confirm_btn = page.locator(SELECTORS["confirm_delete_button"]).first
    try:
        confirm_btn.wait_for(state="visible", timeout=5_000)
        confirm_btn.click(timeout=ACTION_TIMEOUT_MS)
    except PlaywrightTimeoutError:
        pass  # Algunos tenants borran directo sin modal

    page.wait_for_load_state("networkidle", timeout=NAV_TIMEOUT_MS)


# ---------------------------------------------------------------------------
# Función de borrado ítem por ítem (NO se decora con with_retry — ADR-7)
# ---------------------------------------------------------------------------


def _delete_item(page: Page, item_name: str) -> None:
    """
    Borra el item con el nombre indicado via menú contextual.

    Flujo:
        1. Click en el botón "..." (context_menu_trigger) de la fila.
        2. Click en la opción Delete (delete_option).
        3. Si aparece diálogo de confirmación → click en confirm_delete_button.

    NO se reintenta (ADR-7): el borrado no es idempotente; reintentar
    podría borrar un archivo diferente que ocupó la misma posición visual.

    Raises:
        Exception: Cualquier error de Playwright se propaga al llamador,
            que lo loggea como ERROR y continúa (no exit).
    """
    row = _find_row_by_name(page, item_name)
    if row is None:
        raise ValueError(f"Item '{item_name}' no encontrado en el DOM para borrar")

    # Hover sobre el nombre para que aparezca el botón "Más acciones"
    name_el = row.locator(SELECTORS["item_name"])
    name_el.hover(timeout=ACTION_TIMEOUT_MS)

    trigger = row.locator(SELECTORS["context_menu_trigger"])
    trigger.wait_for(state="visible", timeout=ACTION_TIMEOUT_MS)
    trigger.click(timeout=ACTION_TIMEOUT_MS)

    # Esperar que aparezca la opción delete en el menú
    delete_option = page.locator(SELECTORS["delete_option"])
    delete_option.wait_for(state="visible", timeout=ACTION_TIMEOUT_MS)
    delete_option.click(timeout=ACTION_TIMEOUT_MS)

    # Confirmar si aparece diálogo
    confirm_btn = page.locator(SELECTORS["confirm_delete_button"])
    try:
        confirm_btn.wait_for(state="visible", timeout=3_000)
        confirm_btn.click(timeout=ACTION_TIMEOUT_MS)
    except PlaywrightTimeoutError:
        # No hubo diálogo de confirmación → operación ya ejecutada directamente
        pass

    # Esperar que el DOM actualice (la fila desaparece)
    try:
        page.wait_for_load_state("networkidle", timeout=ACTION_TIMEOUT_MS)
    except PlaywrightTimeoutError:
        pass


# ---------------------------------------------------------------------------
# Helper interno
# ---------------------------------------------------------------------------


def _find_row_by_name(page: Page, name: str) -> Locator | None:
    """
    Busca y devuelve el Locator de la primera fila cuyo item_name coincide.
    Retorna None si no se encuentra.
    """
    rows = page.locator(SELECTORS["folder_row"]).all()
    for row in rows:
        try:
            name_el = row.locator(SELECTORS["item_name"])
            current_name = name_el.inner_text(timeout=ACTION_TIMEOUT_MS).strip()
            if current_name == name:
                return row
        except Exception:
            continue
    return None
