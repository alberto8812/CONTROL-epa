# Design: OneDrive RPA con Playwright

## Architecture Overview

Capas finas, separación estricta entre **autenticación**, **navegación/operación RPA** y **CLI**. El estado mutable (sesión, configuración) vive en archivos JSON en el root del paquete; el código nunca asume credenciales en variables de entorno ni secrets externos.

Patrón general: **screaming architecture lite** — los nombres de paquete (`auth`, `rpa`) revelan dominio, no tecnología. Playwright es un detalle de implementación encapsulado en `rpa/cleaner.py` y `auth/session.py`.

```
+------------------------+
|        main.py         |   CLI (click) — orquesta, no decide
+-----------+------------+
            |
            v
+------------------------+      +------------------------+
|    auth/session.py     |<---->|       config.py        |
|  (storage_state I/O)   |      |  (URLs, selectores,    |
+-----------+------------+      |   timeouts, paths)     |
            |                   +------------------------+
            v                              ^
+------------------------+                 |
|    rpa/cleaner.py      |-----------------+
| (navegar + borrar)     |
+------------------------+
            |
            v
        Playwright
       (Chromium)
```

Dependencias dirigidas hacia abajo. `cleaner` no conoce a `main`; `auth` no conoce a `cleaner`. `config` es hoja: no importa nada del proyecto.

## Module Design

### `config.py` — single source of truth para constantes

Tipo: módulo plano con constantes + un par de helpers `Path`.

```python
ONEDRIVE_URL = "https://onedrive.live.com/?id=root"  # ajustable
SESSION_PATH = Path(__file__).parent / "session.json"
FOLDERS_PATH = Path(__file__).parent / "folders.json"
LOG_DIR      = Path(__file__).parent / "logs"

# Timeouts (ms)
NAV_TIMEOUT      = 30_000
ACTION_TIMEOUT   = 10_000
LOGIN_TIMEOUT    = 300_000   # 5 min para login manual

# Retry
MAX_RETRIES        = 3
RETRY_BACKOFF_SEC  = 2  # 2, 4, 8

# Selectores (centralizados; preferir roles ARIA)
SELECTORS = {
    "file_row":         "[role='row'][data-automationid='row']",
    "folder_row":       "[role='row'][data-automationid='row'] [aria-label*='folder']",
    "item_checkbox":    "[role='checkbox']",
    "toolbar_delete":   "button[name='Delete']",
    "confirm_delete":   "button:has-text('Delete')",
    "breadcrumb":       "[data-automationid='breadcrumb']",
    "login_email":      "input[type='email']",
}

# Detección de sesión expirada
LOGIN_REDIRECT_HOSTS = ("login.microsoftonline.com", "login.live.com")
```

**Por qué módulo plano y no `pydantic.BaseSettings`**: no hay env vars; cero ceremonia. Si crece, migrar es trivial.

### `auth/session.py` — manejo de storage_state

API pública:

```python
def load_or_login(playwright, *, mode: Literal["manual", "auto"], force_relogin: bool=False) -> tuple[Browser, BrowserContext]:
    """
    - mode='manual' + no session.json (o --relogin): launch headed, abrir OneDrive,
      esperar a que user complete login (poll por URL != login.* o timeout LOGIN_TIMEOUT),
      llamar context.storage_state(path=SESSION_PATH).
    - mode='auto': launch headless, new_context(storage_state=SESSION_PATH).
      Si SESSION_PATH no existe -> raise SessionMissingError.
    - mode='manual' + session existe + no --relogin: launch headed, reusa sesión.
    """

def is_session_expired(page: Page) -> bool:
    """True si page.url contiene un host de LOGIN_REDIRECT_HOSTS."""
```

Errores:
- `SessionMissingError` — modo auto sin `session.json`. Exit code 2.
- `SessionExpiredError` — detectado durante navegación. Exit code 3.

**Decisión clave**: `storage_state` se persiste **una sola vez** al finalizar el login manual, no en cada corrida. Reescribir en cada corrida invalida el cache y aumenta el riesgo de corromper el archivo si el proceso muere.

### `rpa/cleaner.py` — el corazón del RPA

API pública:

```python
class FolderCleaner:
    def __init__(self, page: Page, *, dry_run: bool, logger):
        ...

    def clean(self, folder_path: str) -> CleanStats:
        """
        Recorre `folder_path` (ej. 'Documentos/Reportes/Viejos') DFS,
        borra todos los archivos. Si encuentra subcarpetas, baja a cada una.
        Devuelve CleanStats(files_deleted, folders_visited, errors).
        """
```

Estrategia interna (DFS recursiva):

```
navigate_to(folder_path)
items = list_items_in_current_view()
for item in items:
    if item.is_folder:
        enter_folder(item)
        clean_current_folder()      # recursión
        go_back_breadcrumb()
    else:
        delete_item(item)           # respeta dry_run
```

