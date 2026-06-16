# CONTROL-epa

Hub de automatización interna con interfaz de terminal (TUI). Centraliza herramientas RPA bajo un menú interactivo unificado llamado **NovaHold**.

---

## Requisitos previos

- **Python 3.11 o superior** — [python.org/downloads](https://www.python.org/downloads/)
- **Git** (para clonar) — [git-scm.com](https://git-scm.com)
- Conexión a internet (para descargar Chromium ~150 MB la primera vez)

> **Windows:** durante la instalación de Python, marcá la opción **"Add Python to PATH"**. Sin eso, los comandos `python` y `pip` no van a funcionar en la terminal.

---

## Instalación

### Opción A — Instalador automático (recomendado)

**macOS / Linux:**
```bash
git clone https://github.com/alberto8812/CONTROL-epa.git
cd CONTROL-epa
chmod +x install.sh
./install.sh
```

**Windows (cmd o PowerShell como usuario normal):**
```
1. Clonar o descomprimir el repositorio
2. Doble click en install.bat
   — o desde cmd: install.bat
3. Abrir una terminal NUEVA y ejecutar: nova
```

El instalador verifica Python 3.11+, instala `pipx` si falta, instala `novahold` como comando global, e instala Chromium automáticamente (~150 MB — puede tardar unos minutos).

> **Windows — PATH no actualizado:** si después de instalar `nova` no es reconocido como comando,
> cerrá la terminal y abrí una nueva. Si persiste, reiniciá el equipo (Windows actualiza el PATH
> del usuario recién al iniciar sesión).

### Opción B — pipx (usuario técnico)

```bash
git clone https://github.com/alberto8812/CONTROL-epa.git
cd CONTROL-epa
pipx install .
```

### Opción C — desarrollo local (sin instalar globalmente)

```bash
git clone https://github.com/alberto8812/CONTROL-epa.git
cd CONTROL-epa
pip install -r requirements.txt
```

En Windows usá `python` en lugar de `python3`:
```bat
python -m pip install -r requirements.txt
```

Para ejecutar en modo desarrollo (sin instalar):

- **macOS/Linux:** `./nova`
- **Windows:** `python -m novahome`

### Primer uso

Después de instalar, ejecutá `nova`. La primera vez que entrés a **azulito**, el hub:
1. Verifica automáticamente si Playwright y Chromium están instalados — y ofrece instalarlos si falta algo.
2. Ofrece configurar las credenciales de OneDrive (`.env`) mediante un wizard interactivo.

No es necesario correr comandos adicionales.

---

## Ejecutar

```bash
nova
```

---

## Estructura del repositorio

```
CONTROL-epa/
├── nova                        ← launcher ejecutable (./nova) — para desarrollo
├── install.sh                  ← instalador macOS/Linux (un solo comando)
├── install.bat                 ← instalador Windows (doble click)
├── pyproject.toml              ← definición del paquete (pipx/pip)
├── requirements.txt            ← dependencias del hub (desarrollo)
├── novahome/                   ← hub NovaHold
│   ├── main.py                 ← entrada principal, menú home
│   ├── __main__.py             ← permite `python -m novahome`
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
    ├── rpa/_navigation.py      ← helpers de navegación OneDrive
    ├── rpa/reporter.py         ← pipeline del reporte Excel
    ├── rpa/ui.py               ← TUI Rich (Observer pattern)
    ├── rpa/logger.py           ← Loguru + audit log rotativo
    ├── rpa/_retry.py           ← decorador @with_retry con backoff
    ├── tests/                  ← tests unitarios del RPA
    ├── folders.json            ← carpetas a limpiar + config del reporte
    └── .env                    ← credenciales (no commitear, solo en desarrollo)
```

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

- **azulito** → accede al módulo de eliminación OneDrive (y generación de reporte)
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
| python3 | intérprete disponible (`python3` en macOS/Linux, `python` o `py` en Windows) |
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
  › Instalar dependencias faltantes
    Configurar variables de entorno
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

Lanza el RPA como proceso hijo. El proceso RPA:
1. Abre Chromium con Playwright
2. Autentica con las credenciales del `.env`
3. Navega recursivamente por las carpetas configuradas en `folders.json`
4. Elimina todos los archivos (mantiene la estructura de carpetas)
5. Muestra progreso en tiempo real con Rich TUI
6. Genera y sube reporte Excel a OneDrive (si `report` está configurado en `folders.json`)

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
subprocess.run([sys.executable, "-m", "onedrive_rpa.main", "--mode", "manual"])
```

Esto preserva la separación en capas del RPA y permite actualizar cada componente de forma independiente. Usar `-m` (invocación de módulo) garantiza que funciona tanto en desarrollo como instalado vía pipx.

### Directorio de datos

`onedrive_rpa/config.py` resuelve el directorio de datos de forma inteligente:

| Modo | Directorio | Condición |
|------|-----------|-----------|
| Desarrollo | `onedrive_rpa/` | `.env`, `session.json` o `folders.json` existen junto a `config.py` |
| Instalado | `~/.novahold/` | Ninguno de los archivos anteriores está presente |

Esto permite que `pipx install .` y `./nova` (desarrollo) coexistan sin conflictos. El wizard de credenciales siempre escribe en el directorio correcto según el modo detectado.

---

## Agregar un nuevo módulo

1. Crear `novahome/modules/mi_herramienta.py` con una función `run() -> None`
2. Agregar el nombre a `novahome/main.py` en la lista de `choices`
3. Agregar el branch de dispatch en el `if/elif` de `main()`
4. Actualizar `_MODULES` en `novahome/ui/banner.py`

---

## Configuración de `folders.json` (azulito)

`onedrive_rpa/folders.json` define qué carpetas limpiar y, opcionalmente, desde dónde generar el reporte:

```json
{
  "clean": [
    { "path": "Documentos/Reportes/Viejos" }
  ],
  "report": {
    "source_folder": "Documents/registros",
    "destination_folder": "Documents/reportes"
  }
}
```

Omitir o poner `"report": null` deshabilita la generación del reporte. El formato legacy (array directo) sigue siendo compatible.

---

## Variables de entorno requeridas (azulito)

**Instalado (`pipx install .`):** el wizard las guarda automáticamente en `~/.novahold/.env`.

**Desarrollo (repo clonado):** copiá `onedrive_rpa/env.example` a `onedrive_rpa/.env` y completá:

```env
ONEDRIVE_USERNAME=tu_usuario@empresa.com
ONEDRIVE_PASSWORD=tu_contraseña
SHAREPOINT_PERSONAL_PATH=/personal/tu_usuario_empresa_com
```

En ambos casos podés usar el wizard desde el hub: `nova → azulito → Configurar variables de entorno`.

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
| openpyxl | 3.1.2 | Generación de reportes Excel |
| cryptography | >=42.0.0 | Encriptación de URLs en el reporte |
| certifi | >=2024.0.0 | Certificados SSL actualizados |
