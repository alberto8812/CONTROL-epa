"""
config.py — Constantes globales del proyecto.

Todas las constantes de comportamiento viven aquí. Los SELECTORS usan
data-automationid de OneDrive for Business, que son más estables que
aria-label (el texto de aria-label varía por idioma del tenant).
"""

import os
from pathlib import Path
from dotenv import load_dotenv
from loguru import logger


def _resolve_data_dir() -> Path:
    """
    Development: data files live alongside config.py (onedrive_rpa/).
    Installed (pipx/pip): data files live in ~/.novahold/.
    Detection: if .env or session.json or folders.json exist next to config.py → dev mode.
    """
    dev_dir = Path(__file__).parent
    if any((dev_dir / f).exists() for f in (".env", "session.json", "folders.json")):
        return dev_dir
    data_dir = Path.home() / ".novahold"
    data_dir.mkdir(exist_ok=True)
    return data_dir


BASE_DIR: Path = _resolve_data_dir()
_BASE_DIR = BASE_DIR  # backward-compat alias

load_dotenv(BASE_DIR / ".env")

# ---------------------------------------------------------------------------
# URLs
# ---------------------------------------------------------------------------

ONEDRIVE_URL: str = "https://archacomco-my.sharepoint.com"
"""URL raíz del tenant de SharePoint/OneDrive for Business."""

ONEDRIVE_LOGIN_URL: str = "https://archacomco-my.sharepoint.com"
"""URL de entrada al tenant. SharePoint redirige al login de Microsoft automáticamente."""

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

SESSION_PATH: Path = BASE_DIR / "session.json"
"""Ruta del archivo de storage_state de Playwright. Nunca commitear."""

FOLDERS_PATH: Path = BASE_DIR / "folders.json"
"""Ruta del archivo con las carpetas a limpiar."""

LOG_DIR: Path = BASE_DIR / "logs"
"""Directorio donde se escriben los logs rotativos."""

# ---------------------------------------------------------------------------
# Timeouts (milisegundos)
# ---------------------------------------------------------------------------

NAV_TIMEOUT_MS: int = 30_000
"""Timeout de navegación entre páginas (page.goto, page.wait_for_url)."""

ACTION_TIMEOUT_MS: int = 10_000
"""Timeout de acciones sobre elementos (click, expect visible)."""

LOGIN_TIMEOUT_MS: int = 300_000
"""Timeout de espera para login manual (5 minutos)."""

UPLOAD_TIMEOUT_MS: int = 60_000
"""Timeout para la operación de carga de archivo (upload) al toolbar de OneDrive."""

# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

REPORT_PASSWORD_LENGTH: int = 24
"""Longitud de la contraseña generada para el reporte XLSX."""

REPORT_PASSWORD_ALPHABET: str = (
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "abcdefghijklmnopqrstuvwxyz"
    "0123456789"
    "!@#$%^&*()-_=+[]{}|;:,.<>?"
)
"""Alfabeto permitido para generar contraseñas de reporte.
Excluye explícitamente las comillas \" y ' para compatibilidad con hojas de cálculo."""

REPORT_FILENAME_PREFIX: str = "reporte"
"""Prefijo del nombre de archivo del reporte XLSX (sin guión bajo final)."""

REPORT_FILENAME_TIMESTAMP_FORMAT: str = "%Y%m%d_%H%M%S"
"""Formato strftime para el timestamp en el nombre del archivo de reporte."""

# ---------------------------------------------------------------------------
# Retry
# ---------------------------------------------------------------------------

MAX_RETRIES: int = 3
"""Número máximo de reintentos para operaciones idempotentes (navigate, list).
El borrado NO se reintenta (ADR-7)."""

RETRY_BACKOFF_SEC: float = 2.0
"""Backoff base en segundos. Cada intento espera backoff * 2^(intento-1)."""

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