**Por qué DFS y no listar todo upfront**: la UI de OneDrive virtualiza listas largas; un "listar todo" requiere scroll completo y duplica complejidad. DFS in-place opera sobre lo visible y deja que el DOM se reorganice tras cada borrado.

**Por qué borrar uno-por-uno y no bulk-select**: bulk-select es más rápido pero más frágil — si una fila no clickea, todo el batch falla y hay que recovery. Uno-por-uno permite retry granular y log preciso por archivo.

#### Selectores y navegación

- **Preferir `page.get_by_role("...")` y `get_by_label`** sobre CSS frágil. Microsoft cambia `data-automationid` con frecuencia; los roles ARIA son más estables porque son requisito de accesibilidad.
- **Breadcrumb-driven navigation**: en lugar de URLs (que codifican IDs internos), navegar por click en breadcrumb + click en filas. Más lento pero soporta paths configurados como strings legibles (`"Documentos/Reportes"`).
- **Esperas explícitas**: `expect(locator).to_be_visible(timeout=ACTION_TIMEOUT)` antes de cada interacción. **Cero `page.wait_for_timeout()` arbitrario** (anti-patrón conocido).

#### Detección archivo vs carpeta

Cada fila en la vista de OneDrive tiene un `aria-label` que distingue: `"Folder, Reportes"` vs `"File, informe.pdf"`. Parseamos el prefijo. Backup: ícono `[data-icon-name='Folder']`.

### `main.py` — CLI

```python
@click.command()
@click.option("--mode", type=click.Choice(["manual","auto"]), default="manual")
@click.option("--config", type=click.Path(exists=True), default="folders.json")
@click.option("--dry-run", is_flag=True)
@click.option("--yes", is_flag=True, help="Skip confirmation prompt")
@click.option("--relogin", is_flag=True, help="Force fresh login (manual mode)")
def cli(mode, config, dry_run, yes, relogin):
    setup_logging()
    folders = load_folders(config)

    if not dry_run and not yes:
        confirm_or_abort(folders)   # input() interactivo

    with sync_playwright() as p:
        browser, context = load_or_login(p, mode=mode, force_relogin=relogin)
        page = context.new_page()
        cleaner = FolderCleaner(page, dry_run=dry_run, logger=logger)
        for folder in folders:
            try:
                stats = cleaner.clean(folder)
                logger.info(f"DONE {folder}: {stats}")
            except SessionExpiredError:
                logger.error("Session expired. Re-run with --mode manual --relogin")
                sys.exit(3)
        browser.close()
```

**Decisión**: usar `sync_playwright`, no async. El uso es secuencial (una carpeta a la vez), no hay ganancia con async y el debugging es más simple.

## Data Flow

### Boot flow (modo manual, primera vez)
```
user $ python main.py --mode manual --dry-run
   |
   v
load_folders(folders.json)         -> [{"path":"Documentos/Reportes/Viejos"}]
confirm("Will delete from N folders. Continue?")
   |
   v
sync_playwright -> chromium.launch(headless=False)
   |
   v
new_context() (sin storage_state)
   |
   v
page.goto(ONEDRIVE_URL)
   |
   v  user completa login en la ventana visible
expect(page).not_to_have_url(re_login_hosts, timeout=LOGIN_TIMEOUT)
   |
   v
context.storage_state(path=session.json)
   |
   v
FolderCleaner(page, dry_run=True).clean("Documentos/Reportes/Viejos")
   |
   v dry_run: solo log, no click final
logger.info("WOULD DELETE: Documentos/Reportes/Viejos/foo.pdf")
```

### Run flow (modo auto, real)
```
user $ python main.py --mode auto --yes
   |
   v
load_folders + skip confirm
   |
   v
chromium.launch(headless=True)
new_context(storage_state=session.json)
   |
   v
page.goto(ONEDRIVE_URL)
   |
   v
is_session_expired(page)? -> sí -> SessionExpiredError -> exit 3
                          -> no -> continúa
   |
   v
for folder in folders:
    cleaner.clean(folder)
        navigate_to(folder)
        for item in items:
            if is_folder: enter + recurse + back
            else: delete + log
```

## Integration Points

| From            | To              | Contract                                                     |
|-----------------|-----------------|--------------------------------------------------------------|
| `main.py`       | `auth.session`  | `load_or_login(p, mode, force_relogin) -> (browser, ctx)`    |
| `main.py`       | `rpa.cleaner`   | `FolderCleaner(page, dry_run, logger).clean(path) -> Stats`  |
| `rpa.cleaner`   | `config`        | lee `SELECTORS`, `ACTION_TIMEOUT`, `MAX_RETRIES`             |
| `auth.session`  | `config`        | lee `SESSION_PATH`, `LOGIN_TIMEOUT`, `LOGIN_REDIRECT_HOSTS`  |
| `main.py`       | `folders.json`  | `[{"path":"<relative path>"}, ...]` — schema validado al cargar |
| `auth.session`  | `session.json`  | Playwright storage_state format (opaco; no inspeccionar)     |

