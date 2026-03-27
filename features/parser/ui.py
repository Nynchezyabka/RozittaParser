"""
FILE: features/parser/ui.py

UI-слой парсера: экран настроек (колонка 3 из Rozitta_prototype.html)
и QThread-воркер запуска парсинга.

Содержит:
  ─────────────────────────────────────────────────────────────────────
  ParseSettingsScreen   — главный виджет колонки 3:
    • Поле выбранного чата (readonly, заполняется из ChatsScreen)
    • Раздел «Медиафайлы»      — 5 MediaButton (Фото/Видео/Кружки/Голос/Файлы)
    • Раздел «Распознавание»   — 3 ChipButton (Видео/Аудио/Кружки)
    • Раздел «Диапазон дат»    — два QDateEdit (С / По)
    • Раздел «Фильтр юзеров»   — кнопка загрузки + режим + UserTag-тэги
    • Раздел «Разбивка DOCX»   — 4 SplitModeButton + ToggleSwitch комментариев

  ParseWorker           — QThread-обёртка над ParserService.collect_data()

  ParseParams           — dataclass параметров, собираемых экраном

  ПРАВИЛО: Никакого Telethon, asyncio, sqlite3. Только PySide6 + Signal/Slot.
  Бизнес-логика — в features/parser/api.py (не трогаем).
  ─────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

from PySide6.QtCore import (
    QObject, Qt, Signal, QThread, QDate,
)
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QLineEdit, QDateEdit,
    QScrollArea, QFrame, QSizePolicy, QButtonGroup,
    QSpacerItem,
)

from core.ui_shared.styles import (
    ACCENT_ORANGE, ACCENT_PINK, ACCENT_SOFT_PINK,
    TEXT_PRIMARY, TEXT_SECONDARY, TEXT_DISABLED,
    OVERLAY_HEX, OVERLAY2_HEX, BORDER_HEX,
    RADIUS_LG, RADIUS_MD, RADIUS_XS,
    FONT_FAMILY, FONT_SIZE_BODY, FONT_SIZE_SMALL, FONT_SIZE_XS,
    QSS_INPUT, QSS_BUTTON_SECONDARY, QSS_DATE_EDIT, QSS_SCROLL_AREA,
)
from core.ui_shared.widgets import (
    SectionTitle, MediaButton, ChipButton,
    SplitModeButton, ToggleSwitch, UserTag,
)

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# DATACLASS ПАРАМЕТРОВ
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class ParseParams:
    """
    Все параметры парсинга, собираемые с экрана.
    Передаётся в ParseWorker и далее в ParserService.collect_data().
    """
    chat: dict                           # словарь выбранного чата из ChatsScreen

    # Медиа
    download_photo:        bool = True
    download_video:        bool = True
    download_videomessage: bool = True
    download_voice:        bool = True
    download_file:         bool = True

    # STT (распознавание речи)
    stt_video:        bool = True
    stt_voice:        bool = True
    stt_videomessage: bool = True

    # Диапазон дат (None = без ограничений)
    date_from: Optional[date] = None
    date_to:   Optional[date] = None

    # Фильтр пользователей
    user_filter_mode: str = "messages-only"   # "messages-only" | "all-threads"
    user_ids: list[int] = field(default_factory=list)  # пусто = все

    # Разбивка DOCX
    split_mode:         str  = "none"   # "none" | "day" | "month" | "post"
    include_comments:   bool = False    # только при split_mode="post"

    # Режим перезагрузки
    re_download:        bool = False    # True = игнорировать downloaded.txt, скачать заново

    # Takeout API
    use_takeout:        bool = False    # True = Takeout API (отдельные лимиты, быстрее при VPN)

    # Фильтр выражений (simpleeval, опционально)
    filter_expression:  Optional[str] = None  # напр. "has_media and media_type=='photo'"


# ══════════════════════════════════════════════════════════════════════════════
# ВСПОМОГАТЕЛЬНЫЕ ВИДЖЕТЫ ЭКРАНА
# ══════════════════════════════════════════════════════════════════════════════

def _label(text: str, size: int = FONT_SIZE_SMALL,
           color: str = TEXT_SECONDARY) -> QLabel:
    """Быстрое создание QLabel с нужным шрифтом и цветом."""
    lbl = QLabel(text)
    lbl.setFont(QFont(FONT_FAMILY, size))
    lbl.setStyleSheet(f"QLabel {{ color: {color}; background: transparent; }}")
    lbl.setWordWrap(True)
    return lbl


class _SubSection(QFrame):
    """
    Контейнер-подсекция с тёмным фоном и скруглёнными углами.
    Соответствует .date-range, .user-filter из прототипа.
    """
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setStyleSheet(f"""
            _SubSection, QFrame {{
                background-color: {OVERLAY2_HEX};
                border-radius: {RADIUS_MD}px;
                border: none;
            }}
        """)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(12, 12, 12, 12)
        self._layout.setSpacing(8)

    def inner_layout(self) -> QVBoxLayout:
        return self._layout


class _UserModeButton(QPushButton):
    """
    Кнопка режима фильтрации пользователей (Только сообщения / Все ветки).
    Соответствует .user-mode-option из прототипа.
    """
    def __init__(self, icon: str, text: str, mode: str,
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._mode = mode
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        icon_lbl = QLabel(icon)
        icon_lbl.setFont(QFont(FONT_FAMILY, 14))
        icon_lbl.setStyleSheet("background: transparent;")
        layout.addWidget(icon_lbl)

        text_lbl = QLabel(text)
        text_lbl.setFont(QFont(FONT_FAMILY, FONT_SIZE_XS))
        text_lbl.setWordWrap(True)
        text_lbl.setStyleSheet("background: transparent;")
        layout.addWidget(text_lbl, 1)

        self._icon_lbl = icon_lbl
        self._text_lbl = text_lbl

        self.toggled.connect(self._refresh)
        self._refresh(False)

    @property
    def mode(self) -> str:
        return self._mode

    def _refresh(self, checked: bool) -> None:
        if checked:
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: {ACCENT_SOFT_PINK};
                    border: 1px solid {ACCENT_PINK};
                    border-radius: {RADIUS_MD}px;
                    color: {ACCENT_PINK};
                }}
            """)
            self._icon_lbl.setStyleSheet(f"color: {ACCENT_PINK}; background: transparent;")
            self._text_lbl.setStyleSheet(f"color: {ACCENT_PINK}; background: transparent;")
        else:
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: {OVERLAY2_HEX};
                    border: 1px solid {BORDER_HEX};
                    border-radius: {RADIUS_MD}px;
                    color: {TEXT_SECONDARY};
                }}
                QPushButton:hover {{
                    background-color: {OVERLAY_HEX};
                }}
            """)
            self._icon_lbl.setStyleSheet(f"color: {TEXT_SECONDARY}; background: transparent;")
            self._text_lbl.setStyleSheet(f"color: {TEXT_SECONDARY}; background: transparent;")


# ══════════════════════════════════════════════════════════════════════════════
# PARSE SETTINGS SCREEN  — главный виджет колонки 3
# ══════════════════════════════════════════════════════════════════════════════

class ParseSettingsScreen(QWidget):
    """
    Экран настроек парсинга (колонка 3 из прототипа).

    Сигналы (исходящие → MainWindow):
        parse_requested(ParseParams)   — пользователь нажал «Начать парсинг»
        load_members_requested(dict)   — нажата кнопка «Загрузить участников»
        log_message(str)               — текстовое сообщение для LogWidget

    Входящие слоты (вызываются из MainWindow):
        set_chat(chat: dict)           — установить выбранный чат
        populate_members(users: list)  — загрузить список участников

    Пример подключения в MainWindow:
        settings = ParseSettingsScreen()
        settings.parse_requested.connect(self._on_parse_requested)
        settings.load_members_requested.connect(self._on_load_members)
        chats_screen.chat_selected.connect(settings.set_chat)
        parser_worker.members_loaded.connect(settings.populate_members)
    """

    parse_requested        = Signal(object)   # ParseParams
    load_members_requested = Signal(dict)     # chat dict
    log_message            = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._current_chat: Optional[dict] = None
        self._member_tags: list[UserTag] = []

        self._build_ui()

    # ──────────────────────────────────────────────────────────────────────
    # ПОСТРОЕНИЕ UI
    # ──────────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Заголовок карточки ────────────────────────────────────────────
        title = SectionTitle("⚙️", "Настройки парсинга", accent=False)
        root.addWidget(title)

        # ── Скроллируемая область ─────────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(QSS_SCROLL_AREA)

        container = QWidget()
        container.setStyleSheet("background: transparent;")
        scroll_layout = QVBoxLayout(container)
        scroll_layout.setContentsMargins(0, 8, 8, 8)   # 8px справа для скроллбара
        scroll_layout.setSpacing(20)

        # Секции
        scroll_layout.addWidget(self._build_chat_section())
        scroll_layout.addWidget(self._build_media_section())
        scroll_layout.addWidget(self._build_stt_section())
        scroll_layout.addWidget(self._build_date_section())
        scroll_layout.addWidget(self._build_user_section())
        scroll_layout.addWidget(self._build_split_section())
        scroll_layout.addWidget(self._build_filter_section())
        scroll_layout.addStretch()

        scroll.setWidget(container)
        root.addWidget(scroll, 1)

        # ── Кнопка «Начать парсинг» ───────────────────────────────────────
        self._start_btn = QPushButton("▶  НАЧАТЬ ПАРСИНГ")
        self._start_btn.setFixedHeight(44)
        self._start_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._start_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {ACCENT_ORANGE};
                border: none;
                border-radius: {RADIUS_MD}px;
                color: #ffffff;
                font-family: {FONT_FAMILY};
                font-size: {FONT_SIZE_BODY}px;
                font-weight: 700;
                letter-spacing: 0.5px;
            }}
            QPushButton:hover  {{ background-color: #E08600; }}
            QPushButton:pressed {{ background-color: #C07400; }}
            QPushButton:disabled {{
                background-color: #5A3500;
                color: #888888;
            }}
        """)
        self._start_btn.setEnabled(False)   # включится при выборе чата
        self._start_btn.clicked.connect(self._on_start_clicked)

        root.addSpacing(12)
        root.addWidget(self._start_btn)

    # ── Секция: Выбранный чат ─────────────────────────────────────────────

    def _build_chat_section(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        layout.addWidget(_label("Выбранный чат", FONT_SIZE_SMALL, TEXT_SECONDARY))

        self._chat_display = QLineEdit()
        self._chat_display.setReadOnly(True)
        self._chat_display.setPlaceholderText("Выберите чат из списка →")
        self._chat_display.setStyleSheet(QSS_INPUT)
        self._chat_display.setFixedHeight(36)
        layout.addWidget(self._chat_display)
        return w

    # ── Секция: Медиафайлы ────────────────────────────────────────────────

    def _build_media_section(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        layout.addWidget(SectionTitle("📥", "Скачивание медиафайлов", accent=True))

        grid = QGridLayout()
        grid.setSpacing(8)
        grid.setContentsMargins(0, 0, 0, 0)

        media_defs = [
            ("🖼️", "Фото",   "photo"),
            ("🎬", "Видео",   "video"),
            ("🔵", "Кружки",  "videomessage"),
            ("🎙️", "Голос",   "voice"),
            ("📎", "Файлы",   "file"),
        ]

        self._media_buttons: dict[str, MediaButton] = {}
        for col, (icon, label, media_type) in enumerate(media_defs):
            btn = MediaButton(icon, label, media_type=media_type, active=True)
            btn.setMinimumHeight(64)
            grid.addWidget(btn, 0, col)
            self._media_buttons[media_type] = btn

        layout.addLayout(grid)
        return w

    # ── Секция: Распознавание речи ────────────────────────────────────────

    def _build_stt_section(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        layout.addWidget(
            SectionTitle("🎤", "Распознавание речи", accent=True,
                         desc="текст в DOCX")
        )

        chips_layout = QHBoxLayout()
        chips_layout.setSpacing(8)
        chips_layout.setContentsMargins(0, 0, 0, 0)

        stt_defs = [
            ("🎬", "Видео",   "video"),
            ("🎙️", "Аудио",   "voice"),
            ("🔵", "Кружки",  "videomessage"),
        ]

        self._stt_chips: dict[str, ChipButton] = {}
        for icon, label, media_type in stt_defs:
            chip = ChipButton(icon, label, media_type=media_type, active=True)
            chips_layout.addWidget(chip)
            self._stt_chips[media_type] = chip

        chips_layout.addStretch()
        layout.addLayout(chips_layout)

        hint = _label(
            "ℹ️  Faster-Whisper — распознавание на локальном GPU/CPU",
            FONT_SIZE_XS, TEXT_DISABLED
        )
        layout.addWidget(hint)
        return w

    # ── Секция: Диапазон дат ──────────────────────────────────────────────

    def _build_date_section(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        layout.addWidget(SectionTitle("📅", "Диапазон скачивания", accent=True))

        sub = _SubSection()
        sub_l = sub.inner_layout()

        # Поля дат
        dates_row = QHBoxLayout()
        dates_row.setSpacing(12)
        dates_row.setContentsMargins(0, 0, 0, 0)

        # Поле «С»
        from_col = QVBoxLayout()
        from_col.setSpacing(4)
        from_col.addWidget(_label("С", FONT_SIZE_XS, TEXT_SECONDARY))
        self._date_from = QDateEdit()
        self._date_from.setCalendarPopup(True)
        self._date_from.setDisplayFormat("yyyy-MM-dd")
        self._date_from.setDate(QDate.currentDate().addDays(-7))
        self._date_from.setStyleSheet(QSS_DATE_EDIT)
        self._date_from.setFixedHeight(34)
        from_col.addWidget(self._date_from)
        dates_row.addLayout(from_col)

        # Поле «По»
        to_col = QVBoxLayout()
        to_col.setSpacing(4)
        to_col.addWidget(_label("По", FONT_SIZE_XS, TEXT_SECONDARY))
        self._date_to = QDateEdit()
        self._date_to.setCalendarPopup(True)
        self._date_to.setDisplayFormat("yyyy-MM-dd")
        self._date_to.setDate(QDate.currentDate())
        self._date_to.setStyleSheet(QSS_DATE_EDIT)
        self._date_to.setFixedHeight(34)
        to_col.addWidget(self._date_to)
        dates_row.addLayout(to_col)

        sub_l.addLayout(dates_row)
        sub_l.addWidget(_label("ℹ️  Формат: ГГГГ-ММ-ДД", FONT_SIZE_XS, TEXT_DISABLED))

        layout.addWidget(sub)
        return w

    # ── Секция: Фильтр по пользователям ──────────────────────────────────

    def _build_user_section(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        layout.addWidget(
            SectionTitle("👤", "Фильтр по пользователям", accent=True,
                         desc="только выбранный")
        )

        sub = _SubSection()
        sub_l = sub.inner_layout()

        # Кнопка «Загрузить участников»
        self._load_members_btn = QPushButton("👥  Загрузить участников")
        self._load_members_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._load_members_btn.setEnabled(False)
        self._load_members_btn.setStyleSheet(QSS_BUTTON_SECONDARY)
        self._load_members_btn.clicked.connect(self._on_load_members_clicked)
        sub_l.addWidget(self._load_members_btn)

        # Режим фильтрации
        mode_row = QHBoxLayout()
        mode_row.setSpacing(8)

        self._mode_only = _UserModeButton("💬", "Только сообщения", "messages-only")
        self._mode_only.setChecked(True)
        self._mode_threads = _UserModeButton("🗨️", "Все ветки с участием", "all-threads")

        # Взаимная эксклюзивность через QButtonGroup
        self._mode_group = QButtonGroup(self)
        self._mode_group.setExclusive(True)
        self._mode_group.addButton(self._mode_only)
        self._mode_group.addButton(self._mode_threads)

        mode_row.addWidget(self._mode_only)
        mode_row.addWidget(self._mode_threads)
        sub_l.addLayout(mode_row)

        # Контейнер тегов пользователей
        self._tags_container = QWidget()
        self._tags_container.setStyleSheet("background: transparent;")
        self._tags_layout = QHBoxLayout(self._tags_container)
        self._tags_layout.setContentsMargins(0, 0, 0, 0)
        self._tags_layout.setSpacing(6)
        self._tags_layout.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )

        # Тег «Все» по умолчанию
        self._tag_all = UserTag("Все", user_id=0, is_all=True, selected=True)
        self._tag_all.toggled.connect(self._on_tag_all_toggled)
        self._tags_layout.addWidget(self._tag_all)
        self._tags_layout.addStretch()

        sub_l.addWidget(self._tags_container)

        hint = _label(
            "ℹ️  Без выбора участников — скачиваются сообщения всех",
            FONT_SIZE_XS, TEXT_DISABLED
        )
        sub_l.addWidget(hint)

        layout.addWidget(sub)
        return w

    # ── Секция: Разбивка документа ────────────────────────────────────────

    def _build_split_section(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        layout.addWidget(SectionTitle("📄", "Разбивка документа", accent=True))

        # 4 кнопки в сетке
        split_grid = QGridLayout()
        split_grid.setSpacing(8)
        split_grid.setContentsMargins(0, 0, 0, 0)

        split_defs = [
            ("📄", "Единый",  "none",  True),
            ("📆", "Дни",     "day",   False),
            ("🗓️", "Месяцы",  "month", False),
            ("📬", "Посты",   "post",  False),
        ]

        self._split_buttons: dict[str, SplitModeButton] = {}
        self._split_group = QButtonGroup(self)
        self._split_group.setExclusive(True)

        for col, (icon, label, mode, active) in enumerate(split_defs):
            btn = SplitModeButton(icon, label, mode=mode, active=active)
            btn.setMinimumHeight(64)
            split_grid.addWidget(btn, 0, col)
            self._split_buttons[mode] = btn
            self._split_group.addButton(btn)

        self._split_group.buttonToggled.connect(self._on_split_changed)
        layout.addLayout(split_grid)

        # Переключатель комментариев (только для режима "post")
        self._comments_row = QWidget()
        self._comments_row.setStyleSheet("background: transparent;")
        self._comments_row.setVisible(False)

        cr_layout = QHBoxLayout(self._comments_row)
        cr_layout.setContentsMargins(0, 4, 0, 0)
        cr_layout.setSpacing(8)

        cr_icon = QLabel("💬")
        cr_icon.setFont(QFont(FONT_FAMILY, FONT_SIZE_BODY))
        cr_icon.setStyleSheet(f"color: {ACCENT_ORANGE}; background: transparent;")
        cr_layout.addWidget(cr_icon)

        cr_lbl = QLabel("Скачивать комментарии к постам")
        cr_lbl.setFont(QFont(FONT_FAMILY, FONT_SIZE_SMALL))
        cr_lbl.setStyleSheet(f"color: {TEXT_PRIMARY}; background: transparent;")
        cr_layout.addWidget(cr_lbl, 1)

        self._comments_toggle = ToggleSwitch(checked=False)
        cr_layout.addWidget(self._comments_toggle)

        layout.addWidget(self._comments_row)
        return w

    # ── Секция: Фильтр выражений ──────────────────────────────────────────

    def _build_filter_section(self) -> QWidget:
        """
        Секция «Фильтр сообщений» — поле ввода Python-выражения (simpleeval).

        Примеры выражений:
            has_media and media_type == 'photo'
            user_id == 123456789
            'слово' in text.lower()
            date.year >= 2024
        """
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        layout.addWidget(
            SectionTitle("🔎", "Фильтр сообщений", accent=True,
                         desc="выражение (simpleeval)")
        )

        sub = _SubSection()
        sub_l = sub.inner_layout()

        self._filter_expr = QLineEdit()
        self._filter_expr.setPlaceholderText(
            "напр. has_media and media_type == 'photo'"
        )
        self._filter_expr.setStyleSheet(QSS_INPUT)
        self._filter_expr.setFixedHeight(36)
        self._filter_expr.setClearButtonEnabled(True)
        sub_l.addWidget(self._filter_expr)

        sub_l.addWidget(_label(
            "ℹ️  Доступно: text, user_id, username, has_media, media_type, date. "
            "Пустое поле = без фильтра. Требует pip install simpleeval.",
            FONT_SIZE_XS, TEXT_DISABLED,
        ))

        layout.addWidget(sub)
        return w

    # ──────────────────────────────────────────────────────────────────────
    # ВХОДЯЩИЕ СЛОТЫ
    # ──────────────────────────────────────────────────────────────────────

    def set_chat(self, chat: dict) -> None:
        """
        Слот: получить выбранный чат из ChatsScreen.
        Обновляет поле отображения и разблокирует кнопки.

        Подключение в MainWindow:
            chats_screen.chat_selected.connect(settings.set_chat)
        """
        self._current_chat = chat
        title = chat.get("title", "")
        chat_id = chat.get("id", "")
        self._chat_display.setText(f"{title}  ({chat_id})")
        self._start_btn.setEnabled(True)
        self._load_members_btn.setEnabled(True)
        self.log_message.emit(f"Выбран чат: {title}")

    def populate_members(self, users: list[dict]) -> None:
        """
        Слот: заполнить теги участников после загрузки.
        users = [{"id": int, "username": str, "name": str}, ...]

        Подключение в MainWindow:
            members_worker.members_loaded.connect(settings.populate_members)
        """
        # Очищаем старые теги (кроме «Все»)
        for tag in self._member_tags:
            self._tags_layout.removeWidget(tag)
            tag.deleteLater()
        self._member_tags.clear()

        # Убираем stretch перед добавлением новых
        # (addStretch добавляем снова в конце)
        while self._tags_layout.count() > 1:   # 0 = tag_all
            item = self._tags_layout.takeAt(1)
            if item.widget():
                item.widget().deleteLater()

        for user in users:
            uid = user.get("id", 0)
            uname = user.get("username") or user.get("name", f"id:{uid}")
            tag = UserTag(uname, user_id=uid, selected=False)
            tag.toggled.connect(self._on_user_tag_toggled)
            self._tags_layout.addWidget(tag)
            self._member_tags.append(tag)

        self._tags_layout.addStretch()
        self.log_message.emit(f"Загружено участников: {len(users)}")

    # ──────────────────────────────────────────────────────────────────────
    # СБОР ПАРАМЕТРОВ
    # ──────────────────────────────────────────────────────────────────────

    def get_params(self) -> Optional[ParseParams]:
        """
        Собрать ParseParams из текущего состояния виджета.
        Возвращает None если чат не выбран.
        """
        if self._current_chat is None:
            return None

        # Медиа
        dl = {k: btn.isActive() for k, btn in self._media_buttons.items()}

        # STT
        stt = {k: chip.isActive() for k, chip in self._stt_chips.items()}

        # Даты
        d_from = self._date_from.date().toPython()
        d_to   = self._date_to.date().toPython()

        # Пользователи
        selected_ids = [
            tag.user_id
            for tag in self._member_tags
            if tag.isChecked() and not tag.is_all
        ]
        mode_btn = self._mode_group.checkedButton()
        u_mode = mode_btn.mode if isinstance(mode_btn, _UserModeButton) else "messages-only"

        # Разбивка
        checked_split = self._split_group.checkedButton()
        split_mode = checked_split.mode if isinstance(checked_split, SplitModeButton) else "none"
        include_comments = (
            self._comments_toggle.isChecked() if split_mode == "post" else False
        )

        # Выражение фильтра (пустая строка → None)
        filter_expr = self._filter_expr.text().strip() or None

        return ParseParams(
            chat=self._current_chat,
            download_photo=dl.get("photo", True),
            download_video=dl.get("video", True),
            download_videomessage=dl.get("videomessage", True),
            download_voice=dl.get("voice", True),
            download_file=dl.get("file", True),
            stt_video=stt.get("video", True),
            stt_voice=stt.get("voice", True),
            stt_videomessage=stt.get("videomessage", True),
            date_from=d_from,
            date_to=d_to,
            user_filter_mode=u_mode,
            user_ids=selected_ids,
            split_mode=split_mode,
            include_comments=include_comments,
            filter_expression=filter_expr,
        )

    # ──────────────────────────────────────────────────────────────────────
    # ОБРАБОТЧИКИ СОБЫТИЙ
    # ──────────────────────────────────────────────────────────────────────

    def _on_start_clicked(self) -> None:
        params = self.get_params()
        if params is None:
            self.log_message.emit("⚠️  Сначала выберите чат")
            return
        self.log_message.emit(
            f"▶  Запуск парсинга: {params.chat.get('title')} "
            f"| медиа: {self._active_media_summary(params)} "
            f"| разбивка: {params.split_mode}"
        )
        self.parse_requested.emit(params)

    def _on_load_members_clicked(self) -> None:
        if self._current_chat is not None:
            self.log_message.emit("👥  Загружаем участников...")
            self.load_members_requested.emit(self._current_chat)

    def _on_split_changed(self, button: QPushButton, checked: bool) -> None:
        if not checked:
            return
        if isinstance(button, SplitModeButton):
            is_post = button.mode == "post"
            self._comments_row.setVisible(is_post)

    def _on_tag_all_toggled(self, checked: bool) -> None:
        """При выборе «Все» снять выделение с остальных тегов."""
        if checked:
            for tag in self._member_tags:
                tag.setChecked(False)

    def _on_user_tag_toggled(self, checked: bool) -> None:
        """При выборе конкретного участника снять «Все»."""
        if checked:
            self._tag_all.setChecked(False)

    # ──────────────────────────────────────────────────────────────────────
    # СОСТОЯНИЕ КНОПОК (вызывается из MainWindow во время парсинга)
    # ──────────────────────────────────────────────────────────────────────

    def set_parsing(self, active: bool) -> None:
        """
        Заблокировать/разблокировать UI во время парсинга.
        Вызывается из MainWindow при получении сигналов от ParseWorker.
        """
        self._start_btn.setEnabled(not active)
        self._load_members_btn.setEnabled(not active and self._current_chat is not None)
        if active:
            self._start_btn.setText("⏳  ПАРСИНГ...")
        else:
            self._start_btn.setText("▶  НАЧАТЬ ПАРСИНГ")

    # ──────────────────────────────────────────────────────────────────────
    # ВСПОМОГАТЕЛЬНЫЕ
    # ──────────────────────────────────────────────────────────────────────

    @staticmethod
    def _active_media_summary(params: ParseParams) -> str:
        parts = []
        if params.download_photo:        parts.append("фото")
        if params.download_video:        parts.append("видео")
        if params.download_videomessage: parts.append("кружки")
        if params.download_voice:        parts.append("голос")
        if params.download_file:         parts.append("файлы")
        return ", ".join(parts) if parts else "ничего"


# ══════════════════════════════════════════════════════════════════════════════
# PARSE WORKER  — QThread-обёртка над ParserService
# ══════════════════════════════════════════════════════════════════════════════

class ParseWorker(QThread):
    """
    Запускает features/parser/api.py :: ParserService.collect_data()
    в отдельном потоке через собственный asyncio event loop.

    Сигналы:
        log_message(str)          — строка для LogWidget
        progress(int)             — прогресс 0..100
        finished(object)          — CollectResult после успешного парсинга
        error(str)                — текст ошибки
        character_state(str)      — состояние персонажа: idle/process/success/error

    Использование в MainWindow:
        worker = ParseWorker(client, params, cfg)
        worker.log_message.connect(log_widget.append_info)
        worker.progress.connect(progress_bar.setValue)
        worker.finished.connect(self._on_parse_finished)
        worker.error.connect(self._on_parse_error)
        worker.start()
    """

    log_message     = Signal(str)
    progress        = Signal(int)
    finished        = Signal(object)    # CollectResult
    error           = Signal(str)
    character_state = Signal(str)

    def __init__(
        self,
        params: "ParseParams",
        cfg,                     # AppConfig
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self._params = params
        self._cfg    = cfg

    def run(self) -> None:
        """Точка входа потока. Создаёт event loop и запускает корутину."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(self._collect())
            self.finished.emit(result)
        except Exception as exc:
            logger.exception("ParseWorker error")
            self.error.emit(str(exc))
            self.character_state.emit("error")
        finally:
            loop.close()

    async def _collect(self):
        """Вызывает ParserService.collect_data() с параметрами из ParseParams."""
        import os
        from telethon import TelegramClient
        from features.parser.api import ParserService
        from core.database import DBManager
        from core.utils import sanitize_filename
        from config import DB_FILENAME

        self.character_state.emit("process")
        self.log_message.emit("🔄  Инициализация парсера...")

        # Папка чата: output_dir / <название чата>
        chat_title = self._params.chat.get("title", "chat")
        chat_dir = os.path.join(self._cfg.output_dir, sanitize_filename(chat_title))
        os.makedirs(chat_dir, exist_ok=True)
        db_path = os.path.join(chat_dir, DB_FILENAME)

        self.log_message.emit(f"📂  Папка чата: {chat_dir}")

        from features.auth.api import AuthService
        client = AuthService.build_client(self._cfg)
        for _attempt in range(5):
            try:
                await client.connect()
                break
            except Exception as _e:
                if "database is locked" in str(_e) and _attempt < 4:
                    self.log_message.emit(f"⏳ Session занята, жду... (попытка {_attempt + 1}/5)")
                    await asyncio.sleep(2)
                else:
                    raise
        try:
            with DBManager(db_path) as db:
                service = ParserService(
                    client   = client,
                    db       = db,
                    log      = self._on_log,
                    progress = self._on_progress,
                )
                collect_params = self._build_collect_params(chat_dir)
                result = await service.collect_data(collect_params)
        finally:
            await client.disconnect()

        # Фиксируем точный db_path — MainWindow будет использовать его напрямую
        # вместо реконструкции из chat_title (расхождение → sqlite3.OperationalError).
        result.db_path = db_path

        self.character_state.emit("success")
        self.log_message.emit(
            f"✅  Парсинг завершён: {result.messages_count} сообщений"
        )
        return result

    def _build_collect_params(self, chat_dir: str):
        """Преобразует ParseParams (UI) → CollectParams (API)."""
        from features.parser.api import CollectParams
        from datetime import datetime, timezone

        p = self._params

        # Медиа-фильтр из boolean флагов → список ключей
        media_types = []
        if p.download_photo:        media_types.append("photo")
        if p.download_video:        media_types.append("video")
        if p.download_videomessage: media_types.append("videomessage")
        if p.download_voice:        media_types.append("voice")
        if p.download_file:         media_types.append("file")
        # None = не скачивать ничего; [] = скачать всё; [...] = только эти типы
        media_filter = media_types if media_types else None

        # Конвертируем date → timezone-aware datetime UTC
        date_from = None
        date_to   = None
        if p.date_from:
            date_from = datetime(
                p.date_from.year, p.date_from.month, p.date_from.day,
                tzinfo=timezone.utc,
            )
        if p.date_to:
            date_to = datetime(
                p.date_to.year, p.date_to.month, p.date_to.day,
                23, 59, 59, tzinfo=timezone.utc,
            )

        return CollectParams(
            chat_id           = p.chat.get("id"),
            topic_id          = p.chat.get("selected_topic_id"),
            date_from         = date_from,
            date_to           = date_to,
            media_filter      = media_filter,
            download_comments = p.include_comments,
            user_ids          = p.user_ids if p.user_ids else None,
            output_dir        = chat_dir,   # папка чата, не корневая
            re_download       = p.re_download,
            filter_expression = p.filter_expression,
            use_takeout       = p.use_takeout,
        )

    def _on_log(self, message: str) -> None:
        self.log_message.emit(message)

    def _on_progress(self, value: int) -> None:
        self.progress.emit(value)
