"""
core/retry.py — Универсальный async retry декоратор

Предоставляет:
- async_retry: декоратор с экспоненциальным backoff и специальной обработкой FloodWait

Стратегия:
    FloodWait (flood_cls): ждёт exc.seconds + flood_buffer, НЕ считается попыткой.
    exc_retry:             экспоненциальный backoff base_delay * (backoff ** (attempt-1)),
                           счётчик попыток++. После max_attempts — re-raise последнего exc.
    Остальные исключения:  re-raise немедленно (не retriable).

Нет Qt-зависимостей — чистый Python / asyncio.
"""

from __future__ import annotations

import asyncio
import functools
import logging
from typing import Any, Callable, Optional, Tuple, Type

logger = logging.getLogger(__name__)


def async_retry(
    max_attempts: int = 3,
    base_delay:   float = 1.0,
    backoff:      float = 2.0,
    exc_retry:    Tuple[Type[Exception], ...] = (OSError,),
    flood_cls:    Optional[Type[Exception]] = None,
    flood_buffer: float = 3.0,
) -> Callable:
    """
    Декоратор async-функций: retry с экспоненциальным backoff.

    Args:
        max_attempts: Максимальное число попыток (>= 1).
                      После исчерпания re-raises последнее exc_retry-исключение.
        base_delay:   Базовая задержка перед первым повтором (секунды).
        backoff:      Множитель экспоненциального роста задержки.
                      delay = base_delay * (backoff ** (attempt - 1))
        exc_retry:    Кортеж классов исключений, при которых выполняется повтор.
        flood_cls:    Класс FloodWait (напр. TelethonFloodWaitError).
                      При его поимке ждём exc.seconds + flood_buffer секунд —
                      и НЕ увеличиваем счётчик попыток.
        flood_buffer: Дополнительный буфер после FloodWait (секунды).

    Returns:
        Декоратор async-функции.

    Example:
        from telethon.errors import FloodWaitError

        @async_retry(
            max_attempts = 3,
            base_delay   = 5.0,
            backoff      = 2.0,
            exc_retry    = (OSError, RPCError),
            flood_cls    = FloodWaitError,
            flood_buffer = 3.0,
        )
        async def _download_media(self, message, target_path):
            return await message.download_media(file=target_path)
    """
    if max_attempts < 1:
        raise ValueError(f"async_retry: max_attempts должен быть >= 1, получено {max_attempts}")

    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            attempt = 0  # число израсходованных попыток из exc_retry

            while True:
                try:
                    return await fn(*args, **kwargs)

                except Exception as exc:
                    # ── FloodWait: не считаем как попытку ──────────────────
                    if flood_cls is not None and isinstance(exc, flood_cls):
                        wait = getattr(exc, "seconds", 0) + flood_buffer
                        logger.warning(
                            "async_retry[%s]: FloodWait %gs — ждём...",
                            fn.__name__, wait,
                        )
                        await asyncio.sleep(wait)
                        continue  # retry без увеличения attempt

                    # ── Retriable exception ─────────────────────────────────
                    if isinstance(exc, exc_retry):
                        attempt += 1
                        if attempt >= max_attempts:
                            logger.warning(
                                "async_retry[%s]: попытка %d/%d — исчерпаны, re-raise: %s",
                                fn.__name__, attempt, max_attempts, exc,
                            )
                            raise  # re-raise оригинальное исключение
                        delay = base_delay * (backoff ** (attempt - 1))
                        logger.warning(
                            "async_retry[%s]: попытка %d/%d, ошибка: %s — повтор через %.1f с",
                            fn.__name__, attempt, max_attempts, exc, delay,
                        )
                        await asyncio.sleep(delay)
                        continue  # retry

                    # ── Остальные исключения: не retriable ──────────────────
                    raise

        return wrapper
    return decorator
