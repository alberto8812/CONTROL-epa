from __future__ import annotations

import subprocess
from pathlib import Path

from rich.columns import Columns
from rich.console import Console
from rich.rule import Rule
from rich.text import Text

__version__ = "0.1.0"

_console = Console()
REPO_ROOT = Path(__file__).resolve().parents[2]
_MODULES = ["azulito", "novahld", "aditai"]


def _ascii_title() -> str:
    try:
        import pyfiglet
        return pyfiglet.figlet_format("NOVAHOLD", font="doom")
    except Exception:
        return "  N O V A H O L D\n"


def _git_branch() -> str:
    try:
        out = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True, text=True, cwd=REPO_ROOT, timeout=2,
        ).stdout.strip()
        return out or "detached"
    except Exception:
        return "unknown"


def _short_path(p: Path, max_len: int = 46) -> str:
    s = str(p)
    return ("..." + s[-(max_len - 3):]) if len(s) > max_len else s


def render_banner() -> None:
    art = _ascii_title()
    _console.print(Text(art, style="bold aquamarine1"), end="")

    branch = _git_branch()

    left = Text()
    left.append("  GIT:        ", style="dim white")
    left.append(f"rama {branch}\n", style="bold cyan")
    left.append("  VER:        ", style="dim white")
    left.append(f"v{__version__}\n", style="bold cyan")
    left.append("  HERRAMIENTAS:", style="dim white")
    left.append(f" {len(_MODULES)} cargadas\n", style="bold cyan")
    left.append("  STATUS:     ", style="dim white")
    left.append("listo\n", style="bold green")

    right = Text()
    right.append("  PATH:       ", style="dim white")
    right.append(f"{_short_path(REPO_ROOT)}\n", style="bold cyan")
    right.append("  MÓDULOS:    ", style="dim white")
    right.append("  ".join(_MODULES) + "\n", style="bold cyan")
    right.append("  ENTORNO:    ", style="dim white")
    right.append("Python · Playwright · Rich\n", style="bold cyan")

    _console.print(Columns([left, right], equal=True, expand=True))
    _console.print(Rule(style="bright_cyan"))
