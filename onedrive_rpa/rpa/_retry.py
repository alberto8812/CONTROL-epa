"""
rpa/_retry.py — Decorador de reintento para operaciones idempotentes.

SOLO usar en: list_items, navigate_to, enter_folder.
NO usar en operaciones de borrado (ADR-7: delete no es idempotente desde la UI).
"""

import time
import functools
from typing import TypeVar, Callable, Any

from loguru import logger

from onedrive_rpa.config import MAX_RETRIES, RETRY_BACKOFF_SEC

F = TypeVar("F", bound=Callable[..., Any])


def with_retry(
    max_retries: int = MAX_RETRIES,
    backoff: float = RETRY_BACKOFF_SEC,
    exceptions: tuple[type[Exception], ...] = (Exception,),
) -> Callable[[F], F]:
    """
    Decorador de reintento con backoff exponencial.

    Args:
        max_retries: Número máximo de reintentos (no cuenta el intento inicial).
        backoff: Segundos base de espera. Cada intento espera backoff * 2^(i-1).
        exceptions: Tupla de tipos de excepción que activan el reintento.

    Ejemplo:
        @with_retry(max_retries=3, backoff=2.0)
        def navigate(page, url): ...
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exc: Exception | None = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:
                    last_exc = exc
                    if attempt < max_retries:
                        wait = backoff * (2 ** attempt)
                        logger.warning(
                            "RETRY | {func} | attempt={attempt}/{max} | wait={wait}s | error={error}",
                            func=func.__name__,
                            attempt=attempt + 1,
                            max=max_retries,
                            wait=wait,
                            error=exc,
                        )
                        time.sleep(wait)
                    else:
                        logger.error(
                            "RETRY_EXHAUSTED | {func} | attempts={attempts} | error={error}",
                            func=func.__name__,
                            attempts=max_retries + 1,
                            error=exc,
                        )
            raise last_exc  # type: ignore[misc]

        return wrapper  # type: ignore[return-value]

    return decorator
