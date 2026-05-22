"""
novahome/modules/instalaciones.py — Gestor de dependencias del hub.

Muestra el estado de cada dependencia, en qué módulo se usa,
y permite instalar una por una o todas las que falten.
"""
from __future__ import annotations

from novahome.modules._deps import USED_IN, build_install_plan, install_deps, run_all_checks


def run() -> None:
    import questionary
    from novahome.ui.checks import render_checks

    while True:
        results = run_all_checks()
        render_checks(results, used_in=USED_IN)

        failing_installable = [
            r for r in results
            if not r.passed and r.name not in ("python3", ".env")
        ]
        failing_manual = [
            r for r in results
            if not r.passed and r.name in ("python3", ".env")
        ]
        all_passed = all(r.passed for r in results)

        if all_passed:
            try:
                questionary.press_any_key_to_continue(
                    "  Todo está instalado. Presioná cualquier tecla para volver."
                ).ask()
            except KeyboardInterrupt:
                pass
            return

        # Build choices: install each one individually + install all + volver
        choices = []
        for r in failing_installable:
            choices.append(f"Instalar  {r.name}")
        if len(failing_installable) > 1:
            choices.append("Instalar todo lo posible")
        if failing_manual:
            choices.append("Ver instrucciones manuales")
        choices.append("Volver")

        try:
            action = questionary.select("¿Qué querés hacer?", choices=choices).ask()
        except KeyboardInterrupt:
            return

        if action is None or action == "Volver":
            return
        elif action == "Instalar todo lo posible":
            install_deps(results)
        elif action == "Ver instrucciones manuales":
            _show_manual_hints(failing_manual)
        elif action and action.startswith("Instalar  "):
            dep_name = action[len("Instalar  "):]
            target = [r for r in results if r.name == dep_name]
            install_deps(target)


def _show_manual_hints(failing: list) -> None:
    import questionary
    from novahome.modules._deps import _PYTHON_HINT, _OS
    from rich.console import Console
    from rich.panel import Panel
    from rich.text import Text

    console = Console()
    for r in failing:
        if r.name == "python3":
            hint = _PYTHON_HINT.get(_OS, "Instalá Python 3 desde https://python.org")
            body = Text(f"  python3\n\n  {hint}", style="white")
        else:
            body = Text(f"  {r.name}\n\n  {r.hint}", style="white")
        console.print(Panel(body, title="Instalación manual requerida", border_style="yellow"))

    questionary.press_any_key_to_continue("  Presioná cualquier tecla para continuar...").ask()
