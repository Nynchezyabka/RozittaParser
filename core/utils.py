"""
core/utils.py — Общие утилиты Rozitta Parser

Содержит:
- finalize_telegram_id: единственная точка нормализации Telegram ID
- Вспомогательные функции для файлов, дат, путей

Правило нормализации (Peer Logic):
    User       : ID всегда > 0   (если пришёл отрицательный — берём abs)
    Chat       : ID начинается с одиночного '-' (например: -456789)
    Channel /
    Supergroup /
    Forum      : ID начинается с '-100' (например: -1002882674903)

Золотое правило:
    Данные напрямую от Telethon (dialog.entity.id) — используем AS IS.
    Данные из ввода пользователя / конфига / БД — пропускаем через finalize_telegram_id.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Literal, Set

from telethon import TelegramClient

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Создаём настроенный экземпляр TelegramClient.
# ---------------------------------------------------------------------------
def build_telegram_client(cfg, *,
                          auto_reconnect=True,
                          connection_retries=5,
                          retry_delay=5,
                          timeout=120,
                          ) -> TelegramClient:
    config = {
        'api_id': cfg.api_id,
        'api_hash': cfg.api_hash,
        'app_version': "3.3.0",
        'auto_reconnect': auto_reconnect,
        'connection_retries': connection_retries,
        'device_model': "Rozitta Parser Desktop",
        'lang_code': "ru",
        'retry_delay': retry_delay,
        'session': cfg.session_name,
        'system_version': "Windows 11",
        'system_lang_code': "ru-RU",
        'timeout': timeout,
    }

    if cfg.proxy_enabled:
        print('use proxy')
        from telethon.network import ConnectionTcpMTProxyAbridged
        config['proxy'] = ('tg2.x6.homes', 443, 'dd9d137443c118caab90485732ae358230')
        config['connection'] = ConnectionTcpMTProxyAbridged

    print(config)
    return TelegramClient(**config)


# ---------------------------------------------------------------------------
# Типы сущностей Telegram
# ---------------------------------------------------------------------------

class TelegramEntityType(str, Enum):
    """Тип сущности Telegram, определяет правило нормализации ID."""
    USER = "user"            # Личный чат / бот
    CHAT = "chat"            # Обычная (legacy) группа
    CHANNEL = "channel"      # Канал / супергруппа / форум


# ---------------------------------------------------------------------------
# Нормализация Telegram ID
# ---------------------------------------------------------------------------

def finalize_telegram_id(
        raw_id: int | str,
        entity_type: TelegramEntityType = TelegramEntityType.CHANNEL,
) -> int:
    """
    Универсальная нормализация Telegram Peer ID.

    Единственная функция в проекте, которая приводит «сырой» ID к формату,
    понятному Telethon / MTProto. Все остальные модули обязаны получать
    уже нормализованные значения — и никогда не делать приведение самостоятельно.

    Args:
        raw_id:      Числовой ID в любом виде (int или str).
                     Может быть положительным, отрицательным, с/без префикса.
        entity_type: Тип сущности. По умолчанию CHANNEL (самый частый случай).

    Returns:
        Нормализованный int:
          - USER    →  abs(raw_id)
          - CHAT    → -abs(raw_id)      (одиночный минус)
          - CHANNEL → -(100_000_000_000 + abs(raw_id_without_prefix))
                       формула: int(f"-100{abs_id_digits}")

    Raises:
        TypeError:  если raw_id невозможно привести к int.
        ValueError: если raw_id == 0.

    Examples:
        >>> finalize_telegram_id(2882674903, TelegramEntityType.CHANNEL)
        -1002882674903
        >>> finalize_telegram_id(-1002882674903, TelegramEntityType.CHANNEL)
        -1002882674903           # уже нормализован — не меняется
        >>> finalize_telegram_id(123456, TelegramEntityType.USER)
        123456
        >>> finalize_telegram_id(-123456, TelegramEntityType.CHAT)
        -123456
    """
    # --- Валидация входного значения ---
    try:
        numeric_id = int(raw_id)
    except (TypeError, ValueError) as exc:
        raise TypeError(
            f"finalize_telegram_id: raw_id должен быть числом, получено "
            f"{type(raw_id).__name__!r} со значением {raw_id!r}"
        ) from exc

    if numeric_id == 0:
        raise ValueError("finalize_telegram_id: raw_id не может быть равен 0")

    # Абсолютное значение «цифровой» части ID (без каких-либо префиксов)
    abs_digits = _strip_channel_prefix(numeric_id)

    match entity_type:
        case TelegramEntityType.USER:
            return abs_digits

        case TelegramEntityType.CHAT:
            return -abs_digits

        case TelegramEntityType.CHANNEL:
            # Формула: "-100" + цифровая часть без префикса
            return int(f"-100{abs_digits}")

        case _:  # pragma: no cover — защита от будущих значений enum
            raise ValueError(f"Неизвестный entity_type: {entity_type!r}")


def _strip_channel_prefix(numeric_id: int) -> int:
    """
    Возвращает «чистую» цифровую часть ID канала/супергруппы/форума.

    Убирает ведущий '-100' (если он есть), затем возвращает abs.

    Examples:
        _strip_channel_prefix(-1002882674903) → 2882674903
        _strip_channel_prefix(2882674903)     → 2882674903
        _strip_channel_prefix(-456789)        → 456789
    """
    abs_id = abs(numeric_id)
    str_id = str(abs_id)

    # Если цифровая строка начинается с '100' и длина > 12 → это уже с префиксом
    if str_id.startswith("100") and len(str_id) > 12:
        return int(str_id[3:])

    return abs_id


def is_channel_id(raw_id: int) -> bool:
    """
    Эвристика: является ли ID идентификатором канала/супергруппы/форума.

    Считаем, что если abs(raw_id) > 1_000_000_000 — это Channel-тип.
    Обычные старые группы (Chat) имеют ID меньше 1 млрд.

    Используй только при неизвестном типе сущности (например, ручной ввод).
    """
    return abs(raw_id) > 1_000_000_000


# ---------------------------------------------------------------------------
# Вспомогательные утилиты
# ---------------------------------------------------------------------------

def sanitize_filename(value: str | None, max_length: int = 120) -> str:
    """
    Очищает строку от символов, недопустимых в имени файла (Windows + Unix).

    Заменяет  / \\ : * ? " < > |  на '_', обрезает до max_length.
    Никогда не возвращает пустую строку — fallback 'chat'.

    Args:
        value:      Исходная строка (может быть None).
        max_length: Максимальная длина результата.

    Returns:
        Очищенное имя файла.
    """
    if not value:
        return "chat"
    cleaned = re.sub(r'[\/\\:*?"<>|]+', "_", value).strip().strip(".")
    return (cleaned[:max_length] or "chat")


def is_image_path(path: str | Path) -> bool:
    """
    Проверяет, является ли путь изображением по расширению.

    Поддерживаемые форматы: jpg, jpeg, png, gif, bmp, webp.
    """
    return Path(path).suffix.lower() in {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}


def ensure_aware_utc(dt: datetime) -> datetime:
    """
    Гарантирует timezone-aware datetime в UTC.

    Если datetime наивный (tzinfo=None) — считаем UTC и добавляем tzinfo.
    Если уже tz-aware — конвертируем в UTC.

    Args:
        dt: Объект datetime (наивный или aware).

    Returns:
        timezone-aware datetime в UTC.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# DownloadTracker — инкрементальный режим парсинга
