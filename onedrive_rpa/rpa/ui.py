"""
rpa/ui.py — Terminal UI enterprise via Rich.

Patrón Observer: el cleaner llama callbacks y la UI actualiza en tiempo real.
La UI expone también display.log(category, message) para que capas externas
(auth, main) puedan emitir eventos al activity log sin acoplarse a Rich.
"""

from __future__ import annotations

import time
import datetime
from collections import deque
from dataclasses import dataclass, field
from typing import Callable

from rich.align import Align
from rich.columns import Columns
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.padding import Padding
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table
from rich.text import Text
from rich import box

# ── Paleta ────────────────────────────────────────────────────────────────────
_C_PRIMARY  = "cyan1"
_C_SUCCESS  = "green3"
_C_DRY      = "yellow3"
_C_ERROR    = "red3"
_C_WARN     = "dark_orange"
_C_AUTH     = "medium_orchid"
_C_NAV      = "cornflower_blue"
_C_DIM      = "grey62"
_C_BORDER   = "grey27"

_MAX_LOG  = 500
_LOG_SHOW = 40

# ── Catálogo de eventos ───────────────────────────────────────────────────────
# category → (icon, color)
_EVENTS: dict[str, tuple[str, str]] = {
    "BOOT":   ("◆", _C_PRIMARY),
    "CFG":    ("⚙", _C_DIM),
    "AUTH":   ("◉", _C_AUTH),
    "SESS":   ("◎", _C_AUTH),
    "NET":    ("⬡", _C_NAV),
    "NAV":    ("▸", _C_NAV),
    "SCAN":   ("⊡", _C_NAV),
    "DELETE": ("✕", _C_SUCCESS),
    "RMDIR":  ("⌫", _C_SUCCESS),
    "DRY":    ("◌", _C_DRY),
    "DONE":   ("✓", _C_SUCCESS),
    "ERROR":  ("✗", _C_ERROR),
    "WARN":   ("▲", _C_WARN),
    "INFO":   ("·", _C_DIM),
    "PARTIAL": ("▲", _C_WARN),
    "REPORT": ("▣", "bold cyan"),
    "UPLOAD": ("↑", "bold blue"),
    "SHARE":  ("⚿", "bold green3"),
    "SHAERR": ("⚿", "bold red3"),
}


# ── Callbacks ─────────────────────────────────────────────────────────────────

@dataclass
class RPACallbacks:
    on_folder_start:      Callable[[str], None]           = field(default=lambda *_: None)
    on_folder_done:       Callable[[str, int, int], None] = field(default=lambda *_: None)
    on_file_deleted:      Callable[[str], None]           = field(default=lambda *_: None)
    on_file_would_delete: Callable[[str], None]           = field(default=lambda *_: None)
    on_folder_deleted:    Callable[[str], None]           = field(default=lambda *_: None)
    on_error:             Callable[[str, str], None]      = field(default=lambda *_: None)
    on_folder_incomplete: Callable[[str, int], None]      = field(default=lambda *_: None)
    on_tick:              Callable[[], None]              = field(default=lambda: None)
    # Report callbacks (PR 3)
    on_report_start:      Callable[[str, str], None]      = field(default=lambda *_: None)
    on_report_subfolders: Callable[[int], None]           = field(default=lambda *_: None)
    on_report_uploaded:   Callable[[str], None]           = field(default=lambda *_: None)
    on_report_skipped:    Callable[[str], None]           = field(default=lambda *_: None)
    on_report_error:      Callable[[str], None]           = field(default=lambda *_: None)


# ── RPADisplay ────────────────────────────────────────────────────────────────

