"""
novahome/main.py — Entry point for the NovaHold hub.

Usage:
    ./nova                (launcher script at repo root)
    python novahome/main.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from novahome.ui.banner import render_banner


def main() -> None:
    import questionary
    from novahome.modules._deps import run_all_checks
    from novahome.ui.checks import render_home_summary

    render_banner()

    # Compact dep status on the home screen
    results = run_all_checks()
    render_home_summary(results)

    while True:
        try:
            choice = questionary.select(
                "Seleccioná una herramienta:",
                choices=["azulito", "novahld", "aditai", "Instalaciones", "Salir"],
            ).ask()
        except KeyboardInterrupt:
            break

        if choice is None or choice == "Salir":
            break

        try:
            if choice == "azulito":
                from novahome.modules.azulito import run
                run()
            elif choice == "novahold":
                from novahome.modules.novahld import run
                run()
            elif choice == "aditia":
                from novahome.modules.aditai import run
                run()
            elif choice == "Instalaciones":
                from novahome.modules.instalaciones import run
                run()
        except KeyboardInterrupt:
            pass  # module interrupted — return to home menu


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nHasta luego.")
        sys.exit(130)