# ---------------------------------------------------------------------------

class DownloadTracker:
    """
    Отслеживает уже скачанные сообщения в текстовом файле downloaded.txt.

    Хранит по одной строке «t.me/<chat_id>/<message_id>» на каждое сообщение.
    При повторном запуске парсинга пропускает уже обработанные message_id.

    Используется в ParserService.collect_data() когда re_download=False.
    При re_download=True вызывать clear() перед стартом итерации.

    Args:
        output_dir: Корневая папка выхода (из CollectParams.output_dir).
        chat_title: Название чата (для папки; передаётся через sanitize_filename).
        chat_id:    Нормализованный ID чата.

    Example:
        tracker = DownloadTracker(params.output_dir, chat_title, chat_id)
        if not params.re_download and tracker.is_downloaded(message.id):
            continue
        tracker.mark_downloaded(message.id)
    """

    def __init__(self, output_dir: str, chat_title: str, chat_id: int) -> None:
        safe_title = sanitize_filename(chat_title)
        self._chat_id = chat_id
        self._dir = os.path.join(output_dir, safe_title)
        self._path = os.path.join(self._dir, "downloaded.txt")
        self._ids: Set[int] = set()
        self._load()

    # ── Внутренний загрузчик ───────────────────────────────────────

    def _load(self) -> None:
        """Читает downloaded.txt и наполняет self._ids."""
        if not os.path.exists(self._path):
            return
        try:
            with open(self._path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    # формат: «t.me/chatId/messageId» — берём последний сегмент
                    try:
                        self._ids.add(int(line.rsplit("/", 1)[-1]))
                    except ValueError:
                        pass
        except OSError as exc:
            logger.warning("DownloadTracker: не удалось прочитать %s: %s", self._path, exc)

    # ── Публичный API ──────────────────────────────────────────────

    def is_downloaded(self, message_id: int) -> bool:
        """Возвращает True если сообщение уже было скачано ранее."""
        return message_id in self._ids

    def mark_downloaded(self, message_id: int) -> None:
        """
        Помечает сообщение как скачанное (только в памяти).

        Файл НЕ пишется немедленно — вызывай save() по завершении итерации.
        Это критично: open/write/close на каждое сообщение блокирует asyncio
        event loop и является основной причиной 30-кратного замедления парсинга.
        """
        self._ids.add(message_id)

    def clear(self) -> None:
        """Сбрасывает трекер (режим re_download=True)."""
        self._ids.clear()
        if os.path.exists(self._path):
            try:
                os.remove(self._path)
            except OSError:
                pass

    def save(self) -> None:
        """Перезаписывает файл целиком (например, после очистки и восстановления)."""
        os.makedirs(self._dir, exist_ok=True)
        try:
            with open(self._path, "w", encoding="utf-8") as fh:
                for mid in sorted(self._ids):
                    fh.write(f"t.me/{self._chat_id}/{mid}\n")
        except OSError as exc:
            logger.warning("DownloadTracker: не удалось сохранить %s: %s", self._path, exc)

    @property
    def count(self) -> int:
        """Количество уже отслеживаемых сообщений."""
        return len(self._ids)


# ---------------------------------------------------------------------------

def format_file_size(size_bytes: int) -> str:
    """
    Форматирует размер файла в человекочитаемую строку.

    Examples:
        >>> format_file_size(1024)
        '1.0 KB'
        >>> format_file_size(1_048_576)
        '1.0 MB'
    """
    if size_bytes < 0:
        return "0 B"
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes //= 1024
    return f"{size_bytes:.1f} TB"
