"""
rpa/logger.py — Configuración de loguru para el proyecto.

Dos sinks (ADR-8 — texto plano, no JSON):
    1. stdout  → nivel INFO, con color.
    2. archivo → nivel DEBUG, rotación diaria, retención 30 días.

Formato greppable:
    {time:YYYY-MM-DDTHH:mm:ss.SSS} | {level:<8} | {message}

Importar y llamar configure_logging() desde main.py antes de cualquier
otra operación.
"""

import sys
from pathlib import Path

from loguru import logger

from onedrive_rpa.config import LOG_DIR


def configure_logging() -> None:
    """
    Configura loguru con dos sinks: consola (INFO) y archivo rotativo (DEBUG).

    Llamar una sola vez al inicio de main.py.
    """
    # Remover el sink por defecto de loguru (stderr sin formato)
    logger.remove()

    log_format = "{time:YYYY-MM-DDTHH:mm:ss.SSS} | {level:<8} | {message}"

    # Sink 1: consola stdout, nivel INFO
    logger.add(
        sys.stdout,
        level="INFO",
        format=log_format,
        colorize=True,
        enqueue=False,
    )

    # Sink 2: archivo rotativo diario, nivel DEBUG, retención 30 días
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / "audit_{time:YYYY-MM-DD}.log"

    logger.add(
        str(log_file),
        level="DEBUG",
        format=log_format,
        rotation="00:00",       # Rotar a medianoche (diario)
        retention="30 days",    # Retener 30 días
        encoding="utf-8",
        enqueue=False,
    )
