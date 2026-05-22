"""
novahome/ui/checks.py — Dependency check result display.

Defines CheckResult dataclass and renders a Rich Table inside a Panel.
Passed checks show green ✓; failed checks show red ✗ with the hint inline.
"""

from __future__ import annotations

from dataclasses import dataclass

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

_console = Console()


@dataclass
class CheckResult:
    name: str
    passed: bool
    hint: str


def render_checks(results: list[CheckResult]) -> None:
    """Render a Rich Table-in-Panel showing dependency check results."""
    table = Table(box=box.SIMPLE, show_header=True, header_style="bold grey82")
    table.add_column("Dependencia", style="white", min_width=20)
    table.add_column("Estado", justify="center", min_width=8)
    table.add_column("Nota", style="dim grey62")

    for result in results:
        if result.passed:
            status = Text("✓  OK", style="bold green3")
            note = Text("")
        else:
            status = Text("✗  Falta", style="bold red3")
            note = Text(result.hint, style="yellow3")

        table.add_row(result.name, status, note)

    all_passed = all(r.passed for r in results)
    border_style = "green3" if all_passed else "red3"
    title = "Verificación de dependencias"

    panel = Panel(table, title=title, border_style=border_style, padding=(0, 1))
    _console.print(panel)