LOGIN_REDIRECT_HOSTS: tuple[str, ...] = (
    "login.microsoftonline.com",
    "login.live.com",
    "onedrive.live.com/login",  # página de login de OneDrive personal
)
"""Hosts/paths que indican que NO estamos logueados. Si page.url contiene
alguno de estos, se levanta SessionExpiredError (exit 3)."""

# ---------------------------------------------------------------------------
# Credenciales (.env)
# ---------------------------------------------------------------------------

ONEDRIVE_USERNAME: str = os.getenv("ONEDRIVE_USERNAME", "")
"""Email/usuario de la cuenta Microsoft. Cargar desde .env."""

ONEDRIVE_PASSWORD: str = os.getenv("ONEDRIVE_PASSWORD", "")
"""Contraseña de la cuenta Microsoft. Cargar desde .env. NUNCA hardcodear."""

SHAREPOINT_PERSONAL_PATH: str = os.getenv("SHAREPOINT_PERSONAL_PATH", "")
"""Path personal del tenant SharePoint, e.g. /personal/carlos_velasco_novahold_com.
Requerido para OneDrive for Business. Se usa para construir la URL de navegación."""

# ---------------------------------------------------------------------------
# URL Shortener (fail-open — swap provider by editing .env only)
# ---------------------------------------------------------------------------

URL_SHORTENER_ENDPOINT: str = os.getenv("URL_SHORTENER_ENDPOINT", "")
"""API endpoint of the URL shortener.
GET-based (is.gd):      https://is.gd/create.php?format=simple
GET-based (TinyURL):    https://tinyurl.com/api-create.php
POST-based (Rebrandly): https://api.rebrandly.com/v1/links
Leave empty to skip shortening."""

URL_SHORTENER_API_KEY: str = os.getenv("URL_SHORTENER_API_KEY", "")
"""API key / bearer token. Leave empty for keyless services (is.gd, TinyURL)."""

URL_SHORTENER_KEY_HEADER: str = os.getenv("URL_SHORTENER_KEY_HEADER", "Authorization")
"""HTTP header for the API key. Rebrandly uses 'apikey'."""

URL_SHORTENER_METHOD: str = os.getenv("URL_SHORTENER_METHOD", "GET").upper()
"""HTTP method: GET (appends ?url=<encoded>) or POST (sends JSON body). Rebrandly requires POST."""

URL_SHORTENER_BODY_KEY: str = os.getenv("URL_SHORTENER_BODY_KEY", "destination")
"""JSON key for the long URL in POST body. Rebrandly uses 'destination'."""

URL_SHORTENER_RESPONSE_KEY: str = os.getenv("URL_SHORTENER_RESPONSE_KEY", "shortUrl")
"""JSON key to extract from POST response. Rebrandly returns 'shortUrl'.
Empty string → treat response as plain text (GET providers like is.gd, TinyURL)."""

URL_SHORTENER_DOMAIN: str = os.getenv("URL_SHORTENER_DOMAIN", "")
"""Rebrandly: short domain fullName, e.g. 'rebrand.ly' or a custom domain.
Leave empty to use Rebrandly's default workspace domain."""

# ---------------------------------------------------------------------------
# Encryption (fail-open — EU-1, EU-2, EU-3)
# ---------------------------------------------------------------------------


def _build_fernet(key: bytes):
    """
    Build a Fernet instance from *key* bytes.

    Fail-open contract (EU-1, EU-3): if the key is empty, missing, or
    syntactically invalid the function returns ``None`` and logs a single
    warning.  It NEVER raises — a missing encryption key must not gate runs.

    Args:
        key: Raw key bytes, typically the encoded value of
             ``FOLDERS_ENCRYPTION_KEY`` from ``.env``.

    Returns:
        A :class:`~cryptography.fernet.Fernet` instance when *key* is valid,
        or ``None`` when the key is absent or invalid.
    """
    if not key:
        return None
    try:
        from cryptography.fernet import Fernet
        return Fernet(key)
    except Exception as exc:  # binascii.Error / ValueError for bad keys (EU-3)
        logger.warning(
            "FERNET_KEY_INVALID | reason={r} | encrypted_url column will be empty",
            r=str(exc),
        )
        return None