Esquema `folders.json`:
```json
[
  { "path": "Documentos/Reportes/Viejos" },
  { "path": "Imagenes/Temp" }
]
```
Validación: lista no vacía; cada item tiene `path` (string no vacío, sin `..`, sin path absoluto).

## Error Handling & Retry

### Taxonomía de errores

| Excepción                  | Causa                                  | Acción                          | Exit code |
|----------------------------|----------------------------------------|---------------------------------|-----------|
| `SessionMissingError`      | `--mode auto` sin `session.json`        | Mensaje + sugerencia            | 2         |
| `SessionExpiredError`      | Redirect a login durante navegación    | Log + abortar corrida           | 3         |
| `FolderNotFoundError`      | Path en `folders.json` no existe en UI | Log warning + skip + continuar  | (no exit) |
| `ItemDeleteFailed`         | Click delete falla tras N retries      | Log error + skip item + continuar | (no exit) |
| `PlaywrightTimeoutError`   | DOM no responde                        | Retry con backoff               | -         |
| `KeyboardInterrupt`        | `Ctrl+C`                                | Cerrar browser limpio + exit    | 130       |

### Retry strategy (operaciones idempotentes)

Operaciones reintentables: `list_items_in_view`, `navigate_to`, `enter_folder`. **Borrado NO se reintenta automáticamente** — un borrado fallido puede haber sucedido server-side y el reintento podría borrar archivo distinto que ocupó la posición.

```python
@retry(max=MAX_RETRIES, backoff=RETRY_BACKOFF_SEC, on=(PlaywrightTimeoutError,))
def list_items_in_view(page) -> list[Item]:
    ...
```

Implementación: decorador simple en `rpa/_retry.py`, **no agregar `tenacity`** — overkill para 3 reintentos.

### Defensa contra borrado masivo accidental

1. **`--dry-run` por omisión recomendado en README**; el README explica que la primera corrida real requiere `--yes` explícito.
2. **Confirmación interactiva** lista carpetas afectadas + estimación si está disponible: `"About to delete files from 3 folders: ... Type 'DELETE' to continue:"`.
3. **Log pre-borrado**: antes del primer delete de cada carpeta, log `BEGIN CLEAN <path> (estimated N items)`.

## Logging

`loguru` con dos sinks:
- **stdout**: nivel INFO, formato corto, color.
- **archivo**: `logs/onedrive_rpa_{time:YYYY-MM-DD}.log`, nivel DEBUG, rotación diaria, retención 30 días, formato completo con módulo + línea.

Líneas estructuradas por archivo:
```
2026-05-19T20:14:33Z | DELETED  | Documentos/Reportes/Viejos/q1.pdf
2026-05-19T20:14:34Z | WOULD_DELETE | Documentos/Reportes/Viejos/q2.pdf       (en dry-run)
2026-05-19T20:14:35Z | SKIP     | Documentos/Reportes/Viejos/locked.xlsx (reason=delete_failed)
```

Decisión: no JSON estructurado. Greppable text es suficiente para auditoría manual. Si se necesitase ingesta automática, agregar segundo sink `serialize=True` luego.

## Architectural Decisions (ADRs)

### ADR-1: Playwright sync API, no async
**Decision**: usar `sync_playwright()`.
**Rationale**: workflow es secuencial; async agrega complejidad sin beneficio. Debugging y stack traces son más limpios.
**Rejected**: `async_playwright` — útil si hubiese paralelización por carpeta, pero el bottleneck es la UI, no la concurrencia.

### ADR-2: Storage state como único mecanismo de auth
**Decision**: persistir cookies + localStorage via `context.storage_state(path=...)`.
**Rationale**: encapsula MFA, Conditional Access, tokens refresh — todo lo que el browser ya negoció. Cero lógica de auth en el RPA.
**Rejected**:
- Microsoft Graph API — bloqueado por permisos de tenant (ver proposal).
- Device code flow — sigue requiriendo App Registration.
- Manejo manual de cookies — frágil, no soporta refresh.

### ADR-3: Selectores en `config.py`, no inline
**Decision**: todos los selectores Playwright viven en `SELECTORS` dict en `config.py`.
**Rationale**: cuando Microsoft cambie la UI, el fix es un solo archivo y sin tocar lógica. Facilita revisión por code review.
**Rejected**: selectores inline — viola DRY; un cambio en UI requiere editar múltiples archivos.

