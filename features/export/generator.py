"""
features/export/generator.py — Генерация DOCX из сохранённых сообщений

Читает данные из DBManager и создаёт DOCX-файлы через python-docx.
Все XML-трюки (закладки, ссылки) делегированы в features/export/xml_magic.py.

Поддерживаемые режимы (split_mode):
    "none"  — один файл со всеми сообщениями
    "day"   — по одному файлу на каждый день
    "month" — по одному файлу на каждый месяц
    "post"  — по одному файлу на каждый пост (+ комментарии если include_comments)

Нет Qt-зависимостей. Нет Telethon-зависимостей.
Весь код — синхронный (python-docx не поддерживает async).

Пример использования (в ExportWorker.run()):
    with DBManager(cfg.db_path) as db:
        gen = DocxGenerator(db, output_dir=params.output_dir)
        files = gen.generate(
            chat_id          = result.chat_id,
            chat_title       = result.chat_title,
            split_mode       = params.split_mode,
            topic_id         = params.topic_id,
            user_id          = params.user_id,
            include_comments = params.download_comments,
            period_label     = result.period_label,
            log              = self.log_message.emit,
        )
"""

from __future__ import annotations

import json
import logging
import os
from collections import defaultdict
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt, RGBColor

from config import VALID_SPLIT_MODES
from core.database import DBManager
from core.exceptions import DocxGenerationError, EmptyDataError
from core.utils import sanitize_filename, is_image_path
from features.export import xml_magic

logger = logging.getLogger(__name__)

_LogCallback = Callable[[str], None]

# Ширина изображений в документе (дюймы)
_IMAGE_WIDTH_INCHES = 4.5
# Отступ комментариев (дюймы)
_COMMENT_INDENT_INCHES = 0.3
# Линия-разделитель между сообщениями
_SEPARATOR = "─" * 60


# ==============================================================================
# Индексы колонок из DBManager.get_messages() / get_post_with_comments()
# ==============================================================================
# SELECT id, chat_id, message_id, topic_id, user_id, username,
#        date, text, media_path, file_type, file_size,
#        reply_to_msg_id, post_id, is_comment, linked_chat_id
# FROM messages
#
# (нумерация с 0, соответствует core/database.py)
_COL_ID            = 0
_COL_CHAT_ID       = 1
_COL_MESSAGE_ID    = 2
_COL_TOPIC_ID      = 3
_COL_USER_ID       = 4
_COL_USERNAME      = 5
_COL_DATE          = 6
_COL_TEXT          = 7
_COL_MEDIA_PATH    = 8
_COL_FILE_TYPE     = 9
_COL_FILE_SIZE     = 10
_COL_REPLY_TO      = 11
_COL_POST_ID       = 12
_COL_IS_COMMENT    = 13
_COL_LINKED_CHAT   = 14


# ==============================================================================
# DocxGenerator
# ==============================================================================