_FOLDERS_ENCRYPTION_KEY_RAW: str = os.getenv("FOLDERS_ENCRYPTION_KEY", "")

FERNET = (
    _build_fernet(_FOLDERS_ENCRYPTION_KEY_RAW.encode())
    if _FOLDERS_ENCRYPTION_KEY_RAW
    else None
)
"""
Fernet instance for encrypting report URLs, or ``None`` when
``FOLDERS_ENCRYPTION_KEY`` is absent or invalid (EU-1, EU-2).

Built once at config import time so that all callers share the same
instance.  Inject a different instance via the ``fernet=`` parameter in
:func:`~onedrive_rpa.rpa.reporter.build_report_rows` for testability (EU-2).
"""

# Selectores del formulario de login de Microsoft (login.microsoftonline.com)
LOGIN_SELECTORS: dict[str, str] = {
    "email_input":    "input[name='loginfmt']",
    "next_button":    "input[type='submit']",
    "password_input": "input[name='passwd']",
    "signin_button":  "input[type='submit']",
    "stay_signed_in": "#idSIButton9",  # botón "Sí" en "¿Mantener sesión iniciada?"
}

# ---------------------------------------------------------------------------
# Selectors — OneDrive for Business (data-automationid)
# ---------------------------------------------------------------------------
#
# Se usan data-automationid en lugar de aria-label porque:
#   - aria-label varía según el idioma configurado del tenant
#   - data-automationid es un contrato de testing de Microsoft, más estable
#
# Nota: tanto folder_row como file_row usan el mismo selector base porque
# OneDrive for Business renderiza ambos tipos con el mismo data-automationid
# en DetailsRowFields. La distinción folder/archivo se hace por item_type.

SELECTORS: dict[str, str] = {
    # Filas de datos en SharePoint modern UI (excluye la fila de encabezado).
    # Las filas de datos tienen siempre un checkbox de selección con data-automationid^='row-selection'.
    "folder_row": "[role='row']:has([data-automationid^='row-selection'])",
    "file_row":   "[role='row']:has([data-automationid^='row-selection'])",

    # Nombre del ítem — span con data-id='heroField' dentro de la fila.
    "item_name": "[data-id='heroField']",

    # Icono del ítem — el src del img distingue carpetas de archivos.
    # Carpetas: src contiene "folder". Archivos: src contiene la extensión (xlsx, pdf, etc).
    "item_type_icon": "[data-automationid='field-DocIcon'] img",

    # Celda del header que contiene el select-all (el div, no el input interno).
    # El input tiene un <span> que intercepta clicks; hacer click en el div padre funciona.
    "select_all": "[data-automationid='row-selection-header']",

    # Botón/item "Eliminar" — cubre toolbar directo y dropdown de overflow.
    "toolbar_delete": (
        "button[title='Eliminar'], button[title='Delete'], "
        "[role='menuitem'][aria-label='Eliminar'], [role='menuitem'][aria-label='Delete'], "
        "[data-automationid='deleteCommand']"
    ),

    # Botón overflow "..." en la barra de comandos (cuando "Eliminar" queda oculto por el ancho).
    "toolbar_overflow": "[data-automationid='more'], button[aria-label='Más'], button[aria-label='More']",

    # Botón de confirmación en el modal "¿Desea eliminar?".
    # data-automationid es todo minúscula: 'confirmbutton' (no 'confirmButton').
    "confirm_delete_button": "button[data-automationid='confirmbutton']",

    # Botón "Cargar" / "Upload" / "Crear o cargar" en la barra de comandos.
    # En SharePoint en español el botón se llama "Crear o cargar".
    "toolbar_upload": (
        "[data-automationid='uploadCommand'], "
        "[data-automationid='newCommand'], "
        "button[title='Crear o cargar'], "
        "button[aria-label='Crear o cargar'], "
        "button[name='Cargar'], button[name='Upload'], "
        "button[aria-label='Cargar'], button[aria-label='Upload']"
    ),

    # Item de menú "Cargar archivos" / "Carga de archivos" / "Upload files" dentro del dropdown.
    # SharePoint en español puede usar "Carga de archivos" O "Cargar archivos" según la versión del tenant.
    "upload_files_menuitem": (
        "[data-automationid='uploadFilesCommand'], "
        "[data-automationid='uploadFileCommand'], "
        "[role='menuitem'][title='Carga de archivos'], "
        "[role='menuitem'][title='Cargar archivos'], "
        "[role='menuitem'][title='Upload files'], "
        "[role='menuitem']:has-text('Carga de archivos'), "
        "[role='menuitem']:has-text('Cargar archivos'), "
        "[role='menuitem']:has-text('Upload files'), "
        "[role='menuitem'][name='Archivos'], "
        "[role='menuitem'][name='Files'], "
        "button:has-text('Carga de archivos'), "
        "li:has-text('Carga de archivos')"
    ),

    # Input de tipo file que SharePoint inyecta al hacer clic en "Archivos".
    "upload_file_input": "input[type='file']",
}

