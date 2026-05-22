# Tasks: onedrive-rpa-playwright

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 350–480 |
| 400-line budget risk | Medium |
| Chained PRs recommended | No |
| Suggested split | Single PR (greenfield, no pre-existing code) |
| Delivery strategy | ask-on-risk |
| Chain strategy | pending |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: pending
400-line budget risk: Medium

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|-------|
| 1 | Toda la implementación (greenfield) | PR 1 | Proyecto nuevo, sin delta contra código previo. ~400 líneas netas. |

> Nota: proyecto greenfield sin código base. El diff ES la creación. Si el conteo real supera 400 líneas, el orchestrator debe reclasificar a `High` y solicitar estrategia de chain antes de apply.

---

## Phase 1: Foundation — Setup & Config

- [x] 1.1 Crear estructura de directorios del proyecto: `onedrive_rpa/auth/`, `onedrive_rpa/rpa/`, `onedrive_rpa/logs/`, `openspec/` ya existe. Crear `__init__.py` en cada paquete Python.
- [x] 1.2 Crear `requirements.txt` con: `playwright`, `click`, `loguru`. Versiones pinned.
- [x] 1.3 Crear `onedrive_rpa/config.py`: constantes `ONEDRIVE_URL`, `SESSION_PATH`, `FOLDERS_PATH`, `LOG_DIR`, `NAV_TIMEOUT_MS`, `ACTION_TIMEOUT_MS`, `LOGIN_TIMEOUT_MS`, `MAX_RETRIES`, `RETRY_BACKOFF_SEC`, `LOGIN_REDIRECT_HOSTS`, `SELECTORS` dict (vacío/stub — se completa en Phase 2 spike).
- [x] 1.4 Crear `folders.json` con schema `[{"path": "<relative>"}]` — un entry de ejemplo comentado (README-style).
- [x] 1.5 Agregar `.gitignore`: excluir `session.json`, `logs/`, `__pycache__/`, `.venv/`.

**Paralelo con:** nada (es la base de todo).

---

## Phase 2: Spike — Selector Verification

- [ ] 2.1 Script de spike `onedrive_rpa/rpa/_spike_selectors.py`: lanza headed Playwright, navega a `ONEDRIVE_URL`, imprime `aria-label` de las primeras 10 filas de la lista. Verificar que `role=row` con `aria-label` que contenga `"Folder,"` o `"File,"` es estable en UI real.
- [ ] 2.2 Ejecutar spike manualmente (requiere sesión válida). Documentar en `config.py` comentarios: qué aria-label se usa para distinguir folder vs file, qué botón abre el context-menu, qué opción del menu ejecuta Delete.
- [ ] 2.3 Poblar `SELECTORS` en `config.py` con los valores reales verificados: `SELECTORS["file_row"]`, `SELECTORS["folder_row"]`, `SELECTORS["context_menu_trigger"]`, `SELECTORS["delete_option"]`, `SELECTORS["confirm_delete_button"]`.

**Depende de:** 1.1, 1.3. **Bloquea:** 3.1–3.3.

---

## Phase 3: Core Implementation

- [ ] 3.1 Crear `onedrive_rpa/rpa/_retry.py`: decorador `with_retry(max_retries, backoff)` — solo para operaciones idempotentes (list, navigate, enter_folder). Sin tenacity.
- [ ] 3.2 Crear `onedrive_rpa/auth/session.py`: implementar `load_or_login(playwright, *, mode, force_relogin) -> (browser, context)` — manual/auto/relogin flows. `is_session_expired(page) -> bool`. Excepciones: `SessionMissingError` (exit 2), `SessionExpiredError` (exit 3). Persiste storage_state UNA sola vez post-login. Spec: `onedrive-session-management` todos los escenarios.
- [ ] 3.3 Crear `onedrive_rpa/rpa/cleaner.py`: clase `FolderCleaner(page, *, dry_run, logger)` con método `clean(folder_path) -> CleanStats`. DFS recursivo in-place. Distingue folder/file vía `SELECTORS`. Borrado item-por-item (NO bulk). Re-lista items tras cada delete. `FolderNotFoundError` → warning + skip. Spec: `onedrive-folder-cleaner` todos los escenarios.
- [ ] 3.4 Crear `onedrive_rpa/main.py`: CLI click con `--mode {manual,auto}`, `--config`, `--dry-run`, `--yes`, `--relogin`. Validar `folders.json` al cargar (schema, paths sin `..`, paths no absolutos). Confirmación interactiva pide escribir literalmente `DELETE`. `--dry-run` omite confirmación. `sync_playwright` (no async). Captura `SessionExpiredError` → exit 3. Spec: `rpa-cli` + `audit-logging`.

**Depende de:** 2.3 (selectores), 1.3 (config).

---

## Phase 4: Logging & Audit

- [ ] 4.1 Configurar loguru en `main.py`: dos sinks — stdout (INFO, color) + `logs/onedrive_rpa_{date}.log` (DEBUG, rotación diaria, retención 30d). Formato texto greppable: `<ISO8601> | <LEVEL> | <message>`. Sin `serialize=True`. Spec: `audit-logging` — dual output + run summary.
- [ ] 4.2 Emitir log `BEGIN CLEAN | folder=<path>` al inicio de cada carpeta en `cleaner.py`.
- [ ] 4.3 Emitir `DELETED | <path>`, `WOULD_DELETE | <path>`, `SKIP | <path> reason=<reason>`, `ERROR | <path> retries=<n>` desde `cleaner.py`. Un log por acción de archivo. Spec: `audit-logging` — per-file log entry.
- [ ] 4.4 Emitir summary en `main.py` al exit (normal + abortado): `SUMMARY deleted=N skipped=N errors=N elapsed=Xs`. Spec: `audit-logging` — run summary on exit.

**Depende de:** 3.3, 3.4. **Paralelo entre sí:** 4.2–4.4 (todos sobre archivos ya creados en Phase 3).

---

## Phase 5: Verification & Cleanup

- [ ] 5.1 Smoke test manual con `--dry-run`: verificar que logs imprimen `WOULD_DELETE` sin modificar OneDrive. Cubre spec `onedrive-folder-cleaner` Dry-run scenario.
- [ ] 5.2 Smoke test manual `--mode manual`: verificar que `session.json` se escribe tras login. Cubre spec `onedrive-session-management` First-time login.
- [ ] 5.3 Smoke test `--mode auto` con `session.json` válida: verificar run headless + summary correcto.
- [ ] 5.4 Test negativo: ejecutar `--mode auto` sin `session.json` — verificar exit code 2 + mensaje. Cubre spec Missing session file.
- [ ] 5.5 Eliminar `onedrive_rpa/rpa/_spike_selectors.py` del árbol final (fue solo spike). Actualizar `.gitignore` si necesario.
- [ ] 5.6 Agregar bloque `## Uso rápido` al `README.md` (si existe) o crear uno mínimo: instalación, primer login, dry-run, run real. Mencionar `.gitignore session.json` explícitamente.

**Depende de:** Phase 4 completa. **5.5 y 5.6 paralelo** entre sí.