class DocxGenerator:
    """
    Генератор DOCX-документов из архива Telegram.

    Читает строки из DBManager (сохранённые через ParserService),
    форматирует их в Word-документы со структурой, закладками и ссылками.

    Args:
        db:         Открытый DBManager (контекстный менеджер управляет им снаружи).
        output_dir: Корневая папка для сохранения DOCX-файлов.
    """

    def __init__(self, db: DBManager, output_dir: str = "output") -> None:
        self._db         = db
        self._output_dir = output_dir
        self._log: _LogCallback = logger.info

        # Текущий контекст (устанавливается в generate() для _build_path)
        self._chat_title:  str = "chat"
        self._period_label: str = "fullchat"
        # Транскрипции: {message_id: text} — загружаются в generate()
        self._transcriptions: Dict[int, str] = {}

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    def generate(
        self,
        chat_id:          int,
        chat_title:       str        = "",
        split_mode:       str        = "none",
        topic_id:         Optional[int] = None,
        user_id:          Optional[int] = None,
        include_comments: bool          = False,
        period_label:     str           = "fullchat",
        log:              _LogCallback  = None,
    ) -> List[str]:
        """
        Главный метод: генерирует DOCX в соответствии с split_mode.

        Args:
            chat_id:          Нормализованный ID чата (из CollectResult.chat_id).
            chat_title:       Название чата (для имён файлов и заголовков).
            split_mode:       "none" | "day" | "month" | "post".
            topic_id:         Фильтр по топику форума (None = весь чат).
            user_id:          Фильтр по пользователю (None = все).
            include_comments: Включать ли комментарии (split_mode="post").
            period_label:     Суффикс имени файла (из CollectResult.period_label).
            log:              Колбэк для UI-логов.

        Returns:
            Список путей к созданным DOCX-файлам. Пустой список при ошибке.

        Raises:
            DocxGenerationError: при критической ошибке создания файла.
            EmptyDataError:      если в БД нет сообщений для данного chat_id.
        """
        if split_mode not in VALID_SPLIT_MODES:
            raise DocxGenerationError(
                file_path="",
                message=f"Неверный split_mode: '{split_mode}'. "
                        f"Допустимые: {VALID_SPLIT_MODES}",
            )

        self._log          = log or logger.info
        self._chat_title   = chat_title or f"chat_{chat_id}"
        self._period_label = period_label
        os.makedirs(self._output_dir, exist_ok=True)

        # Загружаем все транскрипции чата одним запросом
        try:
            self._transcriptions = self._db.get_transcriptions_for_chat(chat_id)
            if self._transcriptions:
                self._log(f"🎙 STT: загружено {len(self._transcriptions)} транскрипций")
        except Exception:
            self._transcriptions = {}

        self._log(f"📄 Генерация DOCX (режим: {split_mode})...")
        logger.info(
            "export: generate chat_id=%s split=%s topic=%s user=%s comments=%s",
            chat_id, split_mode, topic_id, user_id, include_comments,
        )

        try:
            if split_mode == "post":
                files = self._generate_by_posts(
                    chat_id          = chat_id,
                    topic_id         = topic_id,
                    user_id          = user_id,
                    include_comments = include_comments,
                )
            else:
                messages = self._db.get_messages(
                    chat_id          = chat_id,
                    topic_id         = topic_id,
                    user_id          = user_id,
                    include_comments = include_comments,
                )
                if not messages:
                    raise EmptyDataError(chat_id, topic_id)

                if split_mode == "day":
                    files = self._generate_by_day(messages, chat_id)
                elif split_mode == "month":
                    files = self._generate_by_month(messages, chat_id)
                else:  # "none"
                    files = self._generate_single(messages, chat_id)

        except (EmptyDataError, DocxGenerationError):
            raise
        except Exception as exc:
            logger.exception("export: unexpected error in generate()")
            raise DocxGenerationError(
                file_path=self._output_dir,
                message=f"Неожиданная ошибка генерации: {exc}",
                original=exc,
            ) from exc

        self._log(f"✅ Создано файлов: {len(files)}")
        return files

    # ------------------------------------------------------------------
    # Режимы генерации
    # ------------------------------------------------------------------

    def _generate_single(
        self,
        messages: List[tuple],
        chat_id:  int,
    ) -> List[str]:
        """
        Режим "none" — один файл со всеми сообщениями.

        Args:
            messages: Строки из DBManager.get_messages().
            chat_id:  ID чата (для имени файла).

        Returns:
            Список из одного пути к файлу.
        """
        xml_magic.reset_counter()
        doc = Document()

        title = doc.add_heading(f"Архив чата: {self._chat_title}", level=1)
        title.alignment = WD_ALIGN_PARAGRAPH.CENTER

        for msg in messages:
            self._add_message_to_doc(doc, msg)

        file_path = self._build_path("archive")
        self._save_doc(doc, file_path)
        self._log(f"  ✅ {os.path.basename(file_path)} ({len(messages)} сообщений)")
        return [file_path]

    def _generate_by_day(
        self,
        messages: List[tuple],
        chat_id:  int,
    ) -> List[str]:
        """
        Режим "day" — по одному файлу на каждый день.

        Args:
            messages: Строки из DBManager.get_messages(), отсортированные по дате.
            chat_id:  ID чата.

        Returns:
            Список путей к файлам (по одному на день).
        """
        days: Dict[str, List[tuple]] = defaultdict(list)
        for msg in messages:
            day = msg[_COL_DATE][:10]   # "YYYY-MM-DD"
            days[day].append(msg)

        files: List[str] = []
        for day, day_msgs in sorted(days.items()):
            xml_magic.reset_counter()
            doc = Document()

            title = doc.add_heading(f"Сообщения за {day}", level=1)
            title.alignment = WD_ALIGN_PARAGRAPH.CENTER

            for msg in day_msgs:
                self._add_message_to_doc(doc, msg)

            file_path = self._build_path(f"day_{day}")
            self._save_doc(doc, file_path)
            files.append(file_path)
            self._log(f"  ✅ {os.path.basename(file_path)} ({len(day_msgs)} сообщений)")

        self._log(f"📅 Создано {len(files)} файлов по дням")
        return files

    def _generate_by_month(
        self,
        messages: List[tuple],
        chat_id:  int,
    ) -> List[str]:
        """
        Режим "month" — по одному файлу на каждый месяц.

        Args:
            messages: Строки из DBManager.get_messages().
            chat_id:  ID чата.

        Returns:
            Список путей к файлам (по одному на месяц).
        """
        months: Dict[str, List[tuple]] = defaultdict(list)
        for msg in messages:
            month = msg[_COL_DATE][:7]  # "YYYY-MM"
            months[month].append(msg)

        files: List[str] = []
        for month, month_msgs in sorted(months.items()):
            xml_magic.reset_counter()
            doc = Document()

            title = doc.add_heading(f"Сообщения за {month}", level=1)
            title.alignment = WD_ALIGN_PARAGRAPH.CENTER

            for msg in month_msgs:
                self._add_message_to_doc(doc, msg)

            file_path = self._build_path(f"month_{month}")
            self._save_doc(doc, file_path)
            files.append(file_path)
            self._log(f"  ✅ {os.path.basename(file_path)} ({len(month_msgs)} сообщений)")

        self._log(f"📅 Создано {len(files)} файлов по месяцам")
        return files

    def _generate_by_posts(
        self,
        chat_id:          int,
        topic_id:         Optional[int],
        user_id:          Optional[int],
        include_comments: bool,
    ) -> List[str]:
        """
        Режим "post" — по одному файлу на каждый пост.

        Если include_comments=True, каждый файл содержит пост + его комментарии.
        Если include_comments=False, каждый файл содержит только один пост.

        Args:
            chat_id:          ID чата.
            topic_id:         Фильтр по топику.
            user_id:          Фильтр по пользователю.
            include_comments: Включать ли комментарии.

        Returns:
            Список путей к файлам (по одному на пост).

        Raises:
            EmptyDataError: если постов нет.
        """
        # Получаем только посты (is_comment=0)
        posts = self._db.get_messages(
            chat_id          = chat_id,
            topic_id         = topic_id,
            user_id          = user_id,
            include_comments = False,
        )
        if not posts:
            raise EmptyDataError(chat_id, topic_id)

        self._log(f"📝 Найдено постов: {len(posts)}")
        files: List[str] = []

        for post in posts:
            post_id  = post[_COL_MESSAGE_ID]
            xml_magic.reset_counter()
            doc = Document()

            title = doc.add_heading(f"Пост #{post_id}", level=1)
            title.alignment = WD_ALIGN_PARAGRAPH.CENTER

            # Сам пост
            self._add_message_to_doc(doc, post, is_post=True)

            # Комментарии (если нужны)
            comments: list = []
            if include_comments:
                all_rows = self._db.get_post_with_comments(chat_id, post_id)
                # Фильтруем: только комментарии (не сам пост)
                comments = [
                    r for r in all_rows
                    if not (r[_COL_MESSAGE_ID] == post_id and r[_COL_IS_COMMENT] == 0)
                ]
                if comments:
                    doc.add_paragraph()
                    comment_header = doc.add_heading(
                        f"💬 Комментарии ({len(comments)})", level=2
                    )
                    comment_header.paragraph_format.space_before = Pt(12)

                    for comment in comments:
                        self._add_message_to_doc(doc, comment, is_comment=True)

            file_path = self._build_path(f"post_{post_id}")
            self._save_doc(doc, file_path)
            files.append(file_path)

            comment_count = len(comments)
            suffix = f" ({comment_count} комментариев)" if include_comments else ""
            self._log(f"  ✅ {os.path.basename(file_path)}{suffix}")

        return files

    # ------------------------------------------------------------------
    # Добавление сообщения в документ
    # ------------------------------------------------------------------

    def _add_message_to_doc(
        self,
        doc:        Document,
        msg:        tuple,
        is_post:    bool = False,
        is_comment: bool = False,
    ) -> None:
        """
        Форматирует одну строку из БД и добавляет её в документ.

        Структура блока сообщения:
            [Параграф с закладкой]
            [Заголовок: имя + дата]
            [↩️ В ответ на: ссылка] (если reply_to не None)
            [Текст сообщения]        (с автоссылками)
            [📎 Медиафайл: ссылка]   (если есть медиа)
            [Изображение]            (если медиа — картинка)
            [──────────────]         (разделитель, не для комментариев)

        Args:
            doc:        Документ python-docx.
            msg:        Строка из get_messages() / get_post_with_comments().
            is_post:    True → оформлять как пост канала.
            is_comment: True → добавлять отступы, другой цвет заголовка.
        """
        msg_id     = msg[_COL_MESSAGE_ID]
        username   = msg[_COL_USERNAME]  or "Unknown"
        date_str   = msg[_COL_DATE]      or ""
        text       = msg[_COL_TEXT]      or ""
        media_path = msg[_COL_MEDIA_PATH]
        reply_to   = msg[_COL_REPLY_TO]

        # --- Закладка (якорь для внутренних ссылок) ---
        anchor_p = doc.add_paragraph()
        xml_magic.add_bookmark(anchor_p, f"msg_{msg_id}")
        # Убираем лишний отступ у параграфа-якоря
        anchor_p.paragraph_format.space_before = Pt(0)
        anchor_p.paragraph_format.space_after  = Pt(0)

        # --- Заголовок сообщения ---
        header_p = doc.add_paragraph()
        if is_post:
            header_text = f"📌 ПОСТ от {username}"
            font_size   = Pt(12)
            font_color  = RGBColor(0, 102, 204)
        elif is_comment:
            header_text = f"  💬 {username}"
            font_size   = Pt(10)
            font_color  = RGBColor(102, 102, 102)
        else:
            header_text = f"👤 {username}"
            font_size   = Pt(11)
            font_color  = RGBColor(51, 51, 51)

        run = header_p.add_run(header_text)
        run.bold             = True
        run.font.size        = font_size
        run.font.color.rgb   = font_color

        # Дата
        date_run = header_p.add_run(f"\n📅 {date_str}")
        date_run.font.size  = Pt(9)
        date_run.font.color.rgb = RGBColor(128, 128, 128)

        if is_comment:
            header_p.paragraph_format.left_indent = Inches(_COMMENT_INDENT_INCHES)

        # --- Ссылка-ответ ---
        if reply_to:
            reply_p = doc.add_paragraph()
            reply_p.add_run("↩️ В ответ на: ")
            xml_magic.add_internal_hyperlink(
                reply_p, reply_to, f"сообщение #{reply_to}"
            )
            if is_comment:
                reply_p.paragraph_format.left_indent = Inches(_COMMENT_INDENT_INCHES)

        # --- Текст с авто-ссылками ---
        if text:
            text_p = doc.add_paragraph()
            xml_magic.write_text_with_links(text_p, text)
            if is_comment:
                text_p.paragraph_format.left_indent = Inches(_COMMENT_INDENT_INCHES)

        # --- Медиа ---
        # Проверяем существование файла ДО os.path.abspath() —
        # иначе add_external_hyperlink запишет битую ссылку в XML,
        # что Word воспринимает как повреждение документа.
        if media_path and os.path.exists(media_path):
            abs_path = os.path.abspath(media_path)

            media_p  = doc.add_paragraph("📎 Медиафайл: ")
            file_uri = Path(abs_path).as_uri()
            xml_magic.add_external_hyperlink(
                media_p, file_uri, os.path.basename(abs_path)
            )
            if is_comment:
                media_p.paragraph_format.left_indent = Inches(_COMMENT_INDENT_INCHES)

            # Вставка изображения (только если это картинка)
            if is_image_path(abs_path):
                try:
                    img_p   = doc.add_paragraph()
                    img_run = img_p.add_run()
                    img_run.add_picture(abs_path, width=Inches(_IMAGE_WIDTH_INCHES))
                    if is_comment:
                        img_p.paragraph_format.left_indent = Inches(_COMMENT_INDENT_INCHES)
                except Exception as exc:
                    logger.warning(
                        "export: cannot insert image %s: %s",
                        os.path.basename(abs_path), exc
                    )
                    self._log(
                        f"⚠️ Не удалось вставить изображение "
                        f"{os.path.basename(abs_path)}: {exc}"
                    )

        elif media_path:
            # Файл записан в БД, но недоступен на диске — только текст, без ссылки
            media_p = doc.add_paragraph(
                f"📎 [медиафайл недоступен]: {os.path.basename(media_path)}"
            )
            if is_comment:
                media_p.paragraph_format.left_indent = Inches(_COMMENT_INDENT_INCHES)

        # --- Транскрипция голосового / видео-сообщения ---
        file_type = msg[_COL_FILE_TYPE] or ""
        if file_type in ("voice", "video_note") and msg_id in self._transcriptions:
            stt_text = self._transcriptions[msg_id]
            if stt_text:
                stt_p = doc.add_paragraph()
                stt_label = stt_p.add_run("🎙 Распознанная речь: ")
                stt_label.bold = True
                stt_label.font.size = Pt(10)
                stt_label.font.color.rgb = RGBColor(80, 80, 80)
                stt_run = stt_p.add_run(stt_text)
                stt_run.font.size = Pt(10)
                stt_run.font.color.rgb = RGBColor(40, 40, 40)
                stt_run.italic = True
                if is_comment:
                    stt_p.paragraph_format.left_indent = Inches(_COMMENT_INDENT_INCHES)

        # --- Разделитель (не для комментариев) ---
        if not is_comment:
            sep_p = doc.add_paragraph(_SEPARATOR)
            sep_p.paragraph_format.space_before = Pt(4)
            sep_p.paragraph_format.space_after  = Pt(4)
            # Серый цвет у разделителя
            for run in sep_p.runs:
                run.font.color.rgb = RGBColor(200, 200, 200)

    # ------------------------------------------------------------------
    # Вспомогательные методы
    # ------------------------------------------------------------------

    def _build_path(self, kind: str) -> str:
        """
        Строит полный путь к DOCX-файлу.

        Формат имени:
            <безопасное_имя_чата>_<kind>_<period_label>.docx

        Args:
            kind: Тип файла (например, "archive", "day_2025-01-15", "post_42").

        Returns:
            Абсолютный путь к файлу.
        """
        safe_title = sanitize_filename(self._chat_title)
        filename   = f"{safe_title}_{kind}_{self._period_label}.docx"
        return os.path.join(self._output_dir, filename)

    def _save_doc(self, doc: Document, file_path: str) -> None:
        """
        Сохраняет документ на диск.

        Args:
            doc:       Объект python-docx Document.
            file_path: Полный путь к файлу (включая .docx).

        Raises:
            DocxGenerationError: если не удалось записать файл.
        """
        try:
            doc.save(file_path)
            logger.debug("export: saved %s", file_path)
        except Exception as exc:
            logger.error("export: save failed %s: %s", file_path, exc)
            raise DocxGenerationError(
                file_path = file_path,
                message   = f"Не удалось сохранить файл: {exc}",
                original  = exc,
            ) from exc


