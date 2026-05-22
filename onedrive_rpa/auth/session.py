"""
auth/session.py — Gestión de sesión Playwright via storage_state.

Única responsabilidad: crear, cargar y validar la sesión guardada en session.json.
Playwright storage_state encapsula cookies + localStorage → cubre MFA/Conditional Access.

Flujos:
    manual + sin session.json (o --relogin): browser headed, espera login,
        persiste storage_state UNA vez tras confirmar URL fuera de login.
    auto + session.json: browser headless con storage_state. Si falta → SessionMissingError.
    manual + session.json existe (sin --relogin): headed con sesión cargada.

Excepciones:
    SessionMissingError  (exit 2): modo auto sin session.json.
    SessionExpiredError  (exit 3): redirect a login detectado mid-run.
"""

import re
import sys
from pathlib import Path

from loguru import logger
from playwright.sync_api import Playwright, Browser, BrowserContext, Page

from onedrive_rpa.config import (
    ONEDRIVE_URL,
    ONEDRIVE_LOGIN_URL,
    SESSION_PATH,
    LOGIN_TIMEOUT_MS,
    NAV_TIMEOUT_MS,
    ACTION_TIMEOUT_MS,
    LOGIN_REDIRECT_HOSTS,
    ONEDRIVE_USERNAME,
    ONEDRIVE_PASSWORD,
    LOGIN_SELECTORS,
)


# ---------------------------------------------------------------------------
# Excepciones públicas
# ---------------------------------------------------------------------------


class SessionMissingError(Exception):
    """session.json no existe en modo auto."""
    exit_code: int = 2


class SessionExpiredError(Exception):
    """La sesión expiró mid-run (redirect a login)."""
    exit_code: int = 3


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------


def load_or_login(
    playwright: Playwright,
    *,
    mode: str,
    force_relogin: bool = False,
    log_fn=None,
) -> tuple[Browser, BrowserContext, Page]:
    """
    Punto de entrada principal de autenticación.

    Args:
        playwright: Instancia sync de Playwright.
        mode: "manual" | "auto".
        force_relogin: Si True, elimina session.json existente y fuerza login manual.
        log_fn: Callable(category, message) opcional para emitir eventos al TUI.

    Returns:
        Tupla (browser, context, page) lista para navegar.

    Raises:
        SessionMissingError: modo "auto" sin session.json.
        SessionExpiredError: redirect a login detectado al navegar a ONEDRIVE_URL.
    """
    _log = log_fn or (lambda cat, msg: None)

    if force_relogin and SESSION_PATH.exists():
        logger.info("RELOGIN | eliminando session.json existente")
        _log("AUTH", "Forzando re-login — eliminando sesión guardada")
        SESSION_PATH.unlink()

    if mode == "auto":
        _log("SESS", "Modo AUTO — cargando session.json")
        return _load_session(playwright, log_fn=_log)
    else:
        # manual: si hay sesión y no se forzó relogin → cargar; sino → login fresco
        if SESSION_PATH.exists():
            logger.info("SESSION | cargando sesión existente (headed)")
            _log("SESS", "Sesión existente encontrada — reutilizando")
            return _load_session(playwright, headless=False, log_fn=_log)
        else:
            _log("AUTH", "Sin sesión previa — iniciando login manual")
            return _do_manual_login(playwright, relogin=force_relogin, log_fn=_log)


def save_session(context: BrowserContext) -> None:
    """
    Persiste el storage_state del contexto actual en SESSION_PATH.

    Llama solo UNA vez tras confirmar login exitoso.
    """
    SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)
    context.storage_state(path=str(SESSION_PATH))
    logger.info("SESSION_SAVED | path={path}", path=SESSION_PATH)


_MARKETING_URL_FRAGMENT = "microsoft.com/es"

def is_session_expired(page: Page) -> bool:
    """
    Devuelve True si la URL indica que NO estamos logueados:
    - redirigió a un host de login (login.microsoftonline.com, login.live.com)
    - está en la página de marketing de OneDrive (microsoft.com/es-co/...)
    """
    current_url = page.url
    return (
        any(host in current_url for host in LOGIN_REDIRECT_HOSTS)
        or _MARKETING_URL_FRAGMENT in current_url
    )


def check_session_expired(page: Page) -> None:
    """
    Levanta SessionExpiredError si la sesión expiró.

    Convenience wrapper para usar en cleaner.py.
    """
    if is_session_expired(page):
        raise SessionExpiredError(
            "Session expired. Run with --relogin to re-authenticate."
        )


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------


