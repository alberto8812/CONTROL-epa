# CONTROL-epa

Hub de automatización interna con interfaz de terminal (TUI). Centraliza herramientas RPA bajo un menú interactivo unificado llamado **NovaHold**.

---

## Estructura del repositorio

```
CONTROL-epa/
├── nova                        ← launcher ejecutable (./nova)
├── requirements.txt            ← dependencias del hub
├── novahome/                   ← hub NovaHold
│   ├── main.py                 ← entrada principal, menú home
│   ├── modules/
│   │   ├── azulito.py          ← OneDrive RPA launcher
│   │   ├── novahld.py          ← placeholder (próximamente)
│   │   └── aditai.py           ← placeholder (próximamente)
│   └── ui/
│       ├── banner.py           ← banner ASCII + grid de info
│       └── checks.py           ← panel de verificación de dependencias
└── onedrive_rpa/               ← RPA de eliminación de archivos OneDrive
    ├── main.py                 ← CLI del RPA (Click)
    ├── config.py               ← constantes, selectores, vars de entorno
    ├── auth/session.py         ← autenticación Playwright (storage_state)
    ├── rpa/cleaner.py          ← lógica DFS de eliminación
    ├── rpa/ui.py               ← TUI Rich (Observer pattern)
    ├── rpa/logger.py           ← Loguru + audit log rotativo
    ├── rpa/_retry.py           ← decorador @with_retry con backoff
    ├── folders.json            ← carpetas a limpiar
    └── .env                    ← credenciales (no commitear)
```

---

## Instalación

```bash
# 1. Clonar el repositorio
git clone https://github.com/alberto8812/CONTROL-epa.git
cd CONTROL-epa

# 2. Instalar dependencias
pip install -r requirements.txt

# 3. Instalar browser de Playwright
playwright install chromium
```

---

## Ejecutar

```bash
./nova
```

Eso es todo. El launcher `nova` en la raíz del repo inicializa el path y lanza el hub.

> **Alternativa** si preferís explícito: `python3 novahome/main.py`

---

## Flujo de la aplicación

### Home — NovaHold

```
┌─────────────────────────────────────────────────────────┐
│   Banner ASCII "NOVAHOLD" (aquamarine)                   │
│                                                          │
│   GIT: rama main        PATH: .../CONTROL-epa           │
│   VER: v0.1.0           MÓDULOS: azulito novahld aditai  │
│   HERRAMIENTAS: 3       ENTORNO: Python · Playwright     │
│   STATUS: listo                                          │
├─────────────────────────────────────────────────────────┤
│  ? Seleccioná una herramienta:                           │
│    › azulito                                             │
│      novahld                                             │
│      aditai                                              │
│      Salir                                               │
└─────────────────────────────────────────────────────────┘
```

- **azulito** → accede al módulo de eliminación OneDrive
- **novahld** → próximamente (muestra panel informativo y vuelve)
- **aditai** → próximamente (muestra panel informativo y vuelve)
- **Salir** → cierra el hub (también funciona con `Ctrl+C`)

---

### azulito — OneDrive RPA

Al ingresar a azulito aparece un sub-menú:

```
  azulito — OneDrive RPA:
  › Eliminar archivos OneDrive
    Volver
```

#### Opción 1: Eliminar archivos OneDrive

Se ejecutan **5 verificaciones de dependencias** antes de iniciar:

```
┌── Verificación de dependencias ──────────────────────────┐
│  Dependencia    Estado    Nota                            │
│  ─────────────────────────────────────────────────────   │
│  python3        ✓  OK                                    │
│  pip            ✓  OK                                    │
│  playwright     ✓  OK                                    │
│  chromium       ✓  OK                                    │
│  .env           ✓  OK                                    │
└──────────────────────────────────────────────────────────┘
```

| Check | Qué verifica |
|-------|-------------|
| python3 | `shutil.which("python3")` — intérprete disponible |
| pip | `python -m pip --version` — gestor de paquetes |
| playwright | `import playwright` — paquete instalado |
| chromium | `playwright install --dry-run chromium` — browser descargado |
| .env | archivo existe con las 3 variables completas |

**Si todos los checks pasan:**

