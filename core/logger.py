"""
core/logger.py — Настройка логирования Rozitta Parser

Предоставляет единую точку настройки: вызови setup_logging() один раз
в main.py — и все модули через logging.getLogger(__name__) сразу получат
форматированные логи в консоль и в файл.

Формат консоли (цветной, компактный):
    12:34:56 [INFO   ] features.parser.api  — Обработано 100 сообщений

Формат файла (полный, для разбора ошибок):
    2025-01-15 12:34:56.123 [INFO    ] features.parser.api:325 — Обработано 100 сообщений

Уровни:
    DEBUG    — детали внутри функций (обычно выключен)
    INFO     — нормальный ход работы (что видит пользователь)
    WARNING  — что-то пошло не так, но работа продолжается
    ERROR    — операция провалилась
    CRITICAL — приложение не может продолжать работу

Использование в модулях проекта:
    import logging
    logger = logging.getLogger(__name__)
    logger.info("Начинаем парсинг чата %d", chat_id)
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
import warnings
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Константы
# ---------------------------------------------------------------------------

DEFAULT_LOG_FILE    = "rozitta_parser.log"
DEFAULT_MAX_BYTES   = 5 * 1024 * 1024   # 5 MB на файл
DEFAULT_BACKUP_COUNT = 3                  # хранить 3 ротированных файла
ROOT_LOGGER_NAME    = "rozitta"          # корневой логгер проекта


# ---------------------------------------------------------------------------
# ANSI-коды для цветного вывода в консоль
# ---------------------------------------------------------------------------

_RESET   = "\033[0m"
_BOLD    = "\033[1m"

_LEVEL_COLORS: dict[int, str] = {
    logging.DEBUG:    "\033[36m",    # cyan
    logging.INFO:     "\033[32m",    # green
    logging.WARNING:  "\033[33m",    # yellow
    logging.ERROR:    "\033[31m",    # red
    logging.CRITICAL: "\033[35m",    # magenta
}


# ---------------------------------------------------------------------------
# Кастомные форматтеры
# ---------------------------------------------------------------------------

class _ColorConsoleFormatter(logging.Formatter):
    """
    Форматтер для консоли с ANSI-цветами.

    Цвет отражает уровень: INFO→зелёный, WARNING→жёлтый, ERROR→красный.
    На Windows цвета работают начиная с Windows 10 (ANSI включён по умолчанию).
    Если поток не является TTY — цвета отключаются автоматически.
    """

    _FMT = "{color}{time} [{level:<7}]{reset} {name:<30}— {message}"

    def __init__(self, use_color: bool = True) -> None:
        super().__init__()
        self.use_color = use_color

    def format(self, record: logging.LogRecord) -> str:
        color = _LEVEL_COLORS.get(record.levelno, "") if self.use_color else ""
        reset = _RESET if self.use_color else ""

        # Укорачиваем имя логгера: убираем ведущий 'rozitta.'
        short_name = record.name.removeprefix(f"{ROOT_LOGGER_NAME}.")
        if not short_name:
            short_name = ROOT_LOGGER_NAME

        return self._FMT.format(
            color=color,
            time=self.formatTime(record, datefmt="%H:%M:%S"),
            level=record.levelname,
            reset=reset,
            name=short_name,
            message=record.getMessage(),
        )


class _FileFormatter(logging.Formatter):
    """
    Форматтер для файлового лога — полный, без цветов.

    Включает: дату+время с миллисекундами, уровень, имя модуля,
    номер строки и текст сообщения. При наличии исключения —
    traceback добавляется следующей строкой.
    """

    def __init__(self) -> None:
        super().__init__(
            fmt="%(asctime)s.%(msecs)03d [%(levelname)-8s] %(name)s:%(lineno)d — %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )


# ---------------------------------------------------------------------------
# Основная функция настройки
# ---------------------------------------------------------------------------

def setup_logging(
    level:        int | str         = logging.INFO,
    log_file:     Optional[str]     = DEFAULT_LOG_FILE,
    file_level:   int | str         = logging.DEBUG,
    console:      bool              = True,
    use_color:    bool              = True,
    log_dir:      Optional[str]     = None,
    max_bytes:    int               = DEFAULT_MAX_BYTES,
    backup_count: int               = DEFAULT_BACKUP_COUNT,
) -> logging.Logger:
    """
    Инициализирует систему логирования Rozitta Parser.

    Вызывай ОДИН РАЗ в самом начале main.py, до создания QApplication.
    После этого все модули проекта через logging.getLogger(__name__)
    автоматически используют настроенные хэндлеры.

    Args:
        level:        Уровень для консоли (INFO по умолчанию).
        log_file:     Имя файла лога. None — отключить запись в файл.
        file_level:   Уровень для файла (DEBUG — записывает всё).
        console:      Выводить ли логи в stderr.
        use_color:    Использовать ANSI-цвета в консоли.
                      Автоматически отключается если stderr не TTY.
        log_dir:      Папка для лог-файлов. По умолчанию — рядом со скриптом.
        max_bytes:    Максимальный размер лог-файла до ротации (байты).
        backup_count: Количество хранимых ротированных файлов.

    Returns:
        Корневой логгер проекта ('rozitta').

    Example:
        # main.py
        from core.logger import setup_logging
        setup_logging(level=logging.INFO, log_file="rozitta.log")
    """
    root_logger = logging.getLogger(ROOT_LOGGER_NAME)

    # Не добавляем хэндлеры повторно (идемпотентно)
    if root_logger.handlers:
        return root_logger

    numeric_level = _to_int_level(level)
    root_logger.setLevel(logging.DEBUG)   # корневой = всё; хэндлеры фильтруют

    # --- Консольный хэндлер ---
    if console:
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setLevel(numeric_level)

        # Цвета только если stderr — настоящий терминал
        is_tty = hasattr(sys.stderr, "isatty") and sys.stderr.isatty()
        console_handler.setFormatter(
            _ColorConsoleFormatter(use_color=use_color and is_tty)
        )
        root_logger.addHandler(console_handler)

    # --- Файловый хэндлер (RotatingFileHandler) ---
    if log_file:
        log_path = _resolve_log_path(log_file, log_dir)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.handlers.RotatingFileHandler(
            filename=str(log_path),
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
            delay=False,
        )
        file_handler.setLevel(_to_int_level(file_level))
        file_handler.setFormatter(_FileFormatter())
        root_logger.addHandler(file_handler)

        # Направляем ВСЕ логгеры (telethon, asyncio, Qt, py.warnings)
        # в тот же файл — они не являются дочерними к "rozitta",
        # поэтому добавляем file_handler к настоящему Python root-логгеру.
        py_root = logging.getLogger()
        py_root.setLevel(logging.DEBUG)
        py_root.addHandler(file_handler)

        # warnings.warn() → logging ("py.warnings" логгер → файл)
        logging.captureWarnings(True)

        root_logger.info(
            "Логирование запущено. Файл: %s (уровень: %s)",
            log_path,
            logging.getLevelName(_to_int_level(file_level)),
        )

    return root_logger


# ---------------------------------------------------------------------------
# Удобные хелперы
# ---------------------------------------------------------------------------

def get_logger(name: str) -> logging.Logger:
    """
    Возвращает дочерний логгер проекта.

    Эквивалент logging.getLogger(f"rozitta.{name}"), но короче.
    Используй в модулях, где __name__ не содержит 'rozitta':

        from core.logger import get_logger
        logger = get_logger("my_module")

    Обычно достаточно:
        import logging
        logger = logging.getLogger(__name__)

    Args:
        name: Имя подмодуля (без префикса 'rozitta.').

    Returns:
        logging.Logger с именем 'rozitta.{name}'.
    """
    return logging.getLogger(f"{ROOT_LOGGER_NAME}.{name}")


def set_level(level: int | str, handler_type: str = "console") -> None:
    """
    Динамически изменяет уровень логирования во время работы.

    Удобно для кнопки «Verbose mode» в UI: пользователь включает DEBUG
    и сразу видит подробные логи без перезапуска.

    Args:
        level:        Новый уровень (например, logging.DEBUG или "DEBUG").
        handler_type: "console" — только консоль,
                      "file"    — только файл,
                      "all"     — все хэндлеры.
    """
    root_logger = logging.getLogger(ROOT_LOGGER_NAME)
    numeric = _to_int_level(level)

    for handler in root_logger.handlers:
        if handler_type == "all":
            handler.setLevel(numeric)
        elif handler_type == "console" and isinstance(handler, logging.StreamHandler) \
                and not isinstance(handler, logging.FileHandler):
            handler.setLevel(numeric)
        elif handler_type == "file" and isinstance(handler, logging.FileHandler):
            handler.setLevel(numeric)


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------

def _to_int_level(level: int | str) -> int:
    """Приводит уровень лога к int (принимает строку или int)."""
    if isinstance(level, int):
        return level
    numeric = logging.getLevelName(level.upper())
    if not isinstance(numeric, int):
        raise ValueError(
            f"Неизвестный уровень логирования: {level!r}. "
            f"Допустимые: DEBUG, INFO, WARNING, ERROR, CRITICAL."
        )
    return numeric


def _resolve_log_path(log_file: str, log_dir: Optional[str]) -> Path:
    """Возвращает абсолютный Path для лог-файла."""
    path = Path(log_file)
    if log_dir:
        return Path(log_dir) / path.name
    if path.is_absolute():
        return path
    # По умолчанию — в рабочей директории запуска
    return Path.cwd() / path