# ---------------------------------------------------------------------------
# Sharing — Selectors and constants
# ---------------------------------------------------------------------------

SHARE_EXPIRY_DAYS: int = 9
"""Number of days from today until the sharing link expires."""

SHARE_SELECTORS: dict[str, str] = {
    # Toolbar share button — "Compartir" / "Share"
    "share_button": (
        "[data-automationid='shareCommand'], "
        "button[title='Compartir'], "
        "button[aria-label='Compartir'], "
        "button[title='Share'], "
        "button[aria-label='Share']"
    ),
    # "Cualquier persona" (Anyone) — DOM-confirmed: role=radio, data-key='2'
    "anyone_option": (
        "[role='radio'][data-key='2'], "
        ".od-AudienceChoiceGroup-main[data-key='2'], "
        "[role='radio'][aria-label*='Cualquier persona']"
    ),
    # Expiry date input — DOM-confirmed: aria-label='Establecer fecha de expiración'
    # IMPORTANT: readonly='' — .fill()/.clear() do NOT work.
    # Must use click + page.keyboard.type() to set the date.
    "expiry_input": (
        "input[aria-label='Establecer fecha de expiración'], "
        "input[placeholder*='DD/MM/YYYY'], "
        "#datePicker-input20"
    ),
    # Password input — DOM-confirmed: data-automationid='share_link_password'
    "password_input": (
        "[data-automationid='share_link_password'], "
        "input[aria-label='Campo de contraseña'], "
        "input[name='password'][type='password']"
    ),
    # Selector for the share dialog iframe itself (on the main page).
    "share_iframe": "iframe[name='shareFrame']",
    # Gear icon ⚙️ inside the shareFrame iframe — data-automationid confirmed via DOM probe.
    "settings_button": (
        "[data-automationid='Footer-button-settings'], "
        "#Footer-button-settings, "
        "button[aria-label='Configuración de vínculos'], "
        "button[aria-label='Link settings']"
    ),
    # Apply button — DOM-confirmed: class includes od-ModifyPermissions-apply
    "apply_button": (
        "button.od-ModifyPermissions-apply, "
        "[id*='od-ModifyPermissions-apply'], "
        "button:has-text('Aplicar')"
    ),
    # Checkbox cell inside a folder row (for selection before sharing).
    # Click the container div — same pattern as select_all in SELECTORS.
    # Do NOT include the inner input[type='checkbox'] as a fallback: both the
    # container and the input exist within the row, causing a strict mode violation.
    "row_checkbox": "[data-automationid^='row-selection']",
}
