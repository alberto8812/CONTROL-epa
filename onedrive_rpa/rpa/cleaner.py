"""
rpa/cleaner.py — Limpieza recursiva de carpetas OneDrive via Playwright.

Estrategia: DFS in-place (ADR-4).
    1. Listar items visibles en la carpeta actual (listado exhaustivo,
       ver rpa/_navigation.py::list_items — a prueba de virtualización).
    2. Para cada item:
       - Si es carpeta → entrar, recursión, volver. Si tras la recursión la
         subcarpeta quedó sin archivos ni subcarpetas propias, se borra la
         subcarpeta en sí (borrado bottom-up, ver ADR-11 abajo).
       - Si es archivo → borrar en bloque (select-all + toolbar) y
         VERIFICAR con un loop acotado de "listar → borrar → re-listar"
         (hasta MAX_EMPTY_VERIFY_PASSES intentos) en vez de una sola pasada.

ADR-11 (borrado de subcarpetas vacías): la carpeta raíz pasada a `clean()`
(la que está listada en folders.json) NUNCA se borra — solo su contenido.
Pero cualquier subcarpeta encontrada DENTRO de esa raíz, a cualquier
profundidad, si termina sin archivos ni subcarpetas propias tras procesarla,
se borra a su vez. `_process_items()` devuelve un bool "esta carpeta quedó
vacía" y es el LLAMADOR (el nivel padre) quien decide borrar la subcarpeta
— `clean()` nunca actúa sobre su propio bool de retorno, así la raíz jamás
se borra a sí misma.

Por qué el loop de verificación NO viola ADR-7 (borrado no idempotente):
    cada pasada del loop es un ciclo completo y fresco — listar de nuevo,
    seleccionar-todo de nuevo, borrar de nuevo — nunca reutiliza referencias
    de fila (Locator) de una pasada anterior. Lo que se reintenta es "la
    carpeta sigue teniendo archivos", nunca un delete puntual sobre una fila
    ya resuelta. Si tras todos los intentos algo sigue pendiente, la carpeta
    se marca como `incomplete` en vez de reportarse como éxito silencioso.

Borrado NO se reintenta a nivel de operación individual (ADR-7).
Navegación y listing SÍ (via with_retry).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from loguru import logger
from playwright.sync_api import Page, Locator, TimeoutError as PlaywrightTimeoutError

from onedrive_rpa.config import (
    SELECTORS,
    ACTION_TIMEOUT_MS,
    NAV_TIMEOUT_MS,
    MAX_EMPTY_VERIFY_PASSES,
    EMPTY_VERIFY_SETTLE_MS,
    EMPTY_VERIFY_POLL_INTERVAL_MS,
    EMPTY_VERIFY_MAX_SETTLE_MS,
    SELECTION_SETTLE_MS,
    COMMAND_PROBE_TIMEOUT_MS,
)
from onedrive_rpa.auth.session import check_session_expired, SessionExpiredError
from onedrive_rpa.rpa._retry import with_retry
from onedrive_rpa.rpa.ui import RPACallbacks
from onedrive_rpa.rpa._navigation import (
    ItemInfo,
    navigate_to_folder,
    list_items,
    names_match,
    FolderNotFoundError,
)

# Re-export FolderNotFoundError for backward compatibility with existing imports
# (e.g. main.py: from onedrive_rpa.rpa.cleaner import FolderNotFoundError)
FolderNotFoundError = FolderNotFoundError  # noqa: F811


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
    incomplete: list[str] = field(default_factory=list)
    """Carpetas que, tras agotar MAX_EMPTY_VERIFY_PASSES intentos de
    borrado+verificación, todavía tienen archivos pendientes."""
    deleted_folders: list[str] = field(default_factory=list)
    """Subcarpetas (nunca la raíz pasada a clean()) borradas por haber
    quedado vacías tras procesar su contenido (ver ADR-11)."""

    @property
    def deleted_count(self) -> int:
        return len(self.deleted)

    @property
    def error_count(self) -> int:
        return len(self.errors)

    @property
    def incomplete_count(self) -> int:
        return len(self.incomplete)

    def merge(self, other: "CleanStats") -> None:
        """Fusiona las stats de otra limpieza en esta instancia."""
        self.deleted.extend(other.deleted)
        self.would_delete.extend(other.would_delete)
        self.skipped.extend(other.skipped)
        self.errors.extend(other.errors)
        self.incomplete.extend(other.incomplete)
        self.deleted_folders.extend(other.deleted_folders)


# ---------------------------------------------------------------------------
# Helper puro: diff entre listado pendiente y listado tras el borrado bulk
# ---------------------------------------------------------------------------


def _diff_listing(
    pending: set[str], remaining: set[str]
) -> tuple[list[str], set[str], list[str]]:
    """
    Compara el conjunto de nombres pendientes de borrar contra lo que sigue
    apareciendo tras una pasada de borrado bulk. Función pura, sin Playwright.

    Args:
        pending: Nombres de archivo que se intentó borrar en esta pasada.
        remaining: Nombres de archivo observados en el re-listado posterior.

    Returns:
        Tupla ``(confirmed_deleted, still_pending, newly_appeared)``:
            - confirmed_deleted: nombres en *pending* que ya NO están en
              *remaining* (borrado confirmado), ordenados alfabéticamente.
            - still_pending: nombres presentes en ambos conjuntos — quedan
              pendientes para el próximo intento del loop.
            - newly_appeared: nombres en *remaining* que NO estaban en
              *pending* (subida concurrente durante la corrida). No cuentan
              como fallo del borrado ni se agregan a `pending` para reintento
              — no formaban parte del pedido de borrado original.
    """
    confirmed_deleted = sorted(pending - remaining)
    still_pending = pending & remaining
    newly_appeared = sorted(remaining - pending)
    return confirmed_deleted, still_pending, newly_appeared


def _wait_for_delete_settle(page: Page) -> None:
    """
    Wait for a bulk delete to finish propagating server-side before re-listing.

    A single fixed EMPTY_VERIFY_SETTLE_MS sleep was long enough for small
    deletes but a live probe showed 100+ file bulk deletes can still be
    settling well past 1.5s — polling the row count until it stops changing
    (or a bounded budget runs out) adapts to both cases without penalizing
    small folders with a longer fixed sleep.
    """
    page.wait_for_timeout(EMPTY_VERIFY_SETTLE_MS)

    start = time.monotonic()
    last_count = page.locator(SELECTORS["folder_row"]).count()
    while (time.monotonic() - start) * 1000 < EMPTY_VERIFY_MAX_SETTLE_MS:
        page.wait_for_timeout(EMPTY_VERIFY_POLL_INTERVAL_MS)
        current_count = page.locator(SELECTORS["folder_row"]).count()
        if current_count == last_count:
            return
        last_count = current_count


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
        La carpeta raíz (folder_path) en sí NUNCA se elimina — pero cualquier
        subcarpeta encontrada dentro de ella, a cualquier profundidad, se borra
        si queda vacía tras procesar su contenido (ver ADR-11 en el docstring
        del módulo).

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
            navigate_to_folder(self._page, folder_path)
        except FolderNotFoundError:
            logger.warning("SKIP | folder={folder} reason=not_found", folder=folder_path)
            raise

        # El bool de retorno ("¿folder_path quedó vacío?") se descarta a
        # propósito: la raíz configurada en folders.json nunca se borra,
        # solo sus descendientes (ADR-11).
        self._process_items(folder_path, stats)

        self._cb.on_folder_done(folder_path, len(stats.deleted), len(stats.errors))
        return stats

    def _process_items(self, current_path: str, stats: CleanStats) -> bool:
        """
        Lista items visibles y los procesa en orden DFS.

        Re-lista tras cada delete para compensar virtualización del DOM.

        Returns:
            True si, al terminar, current_path quedó sin archivos y sin
            subcarpetas propias — señal para que el LLAMADOR decida borrar
            esta carpeta (nunca lo decide esta misma llamada, ver ADR-11).
        """
        check_session_expired(self._page)

        items = list_items(self._page)

        # Separate folders and files — process folders first (DFS)
        folders = [i for i in items if i.is_folder]
        files = [i for i in items if not i.is_folder]

        # Primero: entrar en cada subcarpeta, y borrarla si quedó vacía
        subfolders_all_removed = True

        for item in folders:
            child_path = f"{current_path}/{item.name}"
            try:
                _enter_folder(self._page, item.name)
                child_is_empty = self._process_items(child_path, stats)
                _go_back(self._page, current_path)

                if child_is_empty:
                    self._remove_empty_folder(item.name, child_path, stats)
                else:
                    subfolders_all_removed = False
            except FolderNotFoundError:
                logger.warning(
                    "SKIP | path={path} reason=folder_disappeared",
                    path=child_path,
                )
                stats.skipped.append(child_path)
                subfolders_all_removed = False
            except SessionExpiredError:
                raise
            except Exception as exc:
                logger.error(
                    "ERROR | path={path} reason={reason}",
                    path=child_path,
                    reason=str(exc),
                )
                stats.errors.append(child_path)
                subfolders_all_removed = False

        # Luego: borrar archivos del nivel actual con select-all + toolbar delete
        check_session_expired(self._page)
        current_items = list_items(self._page)
        current_files = [i for i in current_items if not i.is_folder]

        if not current_files:
            return subfolders_all_removed

        if self._dry_run:
            for item in current_files:
                item_path = f"{current_path}/{item.name}"
                logger.info("WOULD_DELETE | {path}", path=item_path)
                stats.would_delete.append(item_path)
                self._cb.on_file_would_delete(item_path)
            return subfolders_all_removed

        # Loop acotado de verificar-y-rehacer (reemplaza la pasada única).
        # Cada iteración es un ciclo fresco: listar → seleccionar-todo →
        # borrar → re-listar. Nunca reutiliza referencias de fila de una
        # iteración anterior (ADR-7 sigue respetado — ver docstring del módulo).
        pending: set[str] = {item.name for item in current_files}
        hard_failure = False

        for attempt in range(1, MAX_EMPTY_VERIFY_PASSES + 1):
            try:
                check_session_expired(self._page)
                _bulk_delete_files(self._page, len(pending))
                _wait_for_delete_settle(self._page)

                remaining_items = list_items(self._page)
                remaining = {i.name for i in remaining_items if not i.is_folder}

                confirmed_deleted, still_pending, newly_appeared = _diff_listing(
                    pending, remaining
                )

                for name in confirmed_deleted:
                    item_path = f"{current_path}/{name}"
                    logger.info("DELETED | {path}", path=item_path)
                    stats.deleted.append(item_path)
                    self._cb.on_file_deleted(item_path)

                if newly_appeared:
                    logger.warning(
                        "CONCURRENT_UPLOAD | path={path} | items={items}",
                        path=current_path,
                        items=newly_appeared,
                    )

                if not confirmed_deleted:
                    # Una pasada sin excepción que no borró nada: queda en el
                    # audit log en vez de pasar por éxito silencioso.
                    logger.warning(
                        "NO_PROGRESS | path={path} | attempt={attempt} | pending={n}",
                        path=current_path,
                        attempt=attempt,
                        n=len(pending),
                    )

                pending = still_pending
                if not pending:
                    break
            except SessionExpiredError:
                raise
            except Exception as exc:
                logger.error(
                    "ERROR | path={path} attempt={attempt} reason={reason}",
                    path=current_path,
                    attempt=attempt,
                    reason=str(exc),
                )
                hard_failure = True
                for name in pending:
                    item_path = f"{current_path}/{name}"
                    stats.errors.append(item_path)
                    self._cb.on_error(item_path, str(exc))
                break

        if pending:
            stats.incomplete.append(current_path)
            logger.error(
                "INCOMPLETE | path={p} | remaining={n} | passes={a}",
                p=current_path,
                n=len(pending),
                a=MAX_EMPTY_VERIFY_PASSES,
            )
            self._cb.on_folder_incomplete(current_path, len(pending))
            if not hard_failure:
                stats.errors.append(current_path)
            return False

        return subfolders_all_removed

    def _remove_empty_folder(
        self, folder_name: str, folder_path: str, stats: CleanStats
    ) -> None:
        """
        Borra una subcarpeta que quedó vacía tras procesar su contenido
        (ADR-11). Nunca se llama sobre la carpeta raíz pasada a clean().

        En dry-run solo loggea/reporta lo que se haría, sin tocar el DOM.
        """
        if self._dry_run:
            logger.info("WOULD_DELETE_FOLDER | {path}", path=folder_path)
            stats.would_delete.append(folder_path)
            self._cb.on_file_would_delete(folder_path)
            return

        try:
            check_session_expired(self._page)
            _delete_single_row(self._page, folder_name)
            logger.info("DELETED_FOLDER | {path}", path=folder_path)
            stats.deleted_folders.append(folder_path)
            self._cb.on_folder_deleted(folder_path)
        except SessionExpiredError:
            raise
        except Exception as exc:
            logger.error(
                "ERROR | path={path} reason={reason}",
                path=folder_path,
                reason=str(exc),
            )
            stats.errors.append(folder_path)
            self._cb.on_error(folder_path, str(exc))


# ---------------------------------------------------------------------------
# Private navigation helpers (folder traversal within a clean run)
# ---------------------------------------------------------------------------


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
    page.wait_for_load_state("load", timeout=NAV_TIMEOUT_MS)
    try:
        page.wait_for_selector(SELECTORS["folder_row"], timeout=ACTION_TIMEOUT_MS, state="attached")
    except PlaywrightTimeoutError:
        pass
    check_session_expired(page)


@with_retry()
def _go_back(page: Page, parent_path: str) -> None:
    """
    Vuelve a la carpeta padre usando el botón Back del browser.
    """
    page.go_back(timeout=NAV_TIMEOUT_MS, wait_until="load")
    try:
        page.wait_for_selector(SELECTORS["folder_row"], timeout=ACTION_TIMEOUT_MS, state="attached")
    except PlaywrightTimeoutError:
        pass
    check_session_expired(page)


# ---------------------------------------------------------------------------
# Borrado bulk: select-all + toolbar Eliminar (enfoque principal)
# ---------------------------------------------------------------------------


class SelectionError(Exception):
    """La selección de filas no se pudo establecer antes de borrar.

    Se lanza en vez de dejar que el flujo termine en un timeout genérico del
    toolbar: sin selección confirmada nunca se hace click en "Eliminar".
    """


def _resolve_delete_command(page: Page, timeout_ms: int) -> Locator | None:
    """
    Devuelve el comando "Eliminar" listo para clickear, o None si la barra
    no lo ofrece.

    Prueba primero el botón directo y, si no está, abre el overflow "...".
    Que ninguno de los dos aparezca NO es un fallo de red: es la respuesta
    "no hay nada seleccionado" — la barra de comandos sin selección no
    renderiza ni "Eliminar" ni el overflow. Por eso se devuelve None (dato
    para el llamador) en vez de propagar un TimeoutError.
    """
    toolbar_delete = page.locator(SELECTORS["toolbar_delete"]).first
    try:
        toolbar_delete.wait_for(state="visible", timeout=timeout_ms)
        return toolbar_delete
    except PlaywrightTimeoutError:
        pass

    overflow = page.locator(SELECTORS["toolbar_overflow"]).first
    try:
        overflow.wait_for(state="visible", timeout=timeout_ms)
        overflow.click(timeout=ACTION_TIMEOUT_MS)
        toolbar_delete.wait_for(state="visible", timeout=timeout_ms)
        return toolbar_delete
    except PlaywrightTimeoutError:
        return None


def _confirm_delete_and_settle(page: Page) -> None:
    """
    Confirma el modal de borrado (si el tenant lo muestra) y espera a que las
    filas se desmonten.

    Ambas esperas son opcionales por razones legítimas — algunos tenants
    borran sin modal, y un borrado de una sola fila entre muchas nunca
    desmonta la lista entera — pero la ausencia de desmontaje se LOGEA:
    combinada con un re-listado que no cambió, es la firma de una pasada que
    no borró nada. Silenciarla fue lo que hizo que la pasada 1 sobre Bz13ff
    (2026-08-31) se reportara como exitosa habiendo borrado cero archivos.
    """
    confirm_btn = page.locator(SELECTORS["confirm_delete_button"]).first
    try:
        confirm_btn.wait_for(state="visible", timeout=5_000)
        confirm_btn.click(timeout=ACTION_TIMEOUT_MS)
    except PlaywrightTimeoutError:
        logger.debug("DELETE | sin modal de confirmación (tenant borra directo)")

    try:
        page.wait_for_selector(
            SELECTORS["folder_row"], timeout=10_000, state="detached"
        )
    except PlaywrightTimeoutError:
        logger.warning("DELETE_NO_DETACH | las filas no se desmontaron tras el borrado")


def _click_toolbar_delete_and_confirm(page: Page) -> None:
    """
    Click en "Eliminar" de la barra de comandos y confirma el modal si aparece.

    Asume que la selección YA está hecha y verificada por el llamador.

    Raises:
        SelectionError: Si la barra de comandos no ofrece "Eliminar" — señal
            de que no hay nada seleccionado.
    """
    command = _resolve_delete_command(page, ACTION_TIMEOUT_MS)
    if command is None:
        raise SelectionError(
            "La barra de comandos no ofrece 'Eliminar' — no hay selección activa"
        )

    command.click(timeout=ACTION_TIMEOUT_MS)
    _confirm_delete_and_settle(page)


def _bulk_delete_files(page: Page, file_count: int) -> None:
    """
    Selecciona todos los ítems y los elimina via la barra de comandos.

    El select-all del header es un TOGGLE, no un "seleccionar todo"
    idempotente. Si una pasada anterior del loop de verificar-y-rehacer dejó
    la lista seleccionada, el click de esta pasada la DESELECCIONA: la barra
    de comandos vuelve a su estado sin selección — sin "Eliminar" y sin
    overflow "..." — y el código viejo se quedaba esperando ese overflow
    hasta el timeout (run 2026-08-31, Camion/ADMIN/Bz13ff: 39 archivos
    marcados como error por UN solo fallo de toolbar).

    Por eso el resultado del click se VERIFICA contra la propia barra de
    comandos: que "Eliminar" esté alcanzable es exactamente la condición que
    el siguiente paso necesita, así que es mejor evidencia que cualquier
    atributo del DOM. Si no lo está, se vuelve a clickear (restaurando la
    selección) y se comprueba de nuevo. Dos intentos fallidos son un
    SelectionError explícito, nunca un click a ciegas sobre "Eliminar".

    Raises:
        SelectionError: Si tras dos intentos la selección no se estableció.
    """
    select_all_cell = page.locator(SELECTORS["select_all"])
    select_all_cell.wait_for(state="visible", timeout=ACTION_TIMEOUT_MS)

    for attempt in (1, 2):
        select_all_cell.click(timeout=ACTION_TIMEOUT_MS)
        page.wait_for_timeout(SELECTION_SETTLE_MS)

        command = _resolve_delete_command(page, COMMAND_PROBE_TIMEOUT_MS)
        if command is not None:
            command.click(timeout=ACTION_TIMEOUT_MS)
            _confirm_delete_and_settle(page)
            return

        logger.warning(
            "SELECT_ALL_NO_COMMAND | attempt={a} | files={n} | "
            "el click dejó la barra sin 'Eliminar' (toggle apagado)",
            a=attempt,
            n=file_count,
        )

    raise SelectionError(
        f"select-all no dejó una selección activa tras 2 intentos "
        f"({file_count} archivos pendientes)"
    )


# ---------------------------------------------------------------------------
# Función de borrado de una única fila (NO se decora con with_retry — ADR-7)
# ---------------------------------------------------------------------------


def _delete_single_row(page: Page, item_name: str) -> None:
    """
    Selecciona UNA sola fila por su checkbox y la borra via la barra de
    comandos — mismo mecanismo verificado en producción que _bulk_delete_files()
    (y que sharer.py usa para seleccionar una fila puntual antes de compartir),
    pero marcando solo el checkbox de esa fila en vez del select-all del header.

    Usado para borrar subcarpetas que quedaron vacías tras procesar su
    contenido (ADR-11).

    NO se reintenta (ADR-7): el borrado no es idempotente; reintentar
    podría borrar un ítem diferente que ocupó la misma posición visual.

    Raises:
        ValueError: Si la fila con ese nombre no está en el DOM.
        Exception: Cualquier error de Playwright se propaga al llamador,
            que lo loggea como ERROR y continúa (no exit).
    """
    row = _find_row_by_name(page, item_name)
    if row is None:
        raise ValueError(f"Item '{item_name}' no encontrado en el DOM para borrar")

    checkbox = row.locator(SELECTORS["row_checkbox"]).first
    checkbox.click(timeout=ACTION_TIMEOUT_MS)

    _click_toolbar_delete_and_confirm(page)


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
            if names_match(current_name, name):
                return row
        except Exception:
            continue
    return None
