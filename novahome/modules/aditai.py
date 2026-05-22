"""
novahome/modules/aditai.py — Placeholder for the aditai tool.

Shows a "Coming Soon" panel when invoked from the main menu.
"""

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

_console = Console()


def run() -> None:
    """Entry point for the aditai module (coming soon)."""
    content = Text("aditai — Coming Soon", style="bold medium_orchid")
    panel = Panel(content, border_style="medium_orchid", padding=(1, 4))
    _console.print(panel)
