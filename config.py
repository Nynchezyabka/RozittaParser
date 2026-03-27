"""
config.py — Конфигурация Rozitta Parser (корень проекта)

Заменяет разрозненные хардкод-константы из backend.py и frontend_modern.py.

Содержит:
- Константы приложения (магические числа → именованные)
- Датакласс AppConfig — полная конфигурация сессии
- load_config() / save_config() — чтение/запись config_modern.json
  (обратная совместимость: формат файла не изменился)

Использование:

    # Загрузка при старте (main.py):
    from config import load_config, AppConfig
    cfg = load_config()           # читает config_modern.json
    print(cfg.api_id)             # "12345678"

    # В features/auth/api.py:
    from config import cfg        # синглтон, загруженный при старте
    client = TelegramClient(cfg.session_name, int(cfg.api_id), cfg.api_hash)

    # Сохранение после изменения в UI:
    from config import save_config
    cfg.days = 90
    save_config(cfg)
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional

from core.exceptions import ConfigError

logger = logging.getLogger(__name__)


# ==============================================================================
# Константы приложения
# ==============================================================================

# --- Файлы ---
CONFIG_FILE   = "config_modern.json"        # хранит пользовательские настройки
SESSION_NAME  = "telegram_session_modern"   # имя файла Telethon-сессии (без .session)
DB_FILENAME   = "telegram_archive.db"       # имя файла SQLite в output_dir
LOG_FILENAME  = "rozitta_parser.log"        # файл логов

# --- Директории ---
MEDIA_FOLDER_NAME     = "media"             # подпапка для медиафайлов
DOCUMENTS_FOLDER_NAME = "documents"         # (зарезервировано для v4.0)

# --- Парсинг ---
DAYS_LIMIT_ALL_TIME     = 365   # days >= этого значения → «за всё время»
DEFAULT_DAYS_LIMIT      = 30    # значение слайдера по умолчанию
MAX_COMMENT_LIMIT       = 1000  # максимум комментариев на пост
MAX_USER_STATS_LIMIT    = 50    # топ активных пользователей
MESSAGES_LOG_INTERVAL   = 100   # логировать каждые N сообщений
FORUM_TOPICS_PAGE_SIZE  = 100   # количество топиков за один запрос
MERGE_TIME_DELTA        = 60    # максимальный интервал между сообщениями одного автора для склейки (сек)

# --- Медиа ---
IMAGE_EXTENSIONS: frozenset[str] = frozenset({
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"
})

# --- DOCX ---
DOCX_IMAGE_WIDTH_INCHES      = 4.5     # ширина вставляемых изображений
DOCX_IMAGE_WIDTH_COMMENT_INCHES = 4.0  # ширина изображений в комментариях
DOCX_SEPARATOR_LENGTH        = 60      # длина разделителя "_" * N

# --- Валидные режимы разбивки DOCX ---
VALID_SPLIT_MODES: tuple[str, ...] = ("none", "day", "month", "post")

# --- STT (faster-whisper) ---
STT_MODEL_DEFAULT:    str = "small"   # tiny | base | small | medium | large-v3
STT_LANGUAGE_DEFAULT: str = "ru"      # ISO 639-1 код или "" для автоопределения
VALID_STT_MODELS: tuple[str, ...] = ("tiny", "base", "small", "medium", "large-v3")

# --- Валидные типы медиа (внутренние ключи, не UI-текст) ---
VALID_MEDIA_TYPES: tuple[str, ...] = (
    "photo", "video", "videomessage", "voice", "file"
)


# ==============================================================================
# Датакласс конфигурации
# ==============================================================================

@dataclass
class AppConfig:
    """
    Полная конфигурация сессии Rozitta Parser.

    Все поля соответствуют ключам в config_modern.json для
    обратной совместимости с существующим frontend_modern.py.

    Attributes:
        api_id:        Telegram API ID (строка — как приходит из UI).
        api_hash:      Telegram API Hash.
        phone:         Номер телефона в формате +79991234567.
        days:          Глубина парсинга в днях (>= DAYS_LIMIT_ALL_TIME → всё время).
        media_filter:  Список активных типов медиа (UI-текст: "Фото", "Видео"…).
        comments:      Скачивать ли комментарии к постам канала.
        split_mode:    Режим разбивки DOCX: "none" | "day" | "month" | "post".
        output_dir:    Папка для сохранения результатов (не хранится в JSON).
        session_name:  Имя Telethon-сессии (не хранится в JSON).
    """

    api_id:       str        = ""
    api_hash:     str        = ""
    phone:        str        = ""
    days:         int        = DEFAULT_DAYS_LIMIT
    media_filter: List[str]  = field(default_factory=lambda: [
        "Фото", "Видео", "Кружочки", "Голосовые", "Документы"
    ])
    comments:     bool       = False
    split_mode:   str        = "none"
    stt_model:    str        = field(default=STT_MODEL_DEFAULT)
    stt_language: str        = field(default=STT_LANGUAGE_DEFAULT)

    # Поля, не сохраняемые в JSON (только runtime)
    output_dir:   str        = field(default="output", repr=False)
    session_name: str        = field(default=SESSION_NAME, repr=False)

    # Прокси (SOCKS5 / MTProto) — опционально
    proxy_enabled: bool      = False
    proxy_type:    str       = "socks5"    # "socks5" | "mtproto"
    proxy_host:    str       = "127.0.0.1"
    proxy_port:    int       = 9050
    proxy_secret:  str       = ""          # только для MTProto

    # ------------------------------------------------------------------
    # Свойства
    # ------------------------------------------------------------------

    @property
    def api_id_int(self) -> Optional[int]:
        """
        Возвращает api_id как int или None если поле пустое / не число.

        Используй в TelegramClient(session, cfg.api_id_int, cfg.api_hash).
        """
        try:
            return int(self.api_id) if self.api_id else None
        except (ValueError, TypeError):
            return None

    @property
    def is_all_time(self) -> bool:
        """True если нужно парсить за всё время (days >= DAYS_LIMIT_ALL_TIME)."""
        return self.days >= DAYS_LIMIT_ALL_TIME

    @property
    def db_path(self) -> str:
        """Полный путь к файлу БД в output_dir."""
        return os.path.join(self.output_dir, DB_FILENAME)

    @property
    def session_path(self) -> str:
        """Полный путь к файлу Telethon-сессии."""
        return os.path.abspath(self.session_name)

    # ------------------------------------------------------------------
    # Валидация
    # ------------------------------------------------------------------

    def validate(self) -> None:
        """
        Проверяет, что обязательные поля заполнены корректно.

        Raises:
            ConfigError: если api_id отсутствует, не является числом,
                         или api_hash пустой.
        """
        if not self.api_id or not self.api_id.strip():
            raise ConfigError(
                "API ID не указан. Получите его на https://my.telegram.org"
            )

        if self.api_id_int is None:
            raise ConfigError(
                f"API ID должен быть числом, получено: {self.api_id!r}"
            )

        if not self.api_hash or not self.api_hash.strip():
            raise ConfigError(
                "API Hash не указан. Получите его на https://my.telegram.org"
            )

        if self.split_mode not in VALID_SPLIT_MODES:
            raise ConfigError(
                f"Неверный split_mode: {self.split_mode!r}. "
                f"Допустимые: {VALID_SPLIT_MODES}"
            )


# ==============================================================================
# Загрузка / сохранение
# ==============================================================================

def load_config(path: str = CONFIG_FILE) -> AppConfig:
    """
    Читает config_modern.json и возвращает AppConfig.

    Если файл не существует или повреждён — возвращает AppConfig с дефолтами
    (не бросает исключение, чтобы первый запуск работал без конфига).

    Формат файла (обратная совместимость с frontend_modern.py):
        {
            "api_id": "12345678",
            "api_hash": "abcdef1234567890abcdef1234567890",
            "phone": "+79991234567",
            "days": 30,
            "media_filter": ["Фото", "Видео"],
            "comments": false,
            "split_mode": "none"
        }

    Args:
        path: Путь к файлу конфигурации.

    Returns:
        Заполненный AppConfig (с дефолтами для отсутствующих ключей).
    """
    if not os.path.exists(path):
        logger.debug("config.py: файл %s не найден, используем дефолты", path)
        return AppConfig()

    try:
        with open(path, encoding="utf-8") as f:
            data: dict = json.load(f)

        cfg = AppConfig(
            api_id        = str(data.get("api_id", "")),
            api_hash      = str(data.get("api_hash", "")),
            phone         = str(data.get("phone", "")),
            days          = int(data.get("days", DEFAULT_DAYS_LIMIT)),
            media_filter  = list(data.get("media_filter", ["Фото", "Видео", "Кружочки", "Голосовые", "Документы"])),
            comments      = bool(data.get("comments", False)),
            split_mode    = str(data.get("split_mode", "none")),
            stt_model     = str(data.get("stt_model", STT_MODEL_DEFAULT)),
            stt_language  = str(data.get("stt_language", STT_LANGUAGE_DEFAULT)),
            proxy_enabled = bool(data.get("proxy_enabled", False)),
            proxy_type    = str(data.get("proxy_type", "socks5")),
            proxy_host    = str(data.get("proxy_host", "127.0.0.1")),
            proxy_port    = int(data.get("proxy_port", 9050)),
            proxy_secret  = str(data.get("proxy_secret", "")),
        )

        logger.debug("config.py: конфиг загружен из %s", path)
        return cfg

    except json.JSONDecodeError as exc:
        logger.warning(
            "config.py: файл %s повреждён (%s). Используем дефолты.", path, exc
        )
        return AppConfig()

    except Exception as exc:
        logger.warning("config.py: ошибка загрузки конфига (%s). Дефолты.", exc)
        return AppConfig()


def save_config(cfg: AppConfig, path: str = CONFIG_FILE) -> None:
    """
    Сохраняет AppConfig в config_modern.json.

    Сохраняет ТОЛЬКО поля, соответствующие JSON-схеме (без output_dir,
    session_name и других runtime-полей).

    Args:
        cfg:  Объект конфигурации для сохранения.
        path: Путь к файлу конфигурации.

    Raises:
        ConfigError: если не удалось записать файл (нет прав, диск полон).
    """
    # Только сериализуемые поля (исключаем runtime-поля)
    data = {
        "api_id":        cfg.api_id,
        "api_hash":      cfg.api_hash,
        "phone":         cfg.phone,
        "days":          cfg.days,
        "media_filter":  cfg.media_filter,
        "comments":      cfg.comments,
        "split_mode":    cfg.split_mode,
        "stt_model":     cfg.stt_model,
        "stt_language":  cfg.stt_language,
        "proxy_enabled": cfg.proxy_enabled,
        "proxy_type":    cfg.proxy_type,
        "proxy_host":    cfg.proxy_host,
        "proxy_port":    cfg.proxy_port,
        "proxy_secret":  cfg.proxy_secret,
    }

    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        logger.debug("config.py: конфиг сохранён в %s", path)

    except OSError as exc:
        raise ConfigError(f"Не удалось сохранить конфиг в {path}: {exc}") from exc
