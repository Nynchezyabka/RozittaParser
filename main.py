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
from pathlib import Path


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

def _ensure_runtime_workdir() -> None:
    """
    Для frozen-сборок задаёт предсказуемую рабочую папку в HOME.

    На macOS запуск через Finder часто стартует из "/" (или translocation path),
    из-за чего относительные пути вида "output" становятся недоступны для записи.
    """
    if not getattr(sys, "frozen", False):
        return

    app_workdir = Path.home() / "RozittaParser"
    app_workdir.mkdir(parents=True, exist_ok=True)
    os.chdir(app_workdir)
    logger.info("Runtime working directory: %s", app_workdir)

def _resolve_icon_path() -> str | None:
    """Ищет иконку приложения в наиболее вероятных местах (dev/frozen)."""
    roots = [Path(__file__).parent]
    if getattr(sys, "frozen", False):
        roots.extend([
            Path(sys.executable).resolve().parent,          # .../Contents/MacOS
            Path(sys.executable).resolve().parents[1],      # .../Contents
            Path(sys.executable).resolve().parents[1] / "Resources",  # .../Contents/Resources
        ])

    candidates = (
        Path("assets/rozitta_idle.icns"),
        Path("assets/rozitta_idle.ico"),
        Path("assets/rozitta_idle.png"),
        Path("rozitta_idle.icns"),
        Path("rozitta_idle.ico"),
        Path("rozitta_idle.png"),
    )
    for root in roots:
        for rel in candidates:
            p = (root / rel).resolve()
            if p.exists():
                return str(p)
    return None

def main() -> None:
    # ── 1. Логирование ────────────────────────────────────────────────
    # Обязательно ДО создания QApplication и любых импортов Qt-виджетов.
    # В frozen-сборке сначала переводим cwd в writable-папку, иначе setup_logging
    # может попытаться создать /rozitta.log и упасть при запуске из Finder.
    _ensure_runtime_workdir()
    # setup_logging обязательно до создания QApplication и UI.
    setup_logging(level=logging.INFO, log_file="rozitta.log")
    if getattr(sys, "frozen", False):
        logger.info("Runtime working directory: %s", os.getcwd())
    logger.info("Rozitta Parser starting up")

    # ── 2. QApplication ───────────────────────────────────────────────
    app = QApplication(sys.argv)
    app.setApplicationName("Rozitta Parser")
    app.setApplicationVersion("3.3")
    app.setOrganizationName("Rozitta")
    icon_path = _resolve_icon_path()
    if icon_path:
        app.setWindowIcon(QIcon(icon_path))
        logger.info("Application icon loaded: %s", icon_path)
    else:
        logger.warning("Application icon not found")

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
