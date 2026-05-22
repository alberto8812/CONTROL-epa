"""
config.py — Constantes globales del proyecto.

Todas las constantes de comportamiento viven aquí. Los SELECTORS usan
data-automationid de OneDrive for Business, que son más estables que
aria-label (el texto de aria-label varía por idioma del tenant).
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

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

_BASE_DIR: Path = Path(__file__).parent

SESSION_PATH: Path = _BASE_DIR / "session.json"
"""Ruta del archivo de storage_state de Playwright. Nunca commitear."""

FOLDERS_PATH: Path = _BASE_DIR / "folders.json"
"""Ruta del archivo con las carpetas a limpiar."""

LOG_DIR: Path = _BASE_DIR / "logs"
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
}