# ==============================================================================
# JsonGenerator
# ==============================================================================

_AI_SPLIT_WORDS = 300_000   # порог слов для разбивки ИИ-чанков


def _word_count(text: Optional[str]) -> int:
    """Быстрый подсчёт слов (split по пробелам)."""
    return len(text.split()) if text else 0


class JsonGenerator:
    """
    Генерирует JSON-архив переписки из SQLite.

    Структура выходного файла — плоский список объектов, пригодный для
    загрузки в NotebookLM / ChatGPT и простого чтения вручную:

        [
          {
            "message_id": 123,
            "date":       "2025-03-16T10:30:00",
            "sender_id":  456789,
            "username":   "vasya",
            "text":       "Привет!",
            "media_path": null,
            "stt_text":   null
          },
          ...
        ]

    При ai_split=True файл разбивается на части по ~300k слов
    (telegram_history_part_1.json, _part_2.json, …).

    Нет Qt-зависимостей. Нет Telethon-зависимостей. Только stdlib + DBManager.
    """

    def __init__(self, db: DBManager, output_dir: str = "output") -> None:
        self._db         = db
        self._output_dir = output_dir

    def generate(
        self,
        chat_id:          int,
        chat_title:       str,
        *,
        topic_id:         Optional[int]  = None,
        user_id:          Optional[int]  = None,
        include_comments: bool           = False,
        ai_split:         bool           = False,
        log:              _LogCallback   = lambda _: None,
    ) -> List[str]:
        """
        Основная точка входа. Строит JSON и сохраняет на диск.

        Returns:
            Список абсолютных путей к созданным .json файлам
            (один файл без ai_split, несколько с ai_split).

        Raises:
            EmptyDataError: нет сообщений для экспорта.
            OSError: ошибка записи файла.
        """
        os.makedirs(self._output_dir, exist_ok=True)

        log("📋 Загружаю сообщения из БД для JSON-экспорта...")
        rows = self._db.get_messages(
            chat_id,
            topic_id         = topic_id,
            user_id          = user_id,
            include_comments = include_comments,
        )

        if not rows:
            raise EmptyDataError(f"Нет сообщений для чата {chat_id}")

        log(f"📊 Строк получено: {len(rows)}")

        stt_map: dict[int, str] = self._db.get_transcriptions_for_chat(chat_id)
        safe_title = sanitize_filename(chat_title)

        # ── Без разбивки: один файл ────────────────────────────────────
        if not ai_split:
            records: List[dict] = []
            for row in rows:
                msg_id = row[_COL_MESSAGE_ID]
                records.append(self._make_record(row, stt_map.get(msg_id)))
            out_path = os.path.join(self._output_dir, f"{safe_title}_telegram_history.json")
            self._write_json(out_path, records, log)
            return [out_path]

        # ── С разбивкой по ~300k слов ──────────────────────────────────
        out_paths: List[str] = []
        chunk:      List[dict] = []
        words      = 0
        part       = 1

        for row in rows:
            msg_id  = row[_COL_MESSAGE_ID]
            record  = self._make_record(row, stt_map.get(msg_id))
            chunk.append(record)
            words += _word_count(record.get("text")) + _word_count(record.get("stt_text"))

            if words >= _AI_SPLIT_WORDS:
                path = os.path.join(
                    self._output_dir,
                    f"{safe_title}_telegram_history_part_{part}.json",
                )
                self._write_json(path, chunk, log)
                out_paths.append(path)
                chunk = []
                words = 0
                part += 1

        if chunk:   # последний (возможно неполный) чанк
            path = os.path.join(
                self._output_dir,
                f"{safe_title}_telegram_history_part_{part}.json",
            )
            self._write_json(path, chunk, log)
            out_paths.append(path)

        log(f"✅ JSON готов: {len(rows)} сообщений → {len(out_paths)} файл(ов)")
        return out_paths

    # ── Вспомогательные ───────────────────────────────────────────────

    @staticmethod
    def _make_record(row, stt_text: Optional[str]) -> dict:
        return {
            "message_id": row[_COL_MESSAGE_ID],
            "date":       row[_COL_DATE] or None,
            "sender_id":  row[_COL_USER_ID],
            "username":   row[_COL_USERNAME] or None,
            "text":       row[_COL_TEXT] or None,
            "media_path": row[_COL_MEDIA_PATH] or None,
            "stt_text":   stt_text,
        }

    def _write_json(self, path: str, records: List[dict], log: _LogCallback) -> None:
        log(f"💾 Записываю JSON: {os.path.basename(path)} ({len(records)} сообщений)")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(records, fh, ensure_ascii=False, indent=2, default=str)
        logger.info("JsonGenerator: saved %d records → %s", len(records), path)