### ADR-4: DFS in-place, no listado upfront
**Decision**: navegar y borrar in-place con recursión depth-first.
**Rationale**: la lista de OneDrive es virtualizada; listar todo requiere scroll completo de DOM que no escala y duplica complejidad sin valor.
**Rejected**: BFS + lista global — más estructurado pero requiere model de árbol completo en memoria y scroll robusto.

### ADR-5: Borrado item-por-item, no bulk select
**Decision**: seleccionar y borrar un archivo por vez.
**Rationale**: retry granular, log preciso, falla aislada por archivo.
**Rejected**: bulk select + delete masivo — más rápido pero un solo error rompe el batch entero; recovery complicado.

### ADR-6: Detección de sesión expirada por URL host
**Decision**: chequear `page.url` contra `LOGIN_REDIRECT_HOSTS` antes de operar.
**Rationale**: simple, determinístico, no depende de leer DOM ni interceptar respuestas.
**Rejected**:
- Interceptar response 401 — Playwright sync API no expone hooks limpios; complica.
- Buscar elemento "Sign in" en página — falsos positivos.

### ADR-7: Sin reintento automático en borrado
**Decision**: operación `delete_item` falla → log y skip. NO se reintenta automáticamente.
**Rationale**: si el delete partió server-side antes del timeout client-side, reintentar puede borrar otro archivo distinto que ocupó la posición visual. Borrado no es idempotente desde la UI.
**Rejected**: retry con backoff — semánticamente inseguro; preferir log + acción manual.

### ADR-8: `loguru` sin estructuración JSON inicial
**Decision**: log a texto plano greppable.
**Rationale**: auditoría inicial es humana; YAGNI sobre JSON structured logging.
**Rejected**: structlog + JSON — añadir si aparece necesidad de ingesta automática.

### ADR-9: `folders.json` como lista de objetos, no de strings
**Decision**: `[{"path": "..."}]` en vez de `["..."]`.
**Rationale**: futuro-proof — permite añadir flags por carpeta (`recursive: false`, `include_pattern`) sin romper backward compat ni hacer migración.
**Rejected**: lista plana de strings — más simple ahora pero requiere migración cuando aparezca el primer flag.

### ADR-10: Confirmación interactiva con palabra mágica
**Decision**: en corrida real, pedir al usuario que escriba literalmente `DELETE` (no solo `y/n`).
**Rationale**: `y` se pulsa por accidente; escribir 6 letras requiere intención consciente. Es la diferencia entre "ups" y "definitivamente quería esto".
**Rejected**: prompt `y/n` — demasiado fácil de aceptar por reflejo.

## Risks (architectural)

| Risk                                                            | Impact | Mitigation                                             |
|-----------------------------------------------------------------|--------|--------------------------------------------------------|
| Cambio de UI OneDrive rompe selectores                          | High   | ADR-3: centralizar en `config.py`; preferir roles ARIA |
| Recursión sobre carpeta gigante (>10k items) agota memoria/timeouts | Medium | Procesar por chunks visibles (DFS in-place ya lo hace); timeouts generosos |
| `session.json` filtrado a Git                                   | High   | `.gitignore` + README; sin secrets en repo desde día 1 |
| MFA force re-auth a mitad de corrida                            | Medium | `is_session_expired` chequea antes de cada folder; exit limpio |
| Race entre borrado y re-render DOM (item index cambia)          | Medium | DFS in-place + re-listar items tras cada delete dentro del loop |
| `--mode auto` sin `session.json` (primera corrida olvidada)     | Low    | `SessionMissingError` con mensaje accionable          |
| `folders.json` con `..` o paths absolutos (path traversal lógico) | Low    | Validación al cargar; rechazo explícito              |

## Open Questions / Assumptions

1. **Asunción**: el tenant del usuario no fuerza step-up auth (MFA cada N horas) dentro de la ventana de una corrida típica (~minutos). Si esto resulta falso, la corrida se aborta limpiamente y el user re-loguea.
2. **Asunción**: la UI de OneDrive en español/inglés tiene los mismos roles ARIA (los `aria-label` cambian texto pero el role `row`/`button` es estable). Verificar en spike inicial.
3. **Asunción**: borrar archivo manda a Papelera (no purge inmediato) — confirmar con el primer dry-run real.
4. **Pendiente**: definir si `folders.json` soporta wildcards (`Documentos/Reportes/202*`). Decisión: NO en v1 (out of scope per proposal).

## Mapping a Capabilities (proposal)

| Capability                       | Module                                              |
|----------------------------------|-----------------------------------------------------|
| `onedrive-session-management`    | `auth/session.py` + `config.SESSION_PATH`           |
| `onedrive-folder-cleaner`        | `rpa/cleaner.py` (`FolderCleaner.clean`)            |
| `rpa-cli`                        | `main.py` (click commands)                          |
| `audit-logging`                  | `loguru` setup en `main.py` + log calls en cleaner  |
