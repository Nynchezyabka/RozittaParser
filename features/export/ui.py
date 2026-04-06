"""
features/export/ui.py — ExportWorker: QThread-обёртка над DocxGenerator

Запускается автоматически после успешного ParseWorker.finished
(или вручную, если данные уже есть в БД).

Особенности:
    - python-docx синхронный → НЕ нужен asyncio event loop
    - DBManager открывается внутри воркера (отдельный поток = отдельное соединение)
    - Принимает CollectResult от ParseWorker (chat_id, chat_title, period_label)

Сигналы:
    log_message(str)       — строка лога
    export_complete(list)  — List[str] путей к созданным DOCX-файлам
    error(str)             — критическая ошибка

Пример использования (в MainWindow):
    def _on_parse_finished(self, result: CollectResult):
        if not result or not result.success:
            return
        export_params = ExportParams(
            chat_id          = result.chat_id,
            chat_title       = result.chat_title,
            period_label     = result.period_label,
            split_mode       = cfg.split_mode,
            topic_id         = selected_topic_id,
            user_id          = selected_user_id,
            include_comments = cfg.comments,
            output_dir       = str(cfg.output_dir),
            db_path          = str(cfg.db_path),
        )
        self._export_worker = ExportWorker(export_params)
        self._export_worker.log_message.connect(self.append_log)
        self._export_worker.export_complete.connect(self._on_export_complete)
        self._export_worker.error.connect(self._on_error)
        self._export_worker.start()
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from PySide6.QtCore import QThread, Signal

from core.database import DBManager
from core.exceptions import DocxGenerationError, EmptyDataError
from features.export.generator import DocxGenerator, JsonGenerator, MarkdownGenerator, HtmlGenerator

logger = logging.getLogger(__name__)

_LogCallback = Callable[[str], None]


# ==============================================================================
# ExportParams
# ==============================================================================

@dataclass
class ExportParams:
    """
    Параметры одного запуска ExportWorker.

    Передаётся из MainWindow в ExportWorker.
    Отделяет «что экспортировать» от логики воркера.

    Attributes:
        chat_id:          Нормализованный ID чата (из CollectResult).
        chat_title:       Название чата (из CollectResult или БД).
        period_label:     Метка периода для имени файла (из CollectResult).
        split_mode:       "none" | "day" | "month" | "post".
        topic_id:         Фильтр по топику форума (None = весь чат).
        user_id:          Фильтр по пользователю (None = все).
        include_comments: Включать ли комментарии.
        output_dir:       Папка для сохранения.
        db_path:          Путь к SQLite-файлу с сообщениями.
    """
    chat_id:          int
    chat_title:       str
    period_label:     str                 = "fullchat"
    split_mode:       str                 = "none"
    topic_id:         Optional[int]       = None
    # user_id: устаревший однозначный фильтр (backward compat).
    user_id:          Optional[int]       = None
    # user_ids: список выбранных участников (поддерживает несколько).
    user_ids:         Optional[List[int]] = None
    # user_filter_mode:
    #   "messages-only" → экспортировать только сообщения выбранных участников
    #   "all-threads"   → экспортировать целые цепочки ответов с их участием
    user_filter_mode: str                 = "messages-only"
    include_comments: bool                = False
    output_dir:       str                 = "output"
    db_path:          str                 = "output/telegram_archive.db"
    export_formats:   list                = None  # ["docx"] | ["json"] | ["docx","json","html","md"]
    ai_split:         bool                = False  # разбивать MD/JSON/HTML на чанки
    ai_split_chunk_words: int             = 300_000

    def __post_init__(self):
        if self.export_formats is None:
            self.export_formats = ["docx"]
        # Backward compat: заполнить user_id из user_ids при single-user messages-only
        if self.user_id is None and self.user_ids and self.user_filter_mode == "messages-only":
            if len(self.user_ids) == 1:
                self.user_id = self.user_ids[0]


# ==============================================================================
# ExportWorker
# ==============================================================================

class ExportWorker(QThread):
    """
    QThread для генерации DOCX из сохранённых сообщений.

    Читает данные из SQLite (уже заполненной ParseWorker),
    генерирует DOCX через DocxGenerator и эмитит пути к файлам.

    Args:
        params: ExportParams — параметры экспорта.

    Example:
        worker = ExportWorker(export_params)
        worker.log_message.connect(self.append_log)
        worker.export_complete.connect(self._on_export_complete)
        worker.error.connect(self._on_error)
        worker.start()
    """

    # ── Сигналы ──────────────────────────────────────────────────────────────
    log_message    = Signal(str)
    export_complete = Signal(list)  # List[str] — пути к DOCX файлам
    error          = Signal(str)
    character_state = Signal(str)   # TD-5: "idle"|"working"|"success"|"error"

    def __init__(self, params: ExportParams, parent=None) -> None:
        super().__init__(parent)
        self._params     = params
        self._is_running = True

    # ------------------------------------------------------------------
    # Публичные методы
    # ------------------------------------------------------------------

    def stop(self) -> None:
        """Останавливает воркер. python-docx не прерывается, ждём завершения."""
        self._is_running = False
        self.quit()
        self.wait(5000)  # docx-генерация может занять несколько секунд

    # ------------------------------------------------------------------
    # QThread.run() — синхронный, без asyncio
    # ------------------------------------------------------------------

    def run(self) -> None:
        """
        Основная точка входа. Нет event loop — DocxGenerator синхронный.

        Поток выполнения:
            1. Открыть DBManager (отдельное соединение для этого потока)
            2. Создать DocxGenerator
            3. Вызвать generate()
            4. Эмитить export_complete(files)
        """
        p = self._params
        formats = p.export_formats or ["docx"]
        logger.info(
            "ExportWorker: started chat_id=%s split=%s topic=%s formats=%s user_ids=%s mode=%s",
            p.chat_id, p.split_mode, p.topic_id, formats, p.user_ids, p.user_filter_mode,
        )

        # Логируем фильтр участников если задан
        if p.user_ids:
            mode_label = "цепочки с участием" if p.user_filter_mode == "all-threads" else "только сообщения"
            self._log(f"👤 Фильтр участников ({mode_label}): {len(p.user_ids)} чел.")

        self._log(f"📄 Экспорт (режим: {p.split_mode}, форматы: {', '.join(f.upper() for f in formats)})...")
        self._log(f"🗄️ Читаем из БД: {p.db_path}")

        all_files: list[str] = []

        try:
            with DBManager(p.db_path) as db:

                # ── DOCX ──────────────────────────────────────────────────
                if "docx" in formats:
                    gen = DocxGenerator(db=db, output_dir=p.output_dir)
                    files = gen.generate(
                        chat_id          = p.chat_id,
                        chat_title       = p.chat_title,
                        split_mode       = p.split_mode,
                        topic_id         = p.topic_id,
                        user_id          = p.user_id,
                        user_ids         = p.user_ids,
                        user_filter_mode = p.user_filter_mode,
                        include_comments = p.include_comments,
                        period_label     = p.period_label,
                        log              = self._log,
                    )
                    all_files.extend(files)

                # ── JSON ──────────────────────────────────────────────────
                if "json" in formats:
                    jgen = JsonGenerator(db=db, output_dir=p.output_dir)
                    json_paths = jgen.generate(
                        chat_id              = p.chat_id,
                        chat_title           = p.chat_title,
                        topic_id             = p.topic_id,
                        user_id              = p.user_id,
                        user_ids             = p.user_ids,
                        user_filter_mode     = p.user_filter_mode,
                        include_comments     = p.include_comments,
                        ai_split             = p.ai_split,
                        period_label         = p.period_label,
                        log                  = self._log,
                        ai_split_chunk_words = p.ai_split_chunk_words,
                    )
                    all_files.extend(json_paths)

                # ── Markdown ───────────────────────────────────────────────
                if "md" in formats:
                    mdgen = MarkdownGenerator(db=db, output_dir=p.output_dir)
                    md_paths = mdgen.generate(
                        chat_id              = p.chat_id,
                        chat_title           = p.chat_title,
                        topic_id             = p.topic_id,
                        user_id              = p.user_id,
                        user_ids             = p.user_ids,
                        user_filter_mode     = p.user_filter_mode,
                        include_comments     = p.include_comments,
                        ai_split             = p.ai_split,
                        period_label         = p.period_label,
                        ai_split_chunk_words = p.ai_split_chunk_words,
                        log                  = self._log,
                    )
                    all_files.extend(md_paths)

                # ── HTML ──────────────────────────────────────────────────
                if "html" in formats:
                    hgen = HtmlGenerator(db=db, output_dir=p.output_dir)
                    html_paths = hgen.generate(
                        chat_id              = p.chat_id,
                        chat_title           = p.chat_title,
                        topic_id             = p.topic_id,
                        user_id              = p.user_id,
                        user_ids             = p.user_ids,
                        user_filter_mode     = p.user_filter_mode,
                        include_comments     = p.include_comments,
                        ai_split             = p.ai_split,
                        period_label         = p.period_label,
                        log                  = self._log,
                    )
                    all_files.extend(html_paths)
    
            if self._is_running:
                self._log(f"🎉 Готово! Создано файлов: {len(all_files)}")
                for f in all_files:
                    import os
                    self._log(f"   📄 {os.path.basename(f)}")
                logger.info("ExportWorker: emit export_complete (%d файлов)", len(all_files))
                self.export_complete.emit(all_files)

        except EmptyDataError as exc:
            msg = f"⚠️ Нет данных для экспорта: {exc}"
            self._log(msg)
            logger.warning("ExportWorker: EmptyDataError: %s", exc)
            if self._is_running:
                self.export_complete.emit([])

        except DocxGenerationError as exc:
            msg = f"❌ Ошибка создания DOCX: {exc}"
            self._log(msg)
            logger.error("ExportWorker: DocxGenerationError: %s", exc)
            if self._is_running:
                self.error.emit(msg)

        except Exception as exc:
            msg = f"❌ Неожиданная ошибка: {exc}"
            self._log(msg)
            logger.exception("ExportWorker: run() error")
            if self._is_running:
                self.error.emit(msg)

        finally:
            logger.info("ExportWorker: finished")

    # ------------------------------------------------------------------
    # Вспомогательное
    # ------------------------------------------------------------------

    def _log(self, msg: str) -> None:
        if self._is_running:
            self.log_message.emit(msg)
        logger.debug("ExportWorker: %s", msg)