class RPADisplay:

    def __init__(self, *, mode: str, dry_run: bool, folders: list[str]) -> None:
        self._mode          = mode
        self._dry_run       = dry_run
        self._folders       = folders
        self._start_time    = time.monotonic()

        self._deleted        = 0
        self._would_delete   = 0
        self._errors         = 0
        self._incomplete     = 0
        self._folders_done   = 0
        self._current_folder = ""
        self._current_file   = ""

        # Entradas del log: (time_str, category, icon, color, message)
        self._log: deque[tuple[str, str, str, str, str]] = deque(maxlen=_MAX_LOG)

        self._console = Console()
        self._progress = self._build_progress()
        self._folder_tasks: dict[str, TaskID] = {}
        self._live: Live | None = None
        self._layout: Layout | None = None

        # Eventos de arranque
        self._emit("BOOT", f"OneDrive RPA arrancando  ·  modo [bold]{mode.upper()}[/bold]")
        self._emit("CFG",  f"{len(folders)} carpeta(s) en cola")
        if dry_run:
            self._emit("WARN", "DRY-RUN activo — simulación sin borrado real")

    # ── Context manager ───────────────────────────────────────────────────────

    def __enter__(self) -> "RPADisplay":
        self._layout = self._build_layout()
        self._live = Live(
            self._layout,
            console=self._console,
            refresh_per_second=12,
            screen=False,
            vertical_overflow="visible",
        )
        self._live.__enter__()
        return self

    def __exit__(self, *args) -> None:
        if self._live:
            self._live.__exit__(*args)
        self._print_final_summary()

    # ── API pública ───────────────────────────────────────────────────────────

    def log(self, category: str, message: str) -> None:
        """Emitir un evento al log desde capas externas (auth, session, main)."""
        self._emit(category, message)

    @property
    def callbacks(self) -> RPACallbacks:
        return RPACallbacks(
            on_folder_start=self._on_folder_start,
            on_folder_done=self._on_folder_done,
            on_file_deleted=self._on_file_deleted,
            on_file_would_delete=self._on_file_would_delete,
            on_folder_deleted=self._on_folder_deleted,
            on_error=self._on_error,
            on_folder_incomplete=self._on_folder_incomplete,
            on_tick=self._refresh,
            on_report_start=self._on_report_start,
            on_report_subfolders=self._on_report_subfolders,
            on_report_uploaded=self._on_report_uploaded,
            on_report_skipped=self._on_report_skipped,
            on_report_error=self._on_report_error,
        )

    # ── Emisión de eventos ────────────────────────────────────────────────────

    def _emit(self, category: str, message: str) -> None:
        icon, color = _EVENTS.get(category.upper(), ("·", _C_DIM))
        self._log.appendleft((_ts(), category.upper(), icon, color, message))
        self._refresh()

    # ── Handlers de callbacks ─────────────────────────────────────────────────

    def _on_folder_start(self, folder_path: str) -> None:
        self._current_folder = folder_path
        task_id = self._progress.add_task(
            f"[{_C_PRIMARY}]{folder_path}",
            total=None,
        )
        self._folder_tasks[folder_path] = task_id
        self._emit("NAV", f"Carpeta: {folder_path}")

    def _on_folder_done(self, folder_path: str, deleted: int, errors: int) -> None:
        self._folders_done += 1
        task_id = self._folder_tasks.get(folder_path)
        if task_id is not None:
            self._progress.update(task_id, completed=deleted or 1, total=deleted or 1)
            self._progress.stop_task(task_id)
        self._emit("DONE", f"{folder_path}  ·  {deleted} archivo(s) procesado(s)")

    def _on_file_deleted(self, path: str) -> None:
        self._deleted += 1
        self._current_file = path.split("/")[-1]
        task_id = self._folder_tasks.get(self._current_folder)
        if task_id is not None:
            self._progress.advance(task_id)
        self._emit("DELETE", path)

    def _on_folder_deleted(self, path: str) -> None:
        self._current_file = path.split("/")[-1]
        self._emit("RMDIR", path)

    def _on_file_would_delete(self, path: str) -> None:
        self._would_delete += 1
        self._current_file = path.split("/")[-1]
        task_id = self._folder_tasks.get(self._current_folder)
        if task_id is not None:
            self._progress.advance(task_id)
        self._emit("DRY", path)

    def _on_error(self, path: str, reason: str) -> None:
        self._errors += 1
        self._emit("ERROR", f"{path}  ·  {reason[:60]}")

    def _on_folder_incomplete(self, folder_path: str, remaining: int) -> None:
        self._incomplete += 1
        self._emit("PARTIAL", f"{folder_path}  ·  {remaining} archivo(s) NO eliminados")

    def _on_report_start(self, source: str, destination: str) -> None:
        self._emit("REPORT", f"Generating report  ·  source={source}  →  dest={destination}")

    def _on_report_subfolders(self, count: int) -> None:
        self._emit("REPORT", f"{count} subfolder(s) found")

    def _on_report_uploaded(self, filename: str) -> None:
        self._emit("UPLOAD", f"Report uploaded: {filename}")

    def _on_report_skipped(self, reason: str) -> None:
        self._emit("REPORT", f"Report skipped  ·  {reason}")

    def _on_report_error(self, msg: str) -> None:
        self._emit("ERROR", f"Report error  ·  {msg[:80]}")

    def _refresh(self) -> None:
        if not (self._live and self._layout):
            return
        self._layout["operation"].update(self._render_operation())
        self._layout["log"].update(self._render_log())
        self._layout["fileops"].update(self._render_fileops())
        self._layout["stats"].update(self._render_stats())
        self._live.refresh()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build_layout(self) -> Layout:
        layout = Layout()
        layout.split_column(
            Layout(name="header",    size=3),
            Layout(name="operation", size=6),
            Layout(name="main"),
            Layout(name="stats",     size=6),
        )
        layout["main"].split_row(
            Layout(name="log",     ratio=3),
            Layout(name="fileops", ratio=2),
        )
        layout["header"].update(self._render_header())
        layout["operation"].update(self._render_operation())
        layout["log"].update(self._render_log())
        layout["fileops"].update(self._render_fileops())
        layout["stats"].update(self._render_stats())
        return layout

    # ── Secciones ─────────────────────────────────────────────────────────────

    def _render_header(self) -> Panel:
        mode_color = _C_PRIMARY if self._mode == "manual" else "green3"

        badges = Text()
        badges.append(f"  {self._mode.upper()}  ", style=f"bold white on {mode_color}")
        if self._dry_run:
            badges.append("  ", style="")
            badges.append("  DRY-RUN  ", style="bold black on yellow3")
        badges.append("  ", style="")
        badges.append(f"  {len(self._folders)} folder(s)  ", style="dim white on grey19")

        title = Text()
        title.append("◆ ", style=f"bold {_C_PRIMARY}")
        title.append("ONEDRIVE", style="bold white")
        title.append(" RPA", style=f"bold {_C_PRIMARY}")
        title.append("  ·  File Cleanup Automation", style=f"dim {_C_DIM}")

        grid = Table.grid(expand=True)
        grid.add_column(ratio=1)
        grid.add_column(justify="right")
        grid.add_row(Padding(title, (0, 0, 0, 1)), Padding(badges, (0, 1, 0, 0)))

        return Panel(grid, box=box.MINIMAL, border_style=_C_PRIMARY, padding=(0, 1))

    def _render_operation(self) -> Panel:
        folder_text = (
            f"[{_C_DIM}]Esperando autenticación...[/]"
            if not self._current_folder
            else f"[bold white]{self._current_folder}[/]"
        )
        file_text = (
            f"  [dim]→[/]  [{_C_DIM}]{self._current_file}[/]"
            if self._current_file else ""
        )

        grid = Table.grid(expand=True, padding=(0, 1))
        grid.add_column()
        grid.add_row(Text.from_markup(f"[{_C_DIM}]CARPETA ACTIVA[/]"))
        grid.add_row(Text.from_markup(f"  {folder_text}{file_text}"))
        grid.add_row(Padding(self._progress, (1, 0, 0, 0)))

        return Panel(
            grid,
            title=f"[{_C_DIM}] OPERACIÓN [/]",
            border_style=_C_BORDER,
            box=box.ROUNDED,
            padding=(0, 1),
        )

    def _render_log(self) -> Panel:
        table = Table(
            show_header=True,
            header_style=f"bold {_C_DIM}",
            box=None,
            expand=True,
            show_edge=False,
            padding=(0, 1),
        )
        table.add_column("TIME",     style=_C_DIM, width=10, no_wrap=True)
        table.add_column("",         width=2,       no_wrap=True)
        table.add_column("EVENT",    width=8,       no_wrap=True)
        table.add_column("DETAIL",   overflow="fold", ratio=1)

        _FILE_CATS = {"DELETE", "DRY"}
        for ts, cat, icon, color, msg in list(self._log)[:_LOG_SHOW]:
            if cat in _FILE_CATS:
                continue
            table.add_row(
                f"[{_C_DIM}]{ts}[/]",
                f"[{color}]{icon}[/]",
                f"[bold {color}]{cat:<7}[/]",
                Text.from_markup(f"[white]{msg}[/]"),
            )

        return Panel(
            table,
            title=f"[{_C_DIM}] ACTIVITY LOG [/]",
            border_style=_C_BORDER,
            box=box.ROUNDED,
        )

    def _render_fileops(self) -> Panel:
        action_count = self._would_delete if self._dry_run else self._deleted
        action_color = _C_DRY if self._dry_run else _C_SUCCESS
        action_label = "simulados" if self._dry_run else "eliminados"

        counter = Text()
        counter.append(f" {action_count} ", style=f"bold {action_color}")
        counter.append(f"archivo(s) {action_label}", style=f"dim {_C_DIM}")

        table = Table(
            show_header=False,
            box=None,
            expand=True,
            show_edge=False,
            padding=(0, 1),
        )
        table.add_column("",      width=2,  no_wrap=True)
        table.add_column("TIME",  style=_C_DIM, width=10, no_wrap=True)
        table.add_column("PATH",  overflow="fold", ratio=1)

        _FILE_CATS = {"DELETE", "DRY"}
        entries = [e for e in self._log if e[1] in _FILE_CATS]
        for ts, cat, icon, color, path in entries[:_LOG_SHOW]:
            table.add_row(
                f"[{color}]{icon}[/]",
                f"[{_C_DIM}]{ts}[/]",
                f"[white]{_short_path(path)}[/]",
            )

        grid = Table.grid(expand=True)
        grid.add_column()
        grid.add_row(Padding(counter, (0, 0, 1, 1)))
        grid.add_row(table)

        return Panel(
            grid,
            title=f"[{_C_DIM}] FILE OPERATIONS [/]",
            border_style=_C_BORDER,
            box=box.ROUNDED,
        )

    def _render_stats(self) -> Panel:
        elapsed  = time.monotonic() - self._start_time
        mins, s  = divmod(int(elapsed), 60)
        hours, m = divmod(mins, 60)
        elapsed_str = f"{hours:02d}:{m:02d}:{s:02d}"

        action_count = self._would_delete if self._dry_run else self._deleted
        action_color = _C_DRY if self._dry_run else _C_SUCCESS
        action_label = "DRY-RUN" if self._dry_run else "DELETED"

        def stat_card(value: str, label: str, color: str) -> Panel:
            grid = Table.grid(expand=True)
            grid.add_column(justify="center")
            grid.add_row(Text(value, style=f"bold {color}", justify="center"))
            grid.add_row(Text(label, style=f"dim {_C_DIM}", justify="center"))
            return Panel(grid, border_style=_C_BORDER, box=box.ROUNDED, padding=(1, 2))

        cards = Columns(
            [
                stat_card(str(action_count),                            action_label,  action_color),
                stat_card(str(self._errors),                            "ERRORS",      _C_ERROR if self._errors else _C_DIM),
                stat_card(str(self._incomplete),                        "PARTIAL",     _C_WARN if self._incomplete else _C_DIM),
                stat_card(f"{self._folders_done}/{len(self._folders)}", "FOLDERS",     _C_PRIMARY),
                stat_card(elapsed_str,                                  "ELAPSED",     _C_DIM),
            ],
            expand=True,
            equal=True,
        )

        return Panel(
            Padding(cards, (0, 0)),
            title=f"[{_C_DIM}] METRICS [/]",
            border_style=_C_BORDER,
            box=box.ROUNDED,
        )

    def _build_progress(self) -> Progress:
        return Progress(
            SpinnerColumn(style=_C_PRIMARY),
            TextColumn("[{task.description}]", style="dim"),
            BarColumn(
                bar_width=None,
                style=_C_DIM,
                complete_style=_C_SUCCESS if not self._dry_run else _C_DRY,
                finished_style=f"dim {_C_SUCCESS}",
            ),
            TaskProgressColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            expand=True,
        )

    # ── Resumen final ─────────────────────────────────────────────────────────

    def _print_final_summary(self) -> None:
        elapsed  = time.monotonic() - self._start_time
        mins, s  = divmod(int(elapsed), 60)
        hours, m = divmod(mins, 60)

        action_count = self._would_delete if self._dry_run else self._deleted
        action_label = "DRY-RUN" if self._dry_run else "DELETED"
        action_color = _C_DRY if self._dry_run else _C_SUCCESS
        status_color = _C_ERROR if self._errors else _C_SUCCESS
        status_text  = "COMPLETED WITH ERRORS" if self._errors else "COMPLETED SUCCESSFULLY"

        self._console.print()
        self._console.rule(f"[bold {status_color}]{status_text}[/]")
        self._console.print()

        table = Table(box=box.SIMPLE, show_header=False, expand=False, padding=(0, 3))
        table.add_column(style=_C_DIM, justify="right")
        table.add_column(style="bold white")
        table.add_row(action_label, f"[{action_color}]{action_count}[/]")
        table.add_row("ERRORS",     f"[{_C_ERROR if self._errors else _C_DIM}]{self._errors}[/]")
        table.add_row("PARTIAL",    f"[{_C_WARN if self._incomplete else _C_DIM}]{self._incomplete}[/]")
        table.add_row("FOLDERS",    f"[{_C_PRIMARY}]{self._folders_done}/{len(self._folders)}[/]")
        table.add_row("ELAPSED",    f"[{_C_DIM}]{hours:02d}:{m:02d}:{s:02d}[/]")

        self._console.print(Align.center(table))
        self._console.print()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ts() -> str:
    return datetime.datetime.now().strftime("%H:%M:%S")


def _short_path(path: str) -> str:
    """Retorna los últimos 2 segmentos del path para display compacto.
    Ej: Documentos/Reportes/2024/file.pdf → 2024/file.pdf
    """
    parts = path.replace("\\", "/").split("/")
    return "/".join(parts[-2:]) if len(parts) > 2 else path
