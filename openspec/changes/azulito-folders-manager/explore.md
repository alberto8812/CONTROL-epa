# Exploration: azulito-folders-manager

## Schema actual de folders.json

```json
{
  "clean": [
    { "path": "pruebas/archivos_1" }
  ],
  "report": {
    "source_folder": "pruebas",
    "destination_folder": "pruebas/registro"
  }
}
```

- `clean` — requerido, array de `{path: string}`. Paths relativos, sin `..`, sin vacíos.
- `report` — opcional (null o ausente); ambos campos requeridos si la sección existe.
- Formato legacy (array directo) soportado por el RPA pero no usado en la práctica.

## Resolución del directorio de datos

`config.py::_resolve_data_dir()`: si `.env`, `session.json` o `folders.json` existen en `onedrive_rpa/` → modo dev, usa esa carpeta. Caso contrario → `~/.novahold/`. El hub usa la misma lógica en `_deps.py`.

## Menú actual de azulito

```
azulito — OneDrive RPA:
  > Eliminar archivos OneDrive
  > Volver

¿Qué querés hacer?:
  > Iniciar
  > Renovar sesión
  > Configurar variables de entorno
  > Volver
```

## Patrones UI existentes

`questionary.select`, `questionary.text(default=...)`, `questionary.password`, `questionary.confirm`, `questionary.press_any_key_to_continue`. Retorno `None` = Ctrl+C, siempre protegido.

## Enfoques

| Opción | Descripción | Pros | Contras |
|--------|-------------|------|---------|
| A | Inline en azulito.py | Sin archivos nuevos | azulito.py con 3 responsabilidades |
| B | `folder_manager.py` dedicado | SRP, testeable, sigue el patrón de instalaciones.py | Un archivo nuevo |
| C | Extender configure_env() | Un punto de configuración | Mezcla credenciales con config operativa |

## Recomendación: Opción B

Módulo dedicado `novahome/modules/folder_manager.py` con `run()`, llamado desde `azulito.run()`.

**UX del manager:**
```
Gestionar carpetas — folders.json:
  > Ver carpetas configuradas
  > Agregar carpeta a limpiar
  > Eliminar carpeta de la lista
  > Configurar sección de reportes
  > Volver
```

## Archivos afectados

| Archivo | Cambio |
|---------|--------|
| `novahome/modules/folder_manager.py` | Nuevo — lógica CRUD |
| `tests/test_folder_manager.py` | Nuevo — tests unitarios |
| `novahome/modules/azulito.py` | Agregar opción "Gestionar carpetas" |
| `novahome/modules/_deps.py` | Exponer `DATA_DIR` (1 línea) |

Sin cambios al RPA, sin dependencias nuevas.

## Riesgos

1. **Lista clean vacía**: `_load_folders()` llama `sys.exit(1)` si `clean` está vacío. El manager debe advertir pero no bloquear.
2. **`_DATA_DIR` privado**: renombrar a `DATA_DIR` en `_deps.py` antes de usarlo.
3. **Estado parcial en `report`**: ambos campos o ninguno. Validar antes de escribir.
4. **Validación de paths duplicada**: hub isolation impide importar de `onedrive_rpa/`. Replicar la validación en `folder_manager.py`.
5. **Upgrade silencioso**: si hay formato legacy, escribir en formato moderno al guardar.