```
  ¿Qué querés hacer?
  › Iniciar
    Configurar variables de entorno
    Volver
```

**Si algún check falla:**

```
  Hay dependencias faltantes. ¿Qué querés hacer?
  › Configurar variables de entorno
    Volver
```

#### Opción: Configurar variables de entorno

Wizard interactivo que lee el `.env` actual y permite actualizar las 3 variables requeridas:

| Variable | Descripción |
|----------|-------------|
| `ONEDRIVE_USERNAME` | Usuario de Microsoft 365 (email) |
| `ONEDRIVE_PASSWORD` | Contraseña (siempre enmascarada, nunca se muestra) |
| `SHAREPOINT_PERSONAL_PATH` | Path personal en SharePoint (ej: `/personal/usuario_empresa_com`) |

- Si ya existe un valor, se muestra como default (excepto la contraseña).
- Si el usuario no ingresa nada, se conserva el valor anterior.
- Escribe en `onedrive_rpa/.env` (path requerido por el RPA).

#### Opción: Iniciar

Lanza el RPA como proceso hijo:

```bash
python3 onedrive_rpa/main.py --mode manual
```

El proceso RPA:
1. Abre Chromium con Playwright (headless o visible según configuración)
2. Autentica con las credenciales del `.env`
3. Navega recursivamente por las carpetas configuradas en `folders.json`
4. Elimina todos los archivos (mantiene la estructura de carpetas)
5. Muestra progreso en tiempo real con Rich TUI

El exit code del RPA se propaga al hub:

| Código | Significado |
|--------|-------------|
| 0 | Éxito o usuario canceló en la confirmación |
| 1 | Error de configuración (`folders.json` inválido) |
| 2 | `session.json` ausente en modo `--mode auto` |
| 3 | Sesión expiró durante la ejecución |
| 130 | `Ctrl+C` |

---

## Arquitectura — decisiones clave

### Separación hub / RPA

El hub **nunca importa** código de `onedrive_rpa/`. La invocación es siempre como subprocess:

```python
subprocess.run([sys.executable, "onedrive_rpa/main.py", "--mode", "manual"], cwd=REPO_ROOT)
```

Esto preserva la separación en capas del RPA y permite actualizar cada componente de forma independiente.

### Path del .env

`onedrive_rpa/config.py` resuelve el `.env` como `Path(__file__).parent / ".env"`, lo que fija la ruta en `onedrive_rpa/.env`. El wizard siempre escribe ahí — cambiar esta ruta requeriría modificar `config.py`.

### REPO_ROOT

Cada módulo del hub resuelve la raíz del repo en tiempo de import:

```python
REPO_ROOT = Path(__file__).resolve().parents[N]
```

Esto garantiza que `./nova` funcione desde cualquier directorio de trabajo.

---

## Agregar un nuevo módulo

1. Crear `novahome/modules/mi_herramienta.py` con una función `run() -> None`
2. Agregar el nombre a `novahome/main.py` en la lista de `choices`
3. Agregar el branch de dispatch en el `if/elif` de `main()`
4. Actualizar `_MODULES` en `novahome/ui/banner.py`

---

## Variables de entorno requeridas (azulito)

Copiá `onedrive_rpa/env.example` a `onedrive_rpa/.env` y completá:

```env
ONEDRIVE_USERNAME=tu_usuario@empresa.com
ONEDRIVE_PASSWORD=tu_contraseña
SHAREPOINT_PERSONAL_PATH=/personal/tu_usuario_empresa_com
```

O usá el wizard desde el hub: `azulito → Eliminar archivos OneDrive → Configurar variables de entorno`.

---

## Dependencias

| Paquete | Versión | Rol |
|---------|---------|-----|
| playwright | 1.44.0 | Automatización del browser |
| rich | 13.7.1 | TUI, paneles, tablas |
| questionary | >=2.0,<3.0 | Menús interactivos con flechas |
| pyfiglet | >=1.0 | ASCII art del banner |
| click | 8.1.7 | CLI del RPA |
| loguru | 0.7.2 | Logging con rotación |
| python-dotenv | 1.0.1 | Lectura del `.env` |
