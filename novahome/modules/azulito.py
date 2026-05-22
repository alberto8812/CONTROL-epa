"""
novahome/modules/azulito.py — Azulito: OneDrive RPA launcher and configuration hub.

Responsibilities:
- Run 5 dependency checks (python3, pip, playwright, chromium, .env)
- Configure the .env file via interactive prompts
- Launch onedrive_rpa/main.py as a subprocess (ADR-1)

ADR-1: RPA invoked via subprocess.run — zero changes to onedrive_rpa/.
ADR-2: Env wizard reads with dotenv_values, prompts with existing defaults,
        ONEDRIVE_PASSWORD always blank, full rewrite of .env.
ADR-3: All 5 checks run unconditionally, results in list[CheckResult].
ADR-4: Imports (render_checks, CheckResult) only inside run() and
        configure_env() where needed.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

# ── Constants (ADR-1) ─────────────────────────────────────────────────────────

REPO_ROOT: Path = Path(__file__).resolve().parents[2]
ENV_PATH: Path = REPO_ROOT / "onedrive_rpa" / ".env"

REQUIRED_KEYS: list[str] = [
    "ONEDRIVE_USERNAME",
    "ONEDRIVE_PASSWORD",
    "SHAREPOINT_PERSONAL_PATH",
]

# Remediation hints per check (shown inline when check fails)
_HINTS: dict[str, str] = {
    "python3": "Install Python 3.12+ from https://python.org",
    "pip": "Run: python3 -m ensurepip --upgrade",
    "playwright": "Run: pip install playwright",
    "chromium": "Run: python3 -m playwright install chromium",
    ".env": f"Run 'Configurar variables de entorno' to set up {ENV_PATH}",
}


# ── Dependency checks (ADR-3) ─────────────────────────────────────────────────


def run_all_checks() -> list:
    """
    Run all 5 dependency checks unconditionally.

    Returns a list[CheckResult] (type imported lazily to match ADR-4 pattern,
    but CheckResult is a plain dataclass so we import it here for the return).
    """
    from novahome.ui.checks import CheckResult
    from dotenv import dotenv_values

    results: list[CheckResult] = []

    # 1. python3
    results.append(
        CheckResult(
            name="python3",
            passed=shutil.which("python3") is not None,
            hint=_HINTS["python3"],
        )
    )

    # 2. pip (use current interpreter to avoid pip vs pip3 ambiguity)
    pip_rc = subprocess.run(
        [sys.executable, "-m", "pip", "--version"], capture_output=True
    ).returncode
    results.append(
        CheckResult(
            name="pip",
            passed=pip_rc == 0,
            hint=_HINTS["pip"],
        )
    )

    # 3. playwright (importable via current interpreter)
    playwright_rc = subprocess.run(
        [sys.executable, "-c", "import playwright"], capture_output=True
    ).returncode
    results.append(
        CheckResult(
            name="playwright",
            passed=playwright_rc == 0,
            hint=_HINTS["playwright"],
        )
    )

    # 4. chromium (installed via playwright)
    chromium_rc = subprocess.run(
        [sys.executable, "-m", "playwright", "install", "--dry-run", "chromium"],
        capture_output=True,
    ).returncode
    results.append(
        CheckResult(
            name="chromium",
            passed=chromium_rc == 0,
            hint=_HINTS["chromium"],
        )
    )

    # 5. .env (exists and all required keys are non-empty)
    if ENV_PATH.exists():
        values = dotenv_values(ENV_PATH)
        env_ok = all(values.get(k) for k in REQUIRED_KEYS)
    else:
        env_ok = False
    results.append(
        CheckResult(
            name=".env",
            passed=env_ok,
            hint=_HINTS[".env"],
        )
    )

    return results


# ── Env wizard (ADR-2) ────────────────────────────────────────────────────────


def configure_env() -> None:
    """
    Interactive wizard to configure onedrive_rpa/.env.

    Reads existing values as defaults (ONEDRIVE_PASSWORD always blank).
    Validates all 3 fields are non-empty before writing.
    Rewrites the .env file with exactly 3 KEY=value lines.
    """
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

        raw_password = questionary.password(
            "ONEDRIVE_PASSWORD:",
        ).ask()

        raw_sharepoint = questionary.text(
            "SHAREPOINT_PERSONAL_PATH:",
            default=existing.get("SHAREPOINT_PERSONAL_PATH") or "",
        ).ask()

        # Handle Ctrl+C during prompts (questionary returns None)
        if any(v is None for v in [raw_username, raw_password, raw_sharepoint]):
            console.print(Text("Configuración cancelada.", style="yellow3"))
            return

        # Merge: empty input keeps existing value (except password — always required)
        username = raw_username.strip() or existing.get("ONEDRIVE_USERNAME", "")
        password = raw_password.strip() or existing.get("ONEDRIVE_PASSWORD", "")
        sharepoint_path = raw_sharepoint.strip() or existing.get("SHAREPOINT_PERSONAL_PATH", "")

        if not username or not password or not sharepoint_path:
            console.print(
                Text(
                    "Error: todos los campos son requeridos. Por favor completalos.",
                    style="red3",
                )
            )
            continue

        break

    # Merge wizard values on top of all existing keys, then full rewrite (ADR-2 + C-3 fix)
    ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    merged = dict(existing)
    merged["ONEDRIVE_USERNAME"] = username
    merged["ONEDRIVE_PASSWORD"] = password
    merged["SHAREPOINT_PERSONAL_PATH"] = sharepoint_path
    env_content = "".join(f"{k}={v}\n" for k, v in merged.items())
    ENV_PATH.write_text(env_content, encoding="utf-8")

    console.print(
        Text(f"\n.env guardado correctamente en {ENV_PATH}", style="bold green3")
    )


# ── RPA launcher (ADR-1) ──────────────────────────────────────────────────────


def launch_rpa() -> int:
    """
    Launch onedrive_rpa/main.py as a subprocess.

    Returns the process returncode so callers can sys.exit() with it.
    """
    result = subprocess.run(
        [sys.executable, "onedrive_rpa/main.py", "--mode", "manual"],
        cwd=REPO_ROOT,
    )
    return result.returncode


# ── Eliminar flow ─────────────────────────────────────────────────────────────


def _eliminar_flow() -> None:
    """Run dep checks then offer Iniciar / Configurar / Volver."""
    import questionary
    from novahome.ui.checks import render_checks

    results = run_all_checks()
    render_checks(results)
    all_passed = all(r.passed for r in results)

    if all_passed:
        action = questionary.select(
            "¿Qué querés hacer?",
            choices=["Iniciar", "Configurar variables de entorno", "Volver"],
        ).ask()
    else:
        action = questionary.select(
            "Hay dependencias faltantes. ¿Qué querés hacer?",
            choices=["Configurar variables de entorno", "Volver"],
        ).ask()

    if action is None or action == "Volver":
        return
    elif action == "Iniciar":
        sys.exit(launch_rpa())
    elif action == "Configurar variables de entorno":
        configure_env()


# ── Module orchestrator (ADR-4) ───────────────────────────────────────────────


def run() -> None:
    """
    Main entry point for the azulito module.

    Shows a sub-menu first:
      1. Eliminar archivos OneDrive  → dep checks → Iniciar / Configurar / Volver
      2. Volver                      → back to NovaHold home
    """
    import questionary

    while True:
        choice = questionary.select(
            "azulito — OneDrive RPA:",
            choices=[
                "Eliminar archivos OneDrive",
                "Volver",
            ],
        ).ask()

        if choice is None or choice == "Volver":
            return

        if choice == "Eliminar archivos OneDrive":
            _eliminar_flow()
