"""
features/update_archive/worker.py — фоновый воркер обновления архива чата.

Шаг 1 (stub): эмитит прогресс-сообщения в журнал и через ~3 сек
возвращает тестовый отчёт. Реальная цепочка — Шаг 2.

Сигналы:
    log_message(str)      — строка в журнал операций
    progress(int)         — 0..100
    finished(object)      — dict отчёта
    error(str)            — критическая ошибка
    character_state(str)  — состояние персонажа Rozetta

Usage (MainWindow):
    worker = UpdateArchiveWorker(chat=chat, cfg=self._cfg)
    worker.log_message.connect(self._log.append_info, Qt.UniqueConnection)
    worker.progress.connect(self._update_progress, Qt.UniqueConnection)
    worker.character_state.connect(self._rozetta.set_state, Qt.UniqueConnection)
    worker.finished.connect(self._on_update_archive_finished, Qt.UniqueConnection)
    worker.error.connect(self._on_update_archive_error, Qt.UniqueConnection)
    self._start_worker(worker)
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any, Dict

from PySide6.QtCore import QThread, Signal

from config import AppConfig

logger = logging.getLogger(__name__)


class UpdateArchiveWorker(QThread):
    """
    QThread-воркер обновления архива чата.  # ── Update Archive stage 1 ──

    Шаг 1: stub-реализация. Через ~3 секунды эмитит тестовый отчёт.
    Шаг 2: заменит stub на реальную цепочку из 6 этапов
    (докачка -> новые медиа -> транскрибация -> импорт -> KB -> отчёт).
    """

    log_message      = Signal(str)
    progress         = Signal(int)
    finished         = Signal(object)   # dict отчёта
    error            = Signal(str)
    character_state  = Signal(str)

    def __init__(
        self,
        chat: Dict[str, Any],
        cfg: AppConfig,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._chat = chat
        self._cfg = cfg
        self._chat_title: str = chat.get("title", "?") or "?"

    def run(self) -> None:
        """Точка входа потока."""
        try:
            self._stub_run()
        except Exception as exc:
            logger.exception("UpdateArchiveWorker: stub error")
            self.error.emit(str(exc))
        finally:
            self.character_state.emit("idle")

    # ------------------------------------------------------------------
    # Stub-реализация (Шаг 1)
    # ------------------------------------------------------------------

    def _stub_run(self) -> None:
        """Тестовая цепочка: 6 шагов с паузами, тестовый отчёт."""
        t_start = time.perf_counter()

        self.character_state.emit("process")
        self.log_message.emit(
            f"\N{CYCLONE} Обновление архива: \u00ab{self._chat_title}\u00bb (тестовый режим)"
        )
        self.progress.emit(5)

        # Шаг 1: Докачка
        self.log_message.emit("Шаг 1/6: докачка новых сообщений\u2026")
        time.sleep(0.6)
        self.progress.emit(20)

        # Шаг 2: Определение новых медиа
        self.log_message.emit(
            "Шаг 2/6: определение новых медиа для транскрибации\u2026"
        )
        time.sleep(0.5)
        self.progress.emit(35)

        # Шаг 3: Транскрибация
        self.log_message.emit("Шаг 3/6: транскрибация через движок расшифровки\u2026")
        time.sleep(0.7)
        self.progress.emit(60)

        # Шаг 4: Импорт транскрипций
        self.log_message.emit("Шаг 4/6: импорт транскрипций в базу\u2026")
        time.sleep(0.4)
        self.progress.emit(75)

        # Шаг 5: Пересборка KB
        self.log_message.emit("Шаг 5/6: пересборка базы знаний\u2026")
        time.sleep(0.4)
        self.progress.emit(90)

        # Шаг 6: Отчёт
        self.log_message.emit("Шаг 6/6: формирование отчёта об обновлении\u2026")
        time.sleep(0.3)
        self.progress.emit(100)

        duration = time.perf_counter() - t_start

        report: Dict[str, Any] = {
            "chat_title":          self._chat_title,
            "updated_at":          datetime.now().isoformat(timespec="seconds"),
            "new_posts":           1,
            "new_comments":        46,
            "new_media":           3,
            "transcribed_videos":  1,
            "skipped":             0,
            "duration_sec":        round(duration, 2),
            "stub":                True,
        }

        self.log_message.emit("\N{WHITE HEAVY CHECK MARK} Тестовое обновление завершено (stub)")
        self.finished.emit(report)