# ==============================================================================
# MarkdownGenerator
# ==============================================================================

class MarkdownGenerator:
    """
    Генерирует Markdown-архив переписки из SQLite.

    Формат каждого сообщения:

        **[YYYY-MM-DD HH:MM] Имя Автора:**
        Текст сообщения

        *(STT: текст расшифровки)*   <- только если есть STT

        ---

    При ai_split=True файл разбивается на части по ~300k слов
    (telegram_history_part_1.md, _part_2.md, …).

    Нет Qt-зависимостей. Нет Telethon-зависимостей. Только stdlib + DBManager.
    """

    def __init__(self, db: DBManager, output_dir: str = "output") -> None:
        self._db         = db
        self._output_dir = output_dir

    def generate(
        self,
        chat_id:          int,
        chat_title:       str,
        *,
        topic_id:         Optional[int]  = None,
        user_id:          Optional[int]  = None,
        include_comments: bool           = False,
        ai_split:         bool           = False,
        log:              _LogCallback   = lambda _: None,
    ) -> List[str]:
        """
        Основная точка входа. Строит Markdown и сохраняет на диск.

        Returns:
            Список абсолютных путей к созданным .md файлам.

        Raises:
            EmptyDataError: нет сообщений для экспорта.
            OSError: ошибка записи файла.
        """
        os.makedirs(self._output_dir, exist_ok=True)

        log("📋 Загружаю сообщения из БД для Markdown-экспорта...")
        rows = self._db.get_messages(
            chat_id,
            topic_id         = topic_id,
            user_id          = user_id,
            include_comments = include_comments,
        )

        if not rows:
            raise EmptyDataError(f"Нет сообщений для чата {chat_id}")

        log(f"📊 Строк получено: {len(rows)}")

        stt_map:   dict[int, str] = self._db.get_transcriptions_for_chat(chat_id)
        safe_title = sanitize_filename(chat_title)

        header = f"# {chat_title}\n\n"

        # ── Без разбивки: один файл ────────────────────────────────────
        if not ai_split:
            lines: List[str] = [header]
            for row in rows:
                lines.append(self._format_message(row, stt_map.get(row[_COL_MESSAGE_ID])))
            out_path = os.path.join(self._output_dir, f"{safe_title}_telegram_history.md")
            self._write_md(out_path, lines, log)
            return [out_path]

        # ── С разбивкой по ~300k слов ──────────────────────────────────
        out_paths: List[str] = []
        chunk:     List[str] = [header]
        words      = 0
        part       = 1

        for row in rows:
            msg_id  = row[_COL_MESSAGE_ID]
            stt     = stt_map.get(msg_id)
            block   = self._format_message(row, stt)
            chunk.append(block)
            words += (
                _word_count(row[_COL_TEXT])
                + _word_count(stt)
            )

            if words >= _AI_SPLIT_WORDS:
                path = os.path.join(
                    self._output_dir,
                    f"{safe_title}_telegram_history_part_{part}.md",
                )
                self._write_md(path, chunk, log)
                out_paths.append(path)
                chunk = [header]
                words = 0
                part += 1

        if len(chunk) > 1:   # есть сообщения (не только header)
            path = os.path.join(
                self._output_dir,
                f"{safe_title}_telegram_history_part_{part}.md",
            )
            self._write_md(path, chunk, log)
            out_paths.append(path)

        log(f"✅ Markdown готов: {len(rows)} сообщений → {len(out_paths)} файл(ов)")
        return out_paths

    # ── Вспомогательные ───────────────────────────────────────────────

    @staticmethod
    def _format_message(row, stt_text: Optional[str]) -> str:
        """Форматирует одно сообщение в Markdown-блок."""
        # Дата: берём первые 16 символов ISO-строки → "YYYY-MM-DD HH:MM"
        raw_date = row[_COL_DATE] or ""
        date_str = raw_date[:16].replace("T", " ") if raw_date else "—"

        author   = row[_COL_USERNAME] or f"id:{row[_COL_USER_ID]}" or "Неизвестно"
        text     = (row[_COL_TEXT] or "").strip()

        lines = [f"**[{date_str}] {author}:**"]
        if text:
            lines.append(text)
        if stt_text:
            lines.append(f"\n*(STT: {stt_text.strip()})*")
        lines.append("\n---\n")
        return "\n".join(lines) + "\n"

    def _write_md(self, path: str, lines: List[str], log: _LogCallback) -> None:
        log(f"💾 Записываю MD: {os.path.basename(path)}")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("".join(lines))
        logger.info("MarkdownGenerator: saved → %s", path)
