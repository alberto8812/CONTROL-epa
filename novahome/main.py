"""
novahome/main.py — Entry point for the NovaHome hub.

Usage:
    python novahome/main.py          (from repo root)
    python -m novahome.main          (as module)

Presents a top-level menu and dispatches to each tool module via lazy import.
KeyboardInterrupt exits cleanly with code 130.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running as a script directly: python novahome/main.py
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from novahome.ui.banner import render_banner


def main() -> None:
    """Render the NovaHome banner and dispatch to the selected tool."""
    import questionary

    render_banner()

    while True:
        choice = questionary.select(
            "Seleccioná una herramienta:",
            choices=["azulito", "novahld", "aditai", "Salir"],
        ).ask()

        if choice is None or choice == "Salir":
            break

        if choice == "azulito":
            from novahome.modules.azulito import run
            run()
        elif choice == "novahld":
            from novahome.modules.novahld import run
            run()
        elif choice == "aditai":
            from novahome.modules.aditai import run
            run()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nHasta luego.")
        sys.exit(130)