def _load_session(
    playwright: Playwright,
    headless: bool = True,
    log_fn=None,
) -> tuple[Browser, BrowserContext, Page]:
    """
    Carga session.json en un browser nuevo y navega a ONEDRIVE_URL.

    Raises:
        SessionMissingError: si session.json no existe.
        SessionExpiredError: si la URL post-navegación es un host de login.
    """
    _log = log_fn or (lambda cat, msg: None)

    if not SESSION_PATH.exists():
        raise SessionMissingError(
            "Run with --mode manual first to create a session."
        )

    logger.info("SESSION | cargando storage_state | headless={headless}", headless=headless)
    _log("SESS", f"Cargando storage_state  ·  headless={headless}")

    browser = playwright.chromium.launch(headless=headless)
    context = browser.new_context(storage_state=str(SESSION_PATH))
    page = context.new_page()

    _log("NET", f"Navegando a {ONEDRIVE_URL}")
    page.goto(ONEDRIVE_URL, timeout=NAV_TIMEOUT_MS, wait_until="domcontentloaded")

    if is_session_expired(page):
        browser.close()
        _log("ERROR", "Sesión expirada — ejecutá con --relogin")
        raise SessionExpiredError(
            "Session expired. Run with --relogin to re-authenticate."
        )

    logger.info("SESSION | cargada correctamente | url={url}", url=page.url)
    _log("SESS", f"Sesión activa  ·  {page.url}")
    return browser, context, page


def _do_manual_login(
    playwright: Playwright,
    relogin: bool = False,
    log_fn=None,
) -> tuple[Browser, BrowserContext, Page]:
    """
    Abre browser headed y completa el login.

    Si ONEDRIVE_USERNAME y ONEDRIVE_PASSWORD están en .env → auto-fill del formulario.
    Si no hay credenciales → el usuario completa el login manualmente.
    Si hay MFA → espera que el usuario lo resuelva manualmente (hasta LOGIN_TIMEOUT_MS).
    """
    _log = log_fn or (lambda cat, msg: None)
    has_credentials = bool(ONEDRIVE_USERNAME and ONEDRIVE_PASSWORD)

    logger.info(
        "LOGIN | modo={modo} | url={url}",
        modo="auto-fill" if has_credentials else "manual",
        url=ONEDRIVE_LOGIN_URL,
    )
    _log("AUTH", f"{'Auto-fill' if has_credentials else 'Login manual'}  ·  abriendo browser")

    browser = playwright.chromium.launch(headless=False)
    context = browser.new_context()
    page = context.new_page()

    # Navegar directo al login para evitar la redirección a la página de marketing
    _log("NET", f"Navegando a {ONEDRIVE_LOGIN_URL}")
    page.goto(ONEDRIVE_LOGIN_URL, timeout=NAV_TIMEOUT_MS, wait_until="domcontentloaded")
    try:
        page.wait_for_load_state("networkidle", timeout=NAV_TIMEOUT_MS)
    except Exception:
        pass

    # Esperar que el formulario de login esté visible antes de intentar llenar
    if has_credentials:
        _log("AUTH", f"Ingresando credenciales  ·  {ONEDRIVE_USERNAME}")
        _autofill_credentials(page, log_fn=_log)

    # Esperar hasta que la URL indique que el login fue exitoso (check positivo)
    try:
        page.wait_for_function(
            _build_logged_in_check(),
            timeout=LOGIN_TIMEOUT_MS,
        )
    except Exception as exc:
        browser.close()
        raise SessionMissingError(
            "Login no completado dentro del tiempo límite o browser cerrado antes de terminar."
        ) from exc

    save_session(context)
    logger.info("LOGIN_OK | url={url}", url=page.url)
    _log("SESS", "Sesión guardada en session.json")
    _log("NET",  f"Conectado  ·  {page.url}")
    return browser, context, page


def _click_signin_if_marketing(page: Page) -> None:
    """
    Si estamos en la página de marketing de OneDrive, hace click en
    'Iniciar sesión' para ir al formulario de login real.
    """
    if _MARKETING_URL_FRAGMENT not in page.url:
        return
    try:
        btn = page.get_by_role(
            "link",
            name=re.compile(r"Iniciar sesión|Sign in", re.IGNORECASE),
        ).first
        btn.wait_for(state="visible", timeout=5_000)
        btn.click()
        page.wait_for_load_state("networkidle", timeout=NAV_TIMEOUT_MS)
        logger.info("LOGIN | click en 'Iniciar sesión' desde página de marketing")
    except Exception as exc:
        logger.warning("LOGIN | no se encontró botón Iniciar sesión: {err}", err=str(exc))


_EMAIL_SELECTORS = "input[name='loginfmt'], input[type='email'], #i0116"
_PASSWORD_SELECTORS = "input[name='passwd'], input[type='password'], #i0118"
_SUBMIT_SELECTORS = "#idSIButton9, input[type='submit'], button[type='submit']"


_FRAME_PROBE_MS = 3_000
_IFRAME_PROBE_MS = 2_000


