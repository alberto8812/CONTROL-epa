# OneDrive RPA — Limpieza de carpetas

Borra todos los archivos de las carpetas configuradas en `folders.json`, entrando recursivamente en subcarpetas. Muestra el progreso en tiempo real con una TUI en la terminal.

---

## Instalación (una sola vez)

```powershell
cd C:\Users\SoporteQA2\onedrive_rpa
python -m pip install -r requirements.txt
python -m playwright install chromium
```

---

## Configuración

### 1. Credenciales — `.env`

Copiá el archivo `env.example`, renombralo a `.env` y completá con tus datos:

```powershell
copy env.example .env
```

Abrí `.env` y editá:

```env
ONEDRIVE_USERNAME=tu_usuario@empresa.com
ONEDRIVE_PASSWORD=tu_contraseña
```

> El archivo `.env` está en `.gitignore` — nunca se commitea.

Si no configurás credenciales, el script abre Chrome y esperás completar el login manualmente.

---

### 2. Carpetas a limpiar — `folders.json`

El formato actual es un objeto con dos secciones:

```json
{
  "clean": [
    { "path": "Documentos/Reportes/Viejos" },
    { "path": "Compartido/Temporales" }
  ],
  "report": {
    "source_folder": "Documents/registros",
    "destination_folder": "Documents/reportes"
  }
}
```

- **`clean`**: lista de carpetas a limpiar (rutas relativas a la raíz de tu OneDrive).
- **`report.source_folder`**: carpeta cuyos subcarpetas directas se enumeran para el reporte.
- **`report.destination_folder`**: carpeta donde se sube el Excel generado.
- Para deshabilitar el reporte, omitá la clave `report` o poné `"report": null`.

> **Formato legacy**: si `folders.json` es un array `[{ "path": "..." }]`, el script lo sigue soportando — el reporte simplemente no se genera.

---

### 3. Reporte automático

Al terminar la limpieza, si `report` está configurado en `folders.json`, el script:

1. Enumera las subcarpetas inmediatas de `report.source_folder`.
2. Genera un Excel con tres columnas: **Nombre de carpeta**, **Contraseña** (generada aleatoriamente, 24 caracteres) y **Fecha de creación**.
3. Sube el archivo `reporte_YYYYMMDD_HHMMSS.xlsx` a `report.destination_folder` en OneDrive.

El reporte es **no fatal** — si falla, el script termina con exit code 0 igual y muestra el error en la TUI.

Con `--dry-run` el reporte se omite.

---

## Uso

### Dry-run — ver qué se borraría sin borrar nada

```powershell
cd C:\Users\SoporteQA2\onedrive_rpa
python main.py --mode manual --dry-run
```

Siempre corré dry-run primero para verificar que las carpetas y archivos son los correctos.

---

### Borrado real

```powershell
python main.py --mode manual
```

El script te pide escribir `DELETE` para confirmar antes de borrar.

---

### Modo automatizado (sin ventana, para tarea programada)

```powershell
python main.py --mode auto --yes
```

Requiere que `session.json` exista. Si no existe, corré modo manual al menos una vez.
Si la sesión expiró, el script avisa con exit code 3.

---

### Forzar nuevo login

```powershell
python main.py --mode manual --relogin
```

---

## Flags

| Flag | Descripción |
|------|-------------|
| `--mode manual` | Browser visible. Usa `.env` para auto-login si están configuradas las credenciales. |
| `--mode auto` | Headless, usa `session.json` guardada. Requiere login previo. |
| `--dry-run` | Lista lo que borraría sin borrar nada. |
| `--yes` | Salta la confirmación interactiva (útil en scripts/CI). |
| `--relogin` | Ignora `session.json` y fuerza un nuevo login. |

---

## Exit codes

| Código | Significado |
|--------|-------------|
| `0` | Éxito (o abortado por el usuario en confirmación) |
| `1` | Error de configuración (`folders.json` inválido) |
| `2` | Sesión faltante en modo `auto` |
| `3` | Sesión expirada durante la ejecución |
| `4` | Una o más carpetas no quedaron completamente vacías |
| `130` | Interrumpido con Ctrl+C |

---

## Archivos importantes

| Archivo | Qué es |
|---------|--------|
| `folders.json` | Carpetas a limpiar y configuración del reporte — **editá esto** |
| `.env` | Credenciales — **crear desde `env.example`**, nunca commitear |
| `env.example` | Template del `.env` sin valores reales |
| `session.json` | Sesión guardada de Playwright — se crea automático, nunca commitear |
| `config.py` | Selectores, timeouts y constantes del reporte — ajustar si la UI de OneDrive cambia |
| `logs/` | Auditoría de archivos eliminados con timestamp |

---

## Estructura del proyecto

```
onedrive_rpa/
├── .env                  # credenciales (nunca commitear)
├── env.example           # template del .env
├── folders.json          # carpetas a limpiar + config del reporte
├── session.json          # sesión Playwright (auto-generado)
├── requirements.txt
├── config.py             # constantes, selectores, carga .env
├── main.py               # CLI entry point
├── auth/
│   └── session.py        # login manual / auto-fill / carga de sesión
├── rpa/
│   ├── cleaner.py        # borrado recursivo DFS
│   ├── _navigation.py    # helpers de navegación OneDrive (extraído de cleaner)
│   ├── reporter.py       # pipeline del reporte: enumerar → Excel → subir
│   ├── ui.py             # TUI Rich con progreso en tiempo real
│   ├── logger.py         # logging a consola y archivo
│   └── _retry.py         # decorador retry con backoff
├── tests/
│   ├── test_reporter.py  # tests unitarios del reporte
│   └── test_config_loader.py  # tests del cargador de folders.json
└── logs/
    └── audit_YYYY-MM-DD.log
```

---

## Notas de operación

- **MFA**: si tu cuenta tiene autenticación de dos factores, el script llena usuario y contraseña automáticamente y espera que vos completes el MFA en la ventana del browser (hasta 5 minutos).
- **Selectores**: la UI de OneDrive puede cambiar con actualizaciones de Microsoft. Si el script falla al navegar o borrar, revisá los selectores en `config.py` → `SELECTORS`.
- **Sesión expirada**: las sesiones corporativas suelen durar entre 1 y 7 días. Cuando expire, volvé a correr con `--mode manual` para renovarla.
- **openpyxl**: `requirements.txt` incluye `openpyxl==3.1.2`, necesario para generar el reporte Excel. No requiere Excel instalado.
