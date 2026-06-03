"""Shared dependency check and install utilities for NovaHold modules."""
from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from pathlib import Path

# ── Constants ─────────────────────────────────────────────────────────────────


def _resolve_data_dir() -> Path:
    dev_path = Path(__file__).resolve().parents[2] / "onedrive_rpa"
    if any((dev_path / f).exists() for f in (".env", "session.json", "folders.json")):
        return dev_path
    return Path.home() / ".novahold"


REPO_ROOT: Path = Path(__file__).resolve().parents[2]  # backward-compat alias
_DATA_DIR: Path = _resolve_data_dir()
ENV_PATH: Path = _DATA_DIR / ".env"
_OS: str = platform.system()  # "Darwin", "Linux", "Windows"

REQUIRED_KEYS: list[str] = [
    "ONEDRIVE_USERNAME",
    "ONEDRIVE_PASSWORD",
    "SHAREPOINT_PERSONAL_PATH",
]

# Which module uses each dependency
USED_IN: dict[str, str] = {
    "python3":    "todos",
    "pip":        "todos",
    "playwright": "azulito",
    "chromium":   "azulito",
    ".env":       "azulito",
}

_HINTS: dict[str, str] = {
    "python3":    "Instalá Python 3.12+ desde https://python.org",
    "pip":        "Ejecutá: python3 -m ensurepip --upgrade",
    "playwright": "Ejecutá: pip install playwright==1.44.0",
    "chromium":   "Ejecutá: python3 -m playwright install chromium",
    ".env":       "Usá 'Configurar variables de entorno' en azulito",
}

_PYTHON_HINT: dict[str, str] = {
    "Darwin":  "brew install python3\n           o descargá: https://python.org/downloads",
    "Linux":   "sudo apt install python3   (Debian/Ubuntu)\n"
               "           o: sudo dnf install python3   (Fedora)\n"
               "           o: sudo pacman -S python      (Arch)",
    "Windows": "https://python.org/downloads\n"
               "           o: winget install Python.Python.3",
}

_INSTALL_CMDS: dict[str, list[list[str]]] = {
    "pip":        [[sys.executable, "-m", "ensurepip", "--upgrade"]],
    "playwright": [[sys.executable, "-m", "pip", "install", "playwright==1.44.0"]],
    "chromium":   [[sys.executable, "-m", "playwright", "install", "chromium"]],
}

_INSTALL_NOTES: dict[str, str] = {
    "chromium": "Descarga ~150 MB — puede tardar unos minutos",
}

# Deps that cannot be auto-installed
_MANUAL_ONLY = {"python3", ".env"}


# ── Dependency checks ─────────────────────────────────────────────────────────


def run_all_checks() -> list:
    """Run all 5 dependency checks unconditionally. Returns list[CheckResult]."""
    from novahome.ui.checks import CheckResult
    from dotenv import dotenv_values

    results: list[CheckResult] = []

    if _OS == "Windows":
        py3_found = shutil.which("python") is not None or shutil.which("py") is not None
    else:
        py3_found = shutil.which("python3") is not None
    results.append(CheckResult(name="python3", passed=py3_found, hint=_HINTS["python3"]))

    pip_rc = subprocess.run(
        [sys.executable, "-m", "pip", "--version"], capture_output=True
    ).returncode
    results.append(CheckResult(name="pip", passed=pip_rc == 0, hint=_HINTS["pip"]))

    pw_rc = subprocess.run(
        [sys.executable, "-c", "import playwright"], capture_output=True
    ).returncode
    results.append(CheckResult(name="playwright", passed=pw_rc == 0, hint=_HINTS["playwright"]))

    cr_rc = subprocess.run(
        [sys.executable, "-m", "playwright", "install", "--dry-run", "chromium"],
        capture_output=True,
    ).returncode
    results.append(CheckResult(name="chromium", passed=cr_rc == 0, hint=_HINTS["chromium"]))

    if ENV_PATH.exists():
        values = dotenv_values(ENV_PATH)
        env_ok = all(values.get(k) for k in REQUIRED_KEYS)
    else:
        env_ok = False
    results.append(CheckResult(name=".env", passed=env_ok, hint=_HINTS[".env"]))

    return results


# ── Install utilities ─────────────────────────────────────────────────────────


def build_install_plan(results: list) -> list[tuple[str, list | None, str]]:
    """
    Return (name, commands_or_None, extra_note) for every failing check.
    commands_or_None=None means manual action required.
    """
    plan = []
    for r in results:
        if r.passed:
            continue
        if r.name == "python3":
            note = _PYTHON_HINT.get(_OS, "Instalá Python 3 desde https://python.org")
            plan.append(("python3", None, note))
        elif r.name == ".env":
            plan.append((".env", None, "Usá 'Configurar variables de entorno' en azulito"))
        else:
            plan.append((r.name, _INSTALL_CMDS.get(r.name), _INSTALL_NOTES.get(r.name, "")))
    return plan


def install_deps(results: list) -> None:
    """
    Show install plan, ask confirmation, run commands.
    Accepts a filtered list so callers can install a single dep or all.
    """
    import questionary
    from rich.console import Console
    from rich.rule import Rule
    from rich.text import Text

    console = Console()
    plan = build_install_plan(results)

    if not plan:
        return

    console.print()
    console.print(Text("  Plan de instalación", style="bold cyan"))
    console.print()

    has_auto = False
    for name, cmds, note in plan:
        if cmds:
            console.print(f"  [bold green]►[/bold green] {name}  [dim]{' '.join(cmds[-1])}[/dim]")
            if note:
                console.print(f"    [yellow]{note}[/yellow]")
            has_auto = True
        else:
            console.print(f"  [bold yellow]⚠[/bold yellow]  {name}  — instalación manual requerida")
            for line in note.splitlines():
                console.print(f"    [dim]{line}[/dim]")

    console.print()

    if not has_auto:
        console.print(Text("  No hay dependencias que se puedan instalar automáticamente.", style="yellow"))
        questionary.press_any_key_to_continue("  Presioná cualquier tecla para continuar...").ask()
        return

    confirm = questionary.confirm("  ¿Confirmás la instalación?", default=True).ask()
    if not confirm:
        return

    console.print()
    console.print(Rule(style="cyan"))

    for name, cmds, note in plan:
        if not cmds:
            continue
        console.print(Text(f"\n  Instalando {name}...", style="bold cyan"))
        ok = True
        for cmd in cmds:
            console.print(Text(f"  $ {' '.join(cmd)}", style="dim"))
            rc = subprocess.run(cmd).returncode
            if rc != 0:
                console.print(Text(f"  ✗  Error al instalar {name} (código {rc})", style="bold red"))
                ok = False
                break
        if ok:
            console.print(Text(f"  ✓  {name} instalado correctamente", style="bold green"))

    console.print()
    console.print(Rule(style="cyan"))
    console.print(Text("\n  Verificando dependencias de nuevo...\n", style="dim"))
