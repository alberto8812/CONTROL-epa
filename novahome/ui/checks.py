"""
novahome/ui/checks.py — Dependency check result display.

CheckResult dataclass + two render functions:
  render_home_summary() — compact one-liner for the home screen
  render_checks()       — full Table-in-Panel, optional "Usado en" column
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


def render_home_summary(results: list[CheckResult]) -> None:
    """Compact inline status shown on the NovaHold home screen."""
    line = Text()
    for i, r in enumerate(results):
        if i > 0:
            line.append("    ")
        line.append(r.name, style="white")
        line.append(" ")
        if r.passed:
            line.append("✓", style="bold green3")
        else:
            line.append("✗", style="bold red3")

    all_ok = all(r.passed for r in results)
    border = "green3" if all_ok else "red3"
    _console.print(Panel(line, title="[dim]Sistema[/dim]", border_style=border, padding=(0, 2)))


def render_checks(results: list[CheckResult], used_in: dict[str, str] | None = None) -> None:
    """
    Full Table-in-Panel showing dependency check results.

    Args:
        results:  list of CheckResult from run_all_checks()
        used_in:  optional dict mapping dep name → module that uses it.
                  When provided, adds a "Usado en" column.
    """
    table = Table(box=box.SIMPLE, show_header=True, header_style="bold grey82")
    table.add_column("Dependencia", style="white", min_width=14)
    table.add_column("Estado", justify="center", min_width=8)
    table.add_column("Nota", style="dim grey62")
    if used_in is not None:
        table.add_column("Usado en", style="dim cyan", min_width=12)

    for r in results:
        status = (
            Text("✓  OK", style="bold green3")
            if r.passed
            else Text("✗  Falta", style="bold red3")
        )
        note = Text("") if r.passed else Text(r.hint, style="yellow3")

        if used_in is not None:
            table.add_row(r.name, status, note, used_in.get(r.name, "—"))
        else:
            table.add_row(r.name, status, note)

    all_passed = all(r.passed for r in results)
    panel = Panel(
        table,
        title="Verificación de dependencias",
        border_style="green3" if all_passed else "red3",
        padding=(0, 1),
    )
    _console.print(panel)
