# Proposal: OneDrive RPA con Playwright

## Intent

Operadores necesitan vaciar periódicamente carpetas específicas de OneDrive for Business (Microsoft 365) sin tener que clickear archivo por archivo. La interfaz web es lenta y propensa a error humano; los permisos corporativos suelen bloquear o restringir Microsoft Graph API. Resolvemos esto con un RPA en Python que automatiza el navegador, autentica una sola vez de forma interactiva y luego limpia carpetas configuradas de manera repetible y auditable.

## Scope

### In Scope
- CLI en Python con `click` (`main.py`) con subcomandos/flags: `--mode manual|auto`, `--dry-run`, `--config folders.json`.
- Persistencia de sesión Playwright (cookies + storage state) en `session.json`.
- Lectura de carpetas objetivo desde `folders.json` (rutas relativas a la raíz de OneDrive).
- Borrado recursivo (entrando a subcarpetas) de TODOS los archivos en cada carpeta configurada.
- Modo `manual`: browser visible, el usuario hace login y MFA, se guarda `session.json` al cerrar.
- Modo `auto`: headless, reusa `session.json`; aborta con error claro si la sesión expiró.
- Flag `--dry-run` que recorre y loggea todo sin ejecutar borrados.
- Logging con `loguru` a stdout y archivo rotativo, una línea por archivo eliminado con timestamp ISO 8601 y ruta completa.

### Out of Scope
- Migración a Microsoft Graph API (queda como evolución futura).
- Restauración o vaciado de Papelera de reciclaje de OneDrive.
- Carpetas compartidas de terceros (SharePoint sites, "Shared with me").
- Filtros avanzados (por extensión, fecha, tamaño) — sólo borrado total.
- Multi-tenant / multi-cuenta en una misma corrida.
- Empaquetado como `.exe` o instalador (se ejecuta con `python main.py`).

## Capabilities

### New Capabilities
- `onedrive-session-management`: capturar, guardar y reutilizar la sesión autenticada de Playwright contra OneDrive web.
- `onedrive-folder-cleaner`: navegación y borrado recursivo de archivos dentro de carpetas configuradas.
- `rpa-cli`: punto de entrada CLI con modos manual/auto y dry-run.
- `audit-logging`: registro estructurado de cada acción (eliminada / saltada / error) con timestamp.

### Modified Capabilities
- None (proyecto greenfield).

## Approach

RPA basado en **browser automation con Playwright (Chromium)** en lugar de Microsoft Graph API. Tres capas:

1. **`auth/session.py`** — usa `browser.new_context(storage_state="session.json")` cuando existe; en modo manual, `context.storage_state(path="session.json")` al final del login.
2. **`rpa/cleaner.py`** — recibe un `Page` autenticado y una ruta. Navega por breadcrumbs/click, detecta archivos vs subcarpetas en el listado, recursión depth-first (subcarpetas primero, luego archivos de la carpeta actual), borra vía menú contextual o toolbar.
3. **`main.py`** — CLI con `click`, orquesta auth → loop sobre `folders.json` → cleaner. Respeta `--dry-run` cortando antes del click final de "Eliminar".

`config.py` centraliza URLs base, timeouts, selectores y rutas de `session.json`/`folders.json`.

### Por qué Playwright sobre Microsoft Graph API

| Criterio | Playwright | Graph API |
|----------|-----------|-----------|
| Permisos corporativos | Reusa la sesión web del usuario | Requiere App Registration + consent admin |
| Setup | `pip install` + login manual | Tenant config, secrets, OAuth flow |
| MFA / Conditional Access | Lo maneja el usuario en el login | Bloqueante sin device code o cert auth |
| Fragilidad | Alta (selectores UI cambian) | Baja (contrato API estable) |
| Velocidad | Lenta (render UI) | Rápida (HTTP directo) |

En este contexto **el bloqueador real son los permisos de tenant**, no la velocidad. Playwright se elige por viabilidad operativa.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `onedrive_rpa/main.py` | New | Entry point CLI con `click` |
| `onedrive_rpa/config.py` | New | Constantes: URLs, timeouts, paths |
| `onedrive_rpa/auth/session.py` | New | Guardar/cargar `storage_state` Playwright |
| `onedrive_rpa/rpa/cleaner.py` | New | Navegación + borrado recursivo |
| `onedrive_rpa/folders.json` | New | Config del usuario (rutas a limpiar) |
| `onedrive_rpa/session.json` | New (gitignore) | Estado de sesión auto-generado |
| `onedrive_rpa/requirements.txt` | New | `playwright`, `click`, `loguru` |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Borrado masivo accidental por ruta mal configurada | High | `--dry-run` obligatorio en primera corrida; confirmación interactiva en modo manual; log previo de "voy a borrar N archivos" |
| Sesión expirada en modo auto | High | Detectar redirect a login y abortar con exit code != 0 y mensaje claro |
| Selectores UI cambian (OneDrive web update) | Medium | Centralizar selectores en `config.py`; usar roles ARIA y `getByRole` antes de CSS frágil |
| MFA / Conditional Access bloquea reuso de sesión | Medium | Documentar que el modo manual se vuelve a correr cuando expira la sesión |
| Race conditions con UI lenta (archivos no cargados al iterar) | Medium | Esperas explícitas con `expect().toBeVisible()`, no `sleep` |
| `session.json` filtrado a Git con credenciales | High | `.gitignore` desde el día 1; documentar en README |
| Throttling de Microsoft por borrado masivo | Low | Pausas configurables entre acciones; retry con backoff |

## Rollback Plan

- El RPA no modifica código del repo: si una corrida sale mal, **`Ctrl+C`** corta el proceso.
- Los archivos eliminados van a la **Papelera de reciclaje de OneDrive** (retención 30-93 días según política del tenant) — restauración manual desde la web.
- Borrar `session.json` reinicia el ciclo de auth.
- Si se introduce un bug en el código, `git revert` del commit ofensor.

## Dependencies

- Python 3.10+
- `playwright` (con `playwright install chromium` post-pip).
- `click`, `loguru`.
- Cuenta Microsoft 365 con OneDrive for Business activa.
- Permisos de borrado sobre las carpetas configuradas.

## Success Criteria

- [ ] Primera corrida en modo manual: login interactivo termina con `session.json` válido en disco.
- [ ] Segunda corrida en modo auto headless reutiliza la sesión sin pedir credenciales.
- [ ] `--dry-run` lista todos los archivos que se borrarían sin eliminar ninguno.
- [ ] Corrida real elimina el 100% de los archivos en las carpetas de `folders.json` (incluyendo subcarpetas recursivamente).
- [ ] Cada archivo eliminado aparece en el log con timestamp ISO 8601 y ruta completa.
- [ ] Si la sesión expira en modo auto, el proceso aborta con exit code != 0 y mensaje accionable.
