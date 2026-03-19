"""
main.py — Точка входа Rozitta Parser

Единственная ответственность:
  1. Настроить логирование (до создания QApplication)
  2. Загрузить конфигурацию и валидировать её
  3. Открыть DBManager (гарантирует создание схемы БД при первом запуске)
  4. Создать QApplication и MainWindow
  5. Запустить event loop

Вся UI-логика вынесена в ui/main_window.py.
Классы воркеров живут в features/*/ui.py.

Порядок инициализации важен:
  setup_logging() → раньше всего (чтобы ловить ошибки импортов)
  QApplication()  → до создания любых QWidget
  DBManager()     → до create_main_window() (передаётся в окно)
"""

from __future__ import annotations

import logging
import os
import sys
import socket  # Добавили для патча

# ── ПАТЧ: Отключение IPv6 ──────────────────────────────────────────
# Ускоряет подключение к Telegram на 10-30 секунд, если IPv6 не работает.
# Мы подменяем стандартный метод получения адреса на версию только для IPv4.
orig_getaddrinfo = socket.getaddrinfo

def getaddrinfo_ipv4_only(*args, **kwargs):
    args = list(args)
    if len(args) > 3:
        args[3] = socket.AF_INET  # Принудительно используем IPv4
    return orig_getaddrinfo(*args, **kwargs)

socket.getaddrinfo = getaddrinfo_ipv4_only

# Заглушить DirectWrite-предупреждения о шрифтах — должно быть ДО QApplication
os.environ["QT_LOGGING_RULES"] = "qt.qpa.fonts=false"

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from config import AppConfig, load_config
from core.database import DBManager
from core.exceptions import ConfigError
from core.logger import setup_logging
from ui.main_window import create_main_window

logger = logging.getLogger(__name__)


def main() -> None:
    # ── 1. Логирование ────────────────────────────────────────────────
    # Обязательно ДО создания QApplication и любых импортов Qt-виджетов.
    setup_logging(level=logging.INFO, log_file="rozitta.log")
    logger.info("Rozitta Parser starting up")

    # ── 2. QApplication ───────────────────────────────────────────────
    app = QApplication(sys.argv)
    app.setApplicationName("Rozitta Parser")
    app.setApplicationVersion("3.3")
    app.setOrganizationName("Rozitta")

    # ── 3. Конфигурация ───────────────────────────────────────────────
    try:
        cfg: AppConfig = load_config()
        # Если api_id/hash не заданы — окно откроется на экране «Настройки»,
        # поэтому здесь НЕ вызываем cfg.validate() чтобы не крашиться при
        # первом запуске. Валидация происходит внутри MainWindow перед запуском
        # воркеров.
    except Exception as exc:
        logger.exception("Failed to load config")
        QMessageBox.critical(
            None,
            "Ошибка конфигурации",
            f"Не удалось загрузить config_modern.json:\n\n{exc}",
        )
        sys.exit(1)

    # ── 4. База данных ────────────────────────────────────────────────
    # Открываем DBManager заранее:
    #   - гарантирует создание схемы (WAL + индексы) до запуска UI
    #   - позволяет MainWindow читать статистику на старте без отдельного воркера
    #   - передаётся в create_main_window(cfg, db) — второй аргумент
    #
    # Воркеры (ParseWorker, ExportWorker) открывают собственные DBManager
    # в своих потоках. db здесь используется только для read-only запросов
    # из главного UI-потока.
    os.makedirs(cfg.output_dir, exist_ok=True)
    try:
        db = DBManager(str(cfg.db_path))
    except Exception as exc:
        logger.exception("Failed to open database: %s", cfg.db_path)
        QMessageBox.critical(
            None,
            "Ошибка базы данных",
            f"Не удалось открыть базу данных:\n{cfg.db_path}\n\n{exc}",
        )
        sys.exit(1)

    # ── 5. Главное окно ───────────────────────────────────────────────
    try:
        window = create_main_window(cfg, db)
        window.show()
        logger.info("MainWindow shown, entering Qt event loop")
        exit_code = app.exec()
    except Exception as exc:
        logger.exception("Unhandled exception in main window")
        QMessageBox.critical(
            None,
            "Критическая ошибка",
            f"Неожиданная ошибка при запуске:\n\n{exc}",
        )
        exit_code = 1
    finally:
        # Закрываем DBManager корректно при любом исходе
        try:
            db.close()
            logger.info("Database closed")
        except Exception:
            pass

    logger.info("Rozitta Parser exiting with code %d", exit_code)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
