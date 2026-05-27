"""
novahome/modules/azulito.py — Azulito: OneDrive RPA launcher.

Responsibilities:
- Env wizard for onedrive_rpa/.env
- Dep-check loop before running the RPA
- Subprocess launch of onedrive_rpa/main.py
"""
from __future__ import annotations

import subprocess
import sys

from novahome.modules._deps import (
    ENV_PATH,
    REQUIRED_KEYS,
    build_install_plan,
    install_deps,
    run_all_checks,
)


# ── Env wizard ────────────────────────────────────────────────────────────────


def configure_env() -> None:
    """Wizard to configure onedrive_rpa/.env — merge/patch strategy."""
    import questionary
    from dotenv import dotenv_values
    from rich.console import Console
    from rich.text import Text

    console = Console()
    existing = dotenv_values(ENV_PATH) if ENV_PATH.exists() else {}

    while True:
        raw_username = questionary.text(
            "ONEDRIVE_USERNAME:",
            default=existing.get("ONEDRIVE_USERNAME") or "",
        ).ask()

        raw_password = questionary.password("ONEDRIVE_PASSWORD:").ask()

        raw_sharepoint = questionary.text(
            "SHAREPOINT_PERSONAL_PATH:",
            default=existing.get("SHAREPOINT_PERSONAL_PATH") or "",
        ).ask()

        if any(v is None for v in [raw_username, raw_password, raw_sharepoint]):
            console.print(Text("Configuración cancelada.", style="yellow3"))
            return

        username = raw_username.strip() or existing.get("ONEDRIVE_USERNAME", "")
        password = raw_password.strip() or existing.get("ONEDRIVE_PASSWORD", "")
        sharepoint_path = raw_sharepoint.strip() or existing.get("SHAREPOINT_PERSONAL_PATH", "")

        if not username or not password or not sharepoint_path:
            console.print(Text("Error: todos los campos son requeridos.", style="red3"))
            continue
        break

    # Optional: generate/regenerate FOLDERS_ENCRYPTION_KEY (EU-7)
    has_existing_key = bool(existing.get("FOLDERS_ENCRYPTION_KEY"))
    if has_existing_key:
        regen = questionary.confirm(
            "FOLDERS_ENCRYPTION_KEY already exists. Regenerate? (old encrypted URLs will become unreadable)",
            default=False,
        ).ask()
        if regen:
            from cryptography.fernet import Fernet as _Fernet
            merged_key = _Fernet.generate_key().decode("ascii")
        else:
            merged_key = None  # keep existing
    else:
        gen_new = questionary.confirm(
            "Generate a FOLDERS_ENCRYPTION_KEY for report URL encryption?",
            default=True,
        ).ask()
        if gen_new:
            from cryptography.fernet import Fernet as _Fernet
            merged_key = _Fernet.generate_key().decode("ascii")
        else:
            merged_key = None  # user opted out

    ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    merged = dict(existing)
    merged["ONEDRIVE_USERNAME"] = username
    merged["ONEDRIVE_PASSWORD"] = password
    merged["SHAREPOINT_PERSONAL_PATH"] = sharepoint_path
    if merged_key is not None:
        merged["FOLDERS_ENCRYPTION_KEY"] = merged_key
    ENV_PATH.write_text("".join(f"{k}={v}\n" for k, v in merged.items()), encoding="utf-8")
    console.print(Text(f"\n.env guardado en {ENV_PATH}", style="bold green3"))


# ── RPA launcher ──────────────────────────────────────────────────────────────


def launch_rpa(relogin: bool = False) -> int:
    cmd = [sys.executable, "-m", "onedrive_rpa.main", "--mode", "manual"]
    if relogin:
        cmd.append("--relogin")
    result = subprocess.run(cmd)
    return result.returncode


# ── Eliminar flow ─────────────────────────────────────────────────────────────


def _eliminar_flow() -> None:
    import questionary
    from rich.console import Console
    from rich.text import Text
    from novahome.ui.checks import render_checks

    console = Console()

    while True:
        results = run_all_checks()
        render_checks(results)
        all_passed = all(r.passed for r in results)

        if all_passed:
            action = questionary.select(
                "¿Qué querés hacer?",
                choices=["Iniciar", "Renovar sesión", "Configurar variables de entorno", "Volver"],
            ).ask()
            if action is None or action == "Volver":
                return
            elif action == "Iniciar":
                code = launch_rpa()
                if code == 3:
                    console.print(Text(
                        "\n⚠  Sesión expirada. Vas a tener que loguearte de nuevo.",
                        style="bold yellow3",
                    ))
                    renew = questionary.confirm("¿Renovar sesión ahora?", default=True).ask()
                    if renew:
                        sys.exit(launch_rpa(relogin=True))
                else:
                    sys.exit(code)
            elif action == "Renovar sesión":
                sys.exit(launch_rpa(relogin=True))
            elif action == "Configurar variables de entorno":
                configure_env()
        else:
            action = questionary.select(
                "Hay dependencias faltantes. ¿Qué querés hacer?",
                choices=["Instalar dependencias faltantes", "Configurar variables de entorno", "Volver"],
            ).ask()
            if action is None or action == "Volver":
                return
            elif action == "Instalar dependencias faltantes":
                install_deps(results)
            elif action == "Configurar variables de entorno":
                configure_env()


# ── Module entry point ────────────────────────────────────────────────────────


def run() -> None:
    import questionary

    while True:
        choice = questionary.select(
            "azulito — OneDrive RPA:",
            choices=["Eliminar archivos OneDrive", "Volver"],
        ).ask()

        if choice is None or choice == "Volver":
            return
        if choice == "Eliminar archivos OneDrive":
            _eliminar_flow()
