"""
novahome/modules/novahld.py — Placeholder for the novahld tool.

Shows a "Coming Soon" panel when invoked from the main menu.
"""

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

_console = Console()


def run() -> None:
    """Entry point for the novahld module (coming soon)."""
    content = Text("novahld — Coming Soon", style="bold yellow3")
    panel = Panel(content, border_style="yellow3", padding=(1, 4))
    _console.print(panel)