def _find_locator(page: Page, css: str, timeout_ms: int = 5_000):
    """
    Busca un elemento en la página principal y en todos los iframes.

    Estrategia de 3 pasos para cubrir tanto forms en main frame (que renderizan
    lento via JS) como forms dentro de iframes (ej: login.live.com embebido):
      1. Sondeo rápido en main frame — si ya está, lo encontramos al toque.
      2. Sondeo rápido en cada iframe presente — por si el form está en un iframe.
      3. Espera larga en main frame con el tiempo restante — cubre JS lento.
    """
    import time
    deadline_s = time.monotonic() + timeout_ms / 1000
    probe_ms = min(_FRAME_PROBE_MS, timeout_ms)

    # 1. Sondeo rápido en el frame principal
    loc = page.locator(css).first
    try:
        loc.wait_for(state="visible", timeout=probe_ms)
        return loc
    except Exception:
        pass

    # 2. Sondeo rápido en cada iframe presente
    for frame in page.frames:
        if frame == page.main_frame:
            continue
        try:
            loc = frame.locator(css).first
            loc.wait_for(state="visible", timeout=_IFRAME_PROBE_MS)
            return loc
        except Exception:
            continue

    # 3. Espera larga en main frame — cubre renderizado JS tardío
    remaining_ms = max(1_000, int((deadline_s - time.monotonic()) * 1000))
    loc = page.locator(css).first
    try:
        loc.wait_for(state="visible", timeout=remaining_ms)
        return loc
    except Exception:
        pass

    return None


def _autofill_credentials(page: Page, log_fn=None) -> None:
    """
    Completa el formulario de login de Microsoft con las credenciales del .env.
    Busca el formulario tanto en la página principal como en iframes (onedrive.live.com
    carga el formulario de login.live.com dentro de un iframe).

    Si hay MFA, espera que el usuario lo resuelva manualmente.
    """
    _log = log_fn or (lambda cat, msg: None)
    try:
        try:
            page.wait_for_load_state("networkidle", timeout=NAV_TIMEOUT_MS)
        except Exception:
            pass

        # Paso 1: email
        email_loc = _find_locator(page, _EMAIL_SELECTORS, timeout_ms=NAV_TIMEOUT_MS)
        if email_loc is None:
            raise Exception("campo email no encontrado en página ni iframes")
        email_loc.fill(ONEDRIVE_USERNAME)
        logger.info("LOGIN | email ingresado: {u}", u=ONEDRIVE_USERNAME)
        _log("AUTH", f"Email ingresado  ·  {ONEDRIVE_USERNAME}")

        submit_loc = _find_locator(page, _SUBMIT_SELECTORS, timeout_ms=ACTION_TIMEOUT_MS)
        if submit_loc:
            submit_loc.click()

        # Paso 2: password
        try:
            page.wait_for_load_state("networkidle", timeout=NAV_TIMEOUT_MS)
        except Exception:
            pass
        pwd_loc = _find_locator(page, _PASSWORD_SELECTORS, timeout_ms=NAV_TIMEOUT_MS)
        if pwd_loc is None:
            raise Exception("campo password no encontrado")
        pwd_loc.fill(ONEDRIVE_PASSWORD)
        logger.info("LOGIN | contraseña ingresada")
        _log("AUTH", "Contraseña ingresada  ·  enviando formulario")

        submit_loc2 = _find_locator(page, _SUBMIT_SELECTORS, timeout_ms=ACTION_TIMEOUT_MS)
        if submit_loc2:
            submit_loc2.click()

        # Paso 3: "¿Mantener sesión iniciada?" — click Sí si aparece
        try:
            page.wait_for_selector("#idSIButton9", timeout=5_000)
            page.click("#idSIButton9")
            logger.info("LOGIN | 'Mantener sesión' aceptado")
            _log("AUTH", "Sesión persistida  ·  'Mantener sesión' aceptado")
        except Exception:
            pass

    except Exception as exc:
        logger.warning(
            "LOGIN | auto-fill falló ({err}) — completá el login manualmente en el browser abierto",
            err=str(exc),
        )
        _log("WARN", f"Auto-fill falló: {exc}  ·  completá el login manualmente")


def _build_logged_in_check() -> str:
    """
    JS que retorna true cuando la URL indica login exitoso.

    Check positivo: esperamos estar en onedrive.live.com (sin /login),
    sharepoint.com, o office.com. Más robusto que verificar ausencia de
    hosts de login, que puede dar falsos positivos en redirects intermedios.
    """
    return """
        () => {
            const url = window.location.href;
            const loggedIn = (
                (url.includes("onedrive.live.com") && !url.includes("/login")) ||
                url.includes("sharepoint.com") ||
                (url.includes("office.com") && !url.includes("login"))
            );
            return loggedIn;
        }
    """
