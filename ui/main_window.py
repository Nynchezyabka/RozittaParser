"""
FILE: ui/main_window.py

MainWindow v4.0 — Redesign (tabs + right panel).

Layout:
    ┌─────────────────── Header (52px) ───────────────────┐
    │  ✦ Rozitta / Parser          [● Авторизован]        │
    └─────────────────────────────────────────────────────┘
    ┌────────────┬──────────────────────────┬─────────────┐
    │  Sidebar   │    Main Content          │ Right Panel │
    │  (196px)   │    (QStackedWidget)      │  (308px)    │
    │            │                          │             │
    │ [1] Auth   │  Tab 0: AuthScreen       │ [Rozitta]   │
    │ [2] Chats  │  Tab 1: ChatsScreen      │ [Log]       │
    │ [3] Sett.  │  Tab 2: ParseSettings*   │ [Progress]  │
    │            │                          │ [▶ START]   │
    │ [chat: …]  │  * заменяется в UI-2     │             │
    └────────────┴──────────────────────────┴─────────────┘

Ответственности:
  1. Построить 3-колоночный workspace (sidebar + stack + right)
  2. Подключить сигналы всех экранов и воркеров
  3. Управлять навигацией (NavButton states + QStackedWidget)
  4. Запускать/останавливать QThread-воркеры
  5. Показывать toast-уведомления

Чего НЕТ здесь:
  - Никакой бизнес-логики
  - Никаких прямых вызовов Telethon / asyncio / sqlite
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from PySide6.QtCore import Qt, QThread, Signal, QTimer, QSize, QUrl
from PySide6.QtGui import QCloseEvent, QFont, QColor
from PySide6.QtMultimedia import QSoundEffect
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QLabel, QSizePolicy, QProgressBar, QStackedWidget,
    QFrame, QPushButton, QApplication,
    QScrollArea, QGridLayout,
)

from config import AppConfig
from core.database import DBManager
from core.ui_shared.styles import (
    BG_PRIMARY, ACCENT_ORANGE, ACCENT_PINK,
    ACCENT_SOFT_ORANGE,
    TEXT_PRIMARY, TEXT_SECONDARY,
    OVERLAY_HEX, OVERLAY2_HEX, BORDER_HEX,
    RADIUS_LG, RADIUS_MD,
    FONT_FAMILY, FONT_SIZE_BODY, FONT_SIZE_SMALL,
    COLOR_SUCCESS, COLOR_ERROR, COLOR_WARNING,
    QSS_PROGRESS, QSS_INPUT,
)
from core.ui_shared.widgets import (
    RozittaWidget, LogWidget,
    ModernCard, SectionTitle, ToggleSwitch,
    MediaButton, ChipButton, SplitModeButton, UserTag,
)
from core.ui_shared.calendar import DateRangeWidget
from features.auth.ui import AuthScreen
from features.chats.ui import ChatsScreen
from features.parser.ui import ParseWorker, ParseParams

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# ВСПОМОГАТЕЛЬНЫЕ ВИДЖЕТЫ (private to this module)
# ══════════════════════════════════════════════════════════════════════════════

class NavButton(QFrame):
    """
    Кнопка навигации в сайдбаре.
    Layout: [●num] [text]
    States: 'default' | 'active' | 'done'
    """
    clicked = Signal()

    def __init__(self, num: int, text: str, parent=None):
        super().__init__(parent)
        self._state = "default"
        self._hovered = False
        self._build(num, text)
        self._apply_style()
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(38)

    def _build(self, num: int, text: str) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 10, 0)
        layout.setSpacing(9)

        self._num_lbl = QLabel(str(num))
        self._num_lbl.setObjectName("num")
        self._num_lbl.setFixedSize(20, 20)
        self._num_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._num_lbl)

        self._text_lbl = QLabel(text)
        self._text_lbl.setObjectName("navText")
        layout.addWidget(self._text_lbl, 1)

    def set_state(self, state: str) -> None:
        """state: 'default' | 'active' | 'done'"""
        self._state = state
        self._apply_style()

    def enterEvent(self, event) -> None:
        if self._state != "active":
            self._hovered = True
            self._apply_style()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self._apply_style()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def _apply_style(self) -> None:
        if self._state == "active":
            self.setStyleSheet(f"""
                NavButton {{
                    background-color: {ACCENT_SOFT_ORANGE};
                    border: 1px solid rgba(255,149,0,0.4);
                    border-radius: {RADIUS_MD}px;
                }}
                NavButton QLabel#num {{
                    background-color: {ACCENT_ORANGE};
                    border-radius: 10px;
                    color: #ffffff;
                    font-size: 11px;
                    font-weight: 600;
                    border: none;
                }}
                NavButton QLabel#navText {{
                    color: {ACCENT_ORANGE};
                    font-size: 13px;
                    font-weight: 500;
                    background: transparent;
                    border: none;
                }}
            """)
        elif self._state == "done":
            bg = OVERLAY2_HEX if self._hovered else "transparent"
            self.setStyleSheet(f"""
                NavButton {{
                    background-color: {bg};
                    border: 1px solid transparent;
                    border-radius: {RADIUS_MD}px;
                }}
                NavButton QLabel#num {{
                    background-color: {COLOR_SUCCESS};
                    border-radius: 10px;
                    color: #ffffff;
                    font-size: 11px;
                    font-weight: 600;
                    border: none;
                }}
                NavButton QLabel#navText {{
                    color: rgba(0,200,83,0.8);
                    font-size: 13px;
                    font-weight: 500;
                    background: transparent;
                    border: none;
                }}
            """)
        else:  # default
            bg = OVERLAY2_HEX if self._hovered else "transparent"
            self.setStyleSheet(f"""
                NavButton {{
                    background-color: {bg};
                    border: 1px solid transparent;
                    border-radius: {RADIUS_MD}px;
                }}
                NavButton QLabel#num {{
                    background-color: {OVERLAY2_HEX};
                    border: 1px solid {BORDER_HEX};
                    border-radius: 10px;
                    color: {TEXT_SECONDARY};
                    font-size: 11px;
                    font-weight: 500;
                }}
                NavButton QLabel#navText {{
                    color: {TEXT_SECONDARY};
                    font-size: 13px;
                    font-weight: 500;
                    background: transparent;
                    border: none;
                }}
            """)


class StatusPill(QFrame):
    """
    Пилюля статуса в хедере: [●dot] [text]
    States: 'offline' | 'online' | 'busy'
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()
        self.setStyleSheet(f"""
            StatusPill {{
                background-color: {OVERLAY_HEX};
                border: 1px solid {BORDER_HEX};
                border-radius: 20px;
            }}
        """)
        self.set_status("offline", "Не авторизован")

    def _build(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 4, 12, 4)
        layout.setSpacing(7)

        self._dot = QLabel()
        self._dot.setFixedSize(7, 7)
        layout.addWidget(self._dot)

        self._lbl = QLabel()
        self._lbl.setStyleSheet(
            f"color: {TEXT_SECONDARY}; font-size: 12px;"
            " background: transparent; border: none;"
        )
        layout.addWidget(self._lbl)

    def set_status(self, state: str, text: str) -> None:
        """state: 'offline' | 'online' | 'busy'"""
        self._lbl.setText(text)
        if state == "online":
            color = COLOR_SUCCESS
            shadow = f"0 0 6px {COLOR_SUCCESS}"
        elif state == "busy":
            color = COLOR_WARNING
        else:
            color = TEXT_SECONDARY

        self._dot.setStyleSheet(f"""
            QLabel {{
                background-color: {color};
                border-radius: 3px;
                border: none;
            }}
        """)


class ToastWidget(QWidget):
    """
    Всплывающее уведомление. Автоматически исчезает через duration мс.
    Тип: 'info' | 'success' | 'warning' | 'error'
    """
    _ICONS = {"success": "✓", "error": "✕", "warning": "⚠", "info": "ℹ"}
    _COLORS = {
        "success": COLOR_SUCCESS,
        "error":   COLOR_ERROR,
        "warning": COLOR_WARNING,
        "info":    ACCENT_ORANGE,
    }

    def __init__(self, message: str, toast_type: str = "info",
                 duration: int = 3200, parent=None):
        super().__init__(parent)
        self._build(message, toast_type)
        QTimer.singleShot(duration, self.deleteLater)

    def _build(self, message: str, toast_type: str) -> None:
        color = self._COLORS.get(toast_type, ACCENT_ORANGE)
        icon = self._ICONS.get(toast_type, "ℹ")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 9, 14, 9)
        layout.setSpacing(9)

        icon_lbl = QLabel(icon)
        icon_lbl.setStyleSheet(
            f"color: {color}; font-size: 14px; background: transparent; border: none;"
        )
        layout.addWidget(icon_lbl)

        msg_lbl = QLabel(message)
        msg_lbl.setStyleSheet(
            f"color: {TEXT_PRIMARY}; font-size: 12px;"
            " background: transparent; border: none;"
        )
        msg_lbl.setWordWrap(True)
        layout.addWidget(msg_lbl, 1)

        self.setStyleSheet(f"""
            ToastWidget {{
                background-color: rgba(28,28,28,0.97);
                border: 1px solid {BORDER_HEX};
                border-left: 3px solid {color};
                border-radius: {RADIUS_MD}px;
            }}
        """)
        self.setFixedWidth(280)
        self.adjustSize()


# ══════════════════════════════════════════════════════════════════════════════
# SETTINGS PANEL  (UI-2)  — заменяет ParseSettingsScreen на вкладке 2
# ══════════════════════════════════════════════════════════════════════════════

class SettingsPanel(QWidget):
    """
    Панель настроек парсера (UI-2 redesign).
    Полностью заменяет ParseSettingsScreen, сохраняя тот же публичный API:

    Signals:
        parse_requested(object)         — ParseParams
        load_members_requested(object)  — chat dict
        log_message(str)

    Methods:
        set_chat(chat)
        populate_members(users)
        get_params() → Optional[ParseParams]
        set_parsing(active)

    Attributes:
        _current_chat  — словарь выбранного чата (читается из MainWindow)
    """

    parse_requested         = Signal(object)
    load_members_requested  = Signal(object)
    log_message             = Signal(str)

    def __init__(self, cfg: "AppConfig | None" = None, parent=None):
        super().__init__(parent)
        self._cfg           = cfg
        self._current_chat: Optional[dict] = None
        self._user_tags:    list[UserTag]   = []
        self._user_mode:    str             = "messages-only"
        self._split_mode:   str             = "none"
        self._split_buttons: list[SplitModeButton] = []
        self._parsing:      bool            = False
        self._build()
        if cfg:
            self._restore_from_cfg(cfg)

    def _restore_from_cfg(self, cfg) -> None:
        """Восстанавливает последние настройки из AppConfig после сборки UI."""
        # Режим разбивки
        if cfg.split_mode and cfg.split_mode != "none":
            for btn in self._split_buttons:
                if btn.mode == cfg.split_mode:
                    btn.setChecked(True)
                    self._split_mode = cfg.split_mode
                    break

        # Медиафильтр — cfg.media_filter хранит ключи: ["photo", "video", ...]
        # Маппинг ключ → атрибут кнопки
        media_map = {
            "photo":      "_media_photo",
            "video":      "_media_video",
            "file":       "_media_file",
            "voice":      "_media_voice",
            "video_note": "_media_round",
        }
        if cfg.media_filter is not None:
            active_keys = set(cfg.media_filter)
            for key, attr in media_map.items():
                btn = getattr(self, attr, None)
                if btn is not None:
                    btn.setActive(key in active_keys)

    # ──────────────────────────────────────────────────────────────────────
    # ПОСТРОЕНИЕ UI
    # ──────────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(f"""
            QScrollArea {{ background: transparent; border: none; }}
            QScrollBar:vertical {{
                background: {OVERLAY_HEX}; width: 6px; border-radius: 3px;
            }}
            QScrollBar::handle:vertical {{
                background: {OVERLAY2_HEX}; border-radius: 3px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        """)

        content = QWidget()
        content.setStyleSheet("background: transparent;")
        cl = QVBoxLayout(content)
        cl.setContentsMargins(18, 18, 18, 18)
        cl.setSpacing(12)

        cl.addWidget(self._build_chat_info())
        cl.addWidget(self._build_media_section())
        cl.addWidget(self._build_stt_section())
        cl.addWidget(self._build_date_section())
        cl.addWidget(self._build_members_section())
        cl.addWidget(self._build_split_section())
        cl.addWidget(self._build_export_section())
        cl.addWidget(self._build_options_section())
        cl.addStretch(1)

        scroll.setWidget(content)
        outer.addWidget(scroll)

    # ── Вспомогательные ───────────────────────────────────────────────────

    def _card(self) -> tuple[ModernCard, QVBoxLayout]:
        card = ModernCard()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)
        return card, layout

    def _option_row(self, label: str, toggle: ToggleSwitch) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)
        lbl = QLabel(label)
        lbl.setStyleSheet(
            f"color: {TEXT_PRIMARY}; font-size: 13px; background: transparent;"
        )
        row.addWidget(lbl)
        row.addStretch(1)
        row.addWidget(toggle)
        return row

    # ── Секции ────────────────────────────────────────────────────────────

    def _build_chat_info(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet(f"""
            QWidget {{
                background-color: {OVERLAY2_HEX};
                border: 1px dashed rgba(255,255,255,0.1);
                border-radius: {RADIUS_MD}px;
            }}
        """)
        lay = QHBoxLayout(w)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(10)

        lbl_caption = QLabel("Чат:")
        lbl_caption.setStyleSheet(
            f"color: {TEXT_SECONDARY}; font-size: 12px; background: transparent;"
        )
        lay.addWidget(lbl_caption)

        self._chat_label = QLabel("не выбран")
        self._chat_label.setStyleSheet(f"""
            QLabel {{
                color: {ACCENT_ORANGE};
                font-size: 13px;
                font-weight: 600;
                background: transparent;
            }}
        """)
        self._chat_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        lay.addWidget(self._chat_label, 1)
        return w

    def _build_media_section(self) -> ModernCard:
        card, layout = self._card()
        layout.addWidget(SectionTitle("📥", "Медиафайлы", accent=True))

        grid = QWidget()
        grid.setStyleSheet("background: transparent;")
        gl = QGridLayout(grid)
        gl.setSpacing(8)
        gl.setContentsMargins(0, 0, 0, 0)

        self._media_photo = MediaButton("📷", "Фото",    "photo",       True)
        self._media_video = MediaButton("🎬", "Видео",   "video",       True)
        self._media_file  = MediaButton("📁", "Файлы",   "file",        False)
        self._media_voice = MediaButton("🎤", "Голос",   "voice",       True)
        self._media_round = MediaButton("📹", "Кружки",  "video_note",  True)

        for col, btn in enumerate([
            self._media_photo, self._media_video, self._media_file,
            self._media_voice, self._media_round,
        ]):
            btn.setFixedHeight(72)
            gl.addWidget(btn, 0, col)

        layout.addWidget(grid)
        return card

    def _build_stt_section(self) -> ModernCard:
        card, layout = self._card()
        layout.addWidget(SectionTitle("🎙️", "Распознавание речи"))

        chips_row = QHBoxLayout()
        chips_row.setSpacing(8)

        self._stt_voice = ChipButton("🎤", "Голосовые",  "voice",       True)
        self._stt_round = ChipButton("📹", "Кружочки",   "video_note",  True)

        chips_row.addWidget(self._stt_voice)
        chips_row.addWidget(self._stt_round)
        chips_row.addStretch(1)
        layout.addLayout(chips_row)
        return card

    def _build_date_section(self) -> ModernCard:
        card, layout = self._card()
        layout.addWidget(SectionTitle("📅", "Период"))
        self._date_widget = DateRangeWidget()
        layout.addWidget(self._date_widget)
        return card

    def _build_members_section(self) -> ModernCard:
        card, layout = self._card()
        layout.addWidget(SectionTitle("👥", "Участники"))

        # Режим поиска
        mode_row = QHBoxLayout()
        mode_row.setSpacing(8)

        self._mode_btn_messages = QPushButton("Только в теме")
        self._mode_btn_all      = QPushButton("Все темы")

        for btn in (self._mode_btn_messages, self._mode_btn_all):
            btn.setCheckable(True)
            btn.setFixedHeight(28)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {OVERLAY2_HEX};
                    border: 1px solid {BORDER_HEX};
                    border-radius: {RADIUS_MD}px;
                    color: {TEXT_SECONDARY};
                    font-size: 12px;
                    padding: 0 12px;
                }}
                QPushButton:checked {{
                    background-color: {ACCENT_SOFT_ORANGE};
                    border-color: {ACCENT_ORANGE};
                    color: {ACCENT_ORANGE};
                    font-weight: 600;
                }}
                QPushButton:hover:!checked {{
                    background-color: {OVERLAY_HEX};
                }}
            """)

        self._mode_btn_messages.setChecked(True)
        self._mode_btn_messages.clicked.connect(
            lambda: self._set_user_mode("messages-only")
        )
        self._mode_btn_all.clicked.connect(
            lambda: self._set_user_mode("all-threads")
        )

        mode_row.addWidget(self._mode_btn_messages)
        mode_row.addWidget(self._mode_btn_all)
        mode_row.addStretch(1)
        layout.addLayout(mode_row)

        # Кнопка загрузки
        self._load_members_btn = QPushButton("👥  Загрузить участников")
        self._load_members_btn.setEnabled(False)
        self._load_members_btn.setFixedHeight(34)
        self._load_members_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._load_members_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {OVERLAY2_HEX};
                border: 1px solid {BORDER_HEX};
                border-radius: {RADIUS_MD}px;
                color: {TEXT_SECONDARY};
                font-size: 12px;
            }}
            QPushButton:hover:enabled {{
                background-color: {OVERLAY_HEX};
                color: {TEXT_PRIMARY};
            }}
            QPushButton:disabled {{
                color: rgba(255,255,255,0.25);
            }}
        """)
        self._load_members_btn.clicked.connect(self._on_load_members_clicked)
        layout.addWidget(self._load_members_btn)

        # Контейнер тегов (прокручиваемый)
        self._tags_scroll = QScrollArea()
        self._tags_scroll.setFixedHeight(56)
        self._tags_scroll.setWidgetResizable(True)
        self._tags_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._tags_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self._tags_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._tags_scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
        )

        self._tags_container = QWidget()
        self._tags_container.setStyleSheet("background: transparent;")
        self._tags_layout = QHBoxLayout(self._tags_container)
        self._tags_layout.setContentsMargins(0, 4, 0, 4)
        self._tags_layout.setSpacing(6)
        self._tags_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self._tags_scroll.setWidget(self._tags_container)
        layout.addWidget(self._tags_scroll)

        return card

    def _build_split_section(self) -> ModernCard:
        card, layout = self._card()
        layout.addWidget(SectionTitle("📄", "Разбивка документа"))

        grid = QWidget()
        grid.setStyleSheet("background: transparent;")
        gl = QGridLayout(grid)
        gl.setSpacing(8)
        gl.setContentsMargins(0, 0, 0, 0)

        self._split_none  = SplitModeButton("📄", "Единый",    "none",  True)
        self._split_day   = SplitModeButton("🗓",  "По дням",   "day",   False)
        self._split_month = SplitModeButton("📆",  "Месяцы",    "month", False)
        self._split_post  = SplitModeButton("📋",  "Посты",     "post",  False)

        self._split_buttons = [
            self._split_none, self._split_day,
            self._split_month, self._split_post,
        ]

        for col, btn in enumerate(self._split_buttons):
            btn.setFixedHeight(72)
            btn.clicked.connect(
                lambda checked, m=btn.mode: self._on_split_mode(m)
            )
            gl.addWidget(btn, 0, col)

        layout.addWidget(grid)
        return card

    def _build_export_section(self) -> ModernCard:
        card, layout = self._card()
        layout.addWidget(SectionTitle("💾", "Формат экспорта"))

        chips_row = QHBoxLayout()
        chips_row.setSpacing(8)

        # ── Независимые toggle-чипы (НЕ radio-group) ──
        # Каждая кнопка включается/выключается независимо.
        # Можно выбрать несколько форматов одновременно.
        _chip_qss = f"""
            QPushButton {{
                background-color: {OVERLAY2_HEX};
                border: 1px solid {BORDER_HEX};
                border-radius: {RADIUS_MD}px;
                color: {TEXT_SECONDARY};
                font-size: 13px;
                font-weight: 600;
                padding: 0 18px;
                min-height: 34px;
            }}
            QPushButton:checked {{
                background-color: {ACCENT_SOFT_ORANGE};
                border-color: {ACCENT_ORANGE};
                color: {ACCENT_ORANGE};
            }}
            QPushButton:hover:!checked {{
                background-color: {OVERLAY_HEX};
                color: {TEXT_PRIMARY};
            }}
        """

        self._fmt_docx = QPushButton("DOCX")
        self._fmt_json = QPushButton("JSON")
        self._fmt_md   = QPushButton("MD")
        self._fmt_html = QPushButton("HTML")

        for btn in (self._fmt_docx, self._fmt_json, self._fmt_md, self._fmt_html):
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(_chip_qss)

        self._fmt_docx.setChecked(True)   # По умолчанию только DOCX

        chips_row.addWidget(self._fmt_docx)
        chips_row.addWidget(self._fmt_json)
        chips_row.addWidget(self._fmt_md)
        chips_row.addWidget(self._fmt_html)
        chips_row.addStretch(1)
        layout.addLayout(chips_row)

        hint = QLabel("Можно выбрать несколько форматов одновременно")
        hint.setStyleSheet(
            f"color: {TEXT_SECONDARY}; font-size: 11px; background: transparent;"
        )
        layout.addWidget(hint)

        # ── AI-split toggle (только для MD и JSON) ──────────────────────
        self._toggle_ai_split = ToggleSwitch(checked=False)
        ai_row = self._option_row("🤖  Адаптировать для ИИ (разбивать по 300к слов)", self._toggle_ai_split)
        layout.addLayout(ai_row)

        ai_hint = QLabel("Разбивка применяется только к MD и JSON. DOCX всегда единый файл.")
        ai_hint.setStyleSheet(
            f"color: {TEXT_SECONDARY}; font-size: 11px; background: transparent;"
        )
        layout.addWidget(ai_hint)
        return card

    def get_export_formats(self) -> list:
        """Возвращает список активных форматов экспорта. Минимум один — docx."""
        fmt = []
        if self._fmt_docx.isChecked():
            fmt.append("docx")
        if self._fmt_json.isChecked():
            fmt.append("json")
        if self._fmt_md.isChecked():
            fmt.append("md")
        if self._fmt_html.isChecked():
            fmt.append("html")
        return fmt or ["docx"]   # fallback

    def get_ai_split(self) -> bool:
        """Возвращает состояние чекбокса 'Адаптировать для ИИ'."""
        return self._toggle_ai_split.isChecked()

    def _build_options_section(self) -> ModernCard:
        card, layout = self._card()
        layout.addWidget(SectionTitle("⚙️", "Параметры"))

        self._toggle_comments   = ToggleSwitch(checked=False)
        self._toggle_redownload = ToggleSwitch(checked=False)
        self._toggle_takeout    = ToggleSwitch(checked=False)

        layout.addLayout(self._option_row("Включить комментарии", self._toggle_comments))
        layout.addLayout(self._option_row("Перекачать медиа",    self._toggle_redownload))
        layout.addLayout(self._option_row("⚡ Takeout API (быстрее при VPN)", self._toggle_takeout))
        return card

    # ──────────────────────────────────────────────────────────────────────
    # ВНУТРЕННИЕ СЛОТЫ
    # ──────────────────────────────────────────────────────────────────────

    def _set_user_mode(self, mode: str) -> None:
        self._user_mode = mode
        self._mode_btn_messages.setChecked(mode == "messages-only")
        self._mode_btn_all.setChecked(mode == "all-threads")

    def _on_split_mode(self, mode: str) -> None:
        self._split_mode = mode
        for btn in self._split_buttons:
            btn.setChecked(btn.mode == mode)

    def _on_load_members_clicked(self) -> None:
        if self._current_chat:
            self.load_members_requested.emit(self._current_chat)

    # ──────────────────────────────────────────────────────────────────────
    # ПУБЛИЧНЫЙ API (совместим с ParseSettingsScreen)
    # ──────────────────────────────────────────────────────────────────────

    def set_chat(self, chat: dict) -> None:
        self._current_chat = chat
        title = chat.get("title", "")
        short = (title[:38] + "…") if len(title) > 38 else title
        self._chat_label.setText(short or "не выбран")
        self._load_members_btn.setEnabled(True)

    def populate_members(self, users: list[dict]) -> None:
        # Очистить старые теги
        self._user_tags.clear()
        while self._tags_layout.count():
            item = self._tags_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Тег «Все»
        all_tag = UserTag("Все", user_id=0, is_all=True, selected=True)
        self._tags_layout.addWidget(all_tag)
        self._user_tags.append(all_tag)

        # Теги участников
        for user in users:
            uid  = user.get("id", 0)
            name = (
                user.get("username")
                or user.get("first_name")
                or str(uid)
            )
            tag = UserTag(name, user_id=uid, is_all=False, selected=False)
            self._tags_layout.addWidget(tag)
            self._user_tags.append(tag)

        self._tags_layout.addStretch(1)
        self.log_message.emit(f"Загружено участников: {len(users)}")

    def get_params(self) -> Optional[ParseParams]:
        if self._current_chat is None:
            return None

        # Выбранные user_ids (без «Все»-тега)
        user_ids: list[int] = []
        all_selected = True
        for tag in self._user_tags:
            if tag.is_all:
                if not tag.isChecked():
                    all_selected = False
            elif tag.isChecked():
                user_ids.append(tag.user_id)
        if all_selected:
            user_ids = []

        # Даты
        date_from = None
        date_to   = None
        start_dt, end_dt = self._date_widget.get_date_range()
        if start_dt is not None:
            date_from = start_dt.date()
        if end_dt is not None:
            date_to = end_dt.date()

        return ParseParams(
            chat=self._current_chat,
            download_photo       = self._media_photo.isChecked(),
            download_video       = self._media_video.isChecked(),
            download_file        = self._media_file.isChecked(),
            download_voice       = self._media_voice.isChecked(),
            download_videomessage= self._media_round.isChecked(),
            stt_voice            = self._stt_voice.isActive(),
            stt_videomessage     = self._stt_round.isActive(),
            stt_video            = False,
            date_from            = date_from,
            date_to              = date_to,
            user_filter_mode     = self._user_mode,
            user_ids             = user_ids,
            split_mode           = self._split_mode,
            include_comments     = self._toggle_comments.isChecked(),
            re_download          = self._toggle_redownload.isChecked(),
            use_takeout          = self._toggle_takeout.isChecked(),
        )

    def set_parsing(self, active: bool) -> None:
        self._parsing = active
        self.setEnabled(not active)


# ══════════════════════════════════════════════════════════════════════════════
# LOGOUT WORKER
# ══════════════════════════════════════════════════════════════════════════════

class LogoutWorker(QThread):
    """
    Выход из аккаунта Telegram: client.log_out() + удаление session-файла.

    Signals:
        logout_done()      — успешный выход (session удалена)
        log_message(str)   — текстовые сообщения для лога
        error(str)         — ошибка (файл не удалён / logout failed)
    """

    logout_done  = Signal()
    log_message  = Signal(str)
    error        = Signal(str)

    def __init__(self, cfg: AppConfig, parent=None):
        super().__init__(parent)
        self._cfg = cfg

    def run(self) -> None:
        import asyncio, os
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(self._do_logout())
        except Exception as exc:
            self.error.emit(f"Ошибка выхода: {exc}")
        finally:
            loop.close()

    async def _do_logout(self) -> None:
        import os
        from telethon import TelegramClient

        import gc
        cfg = self._cfg
        self.log_message.emit("⏻ Выход из Telegram...")
        client = TelegramClient(cfg.session_path, cfg.api_id_int, cfg.api_hash)
        try:
            await client.connect()
            await client.log_out()
            self.log_message.emit("✅ Сессия завершена на сервере")
        except Exception as exc:
            self.log_message.emit(f"⚠️ log_out error (продолжаем): {exc}")
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass
            # Явно закрываем SQLite-соединение session-файла
            try:
                client.session.close()
            except Exception:
                pass
            del client
            gc.collect()

        # Удалить session-файл
        session_file = str(cfg.session_path)
        if not session_file.endswith(".session"):
            session_file += ".session"
        try:
            if os.path.exists(session_file):
                os.remove(session_file)
                self.log_message.emit("🗑 Session-файл удалён")
        except OSError as exc:
            self.error.emit(f"Не удалось удалить session-файл: {exc}")
            return

        self.logout_done.emit()


# ══════════════════════════════════════════════════════════════════════════════
# ФАБРИЧНАЯ ФУНКЦИЯ (вызывается из main.py)
# ══════════════════════════════════════════════════════════════════════════════

def create_main_window(cfg: AppConfig, db: DBManager) -> "MainWindow":
    window = MainWindow(cfg, db)
    return window


# ══════════════════════════════════════════════════════════════════════════════
# MAIN WINDOW
# ══════════════════════════════════════════════════════════════════════════════

class MainWindow(QMainWindow):

    def __init__(self, cfg: AppConfig, db: DBManager):
        super().__init__()
        self._cfg = cfg
        self._db  = db
        self._active_workers: list[QThread] = []
        self._current_step: int = 0
        self._last_collect_result = None  # сохраняется в _run_stt для _on_stt_finished_slot

        self._setup_window()
        self._build_ui()
        self._connect_signals()
        self._set_step(0)

        logger.info("MainWindow initialized (v4.0 redesign)")

    # ──────────────────────────────────────────────────────────────────────
    # НАСТРОЙКА ОКНА
    # ──────────────────────────────────────────────────────────────────────

    def _setup_window(self) -> None:
        self.setWindowTitle("Rozitta Parser")
        self.setMinimumSize(1280, 720)
        self.resize(1600, 900)
        self.setStyleSheet(f"""
            QMainWindow {{
                background-color: {BG_PRIMARY};
            }}
            QWidget {{
                font-family: {FONT_FAMILY};
                color: {TEXT_PRIMARY};
            }}
        """)

    # ──────────────────────────────────────────────────────────────────────
    # ПОСТРОЕНИЕ UI
    # ──────────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        central = QWidget()
        central.setObjectName("centralWidget")
        central.setStyleSheet(
            f"QWidget#centralWidget {{ background-color: {BG_PRIMARY}; }}"
        )
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Header ────────────────────────────────────────────────────────
        root.addWidget(self._build_header())

        # ── Workspace ─────────────────────────────────────────────────────
        workspace = QWidget()
        workspace.setStyleSheet("background-color: transparent;")
        ws_layout = QHBoxLayout(workspace)
        ws_layout.setContentsMargins(0, 0, 0, 0)
        ws_layout.setSpacing(0)

        ws_layout.addWidget(self._build_sidebar())
        ws_layout.addWidget(self._vline())
        self._stack = self._build_main_content()
        ws_layout.addWidget(self._stack, 1)
        ws_layout.addWidget(self._vline())
        ws_layout.addWidget(self._build_right_panel())

        root.addWidget(workspace, 1)

    # ── Header ────────────────────────────────────────────────────────────

    def _build_header(self) -> QWidget:
        header = QWidget()
        header.setFixedHeight(52)
        header.setStyleSheet(f"""
            QWidget {{
                background-color: rgba(22,22,22,0.90);
                border-bottom: 1px solid {BORDER_HEX};
            }}
        """)

        layout = QHBoxLayout(header)
        layout.setContentsMargins(20, 0, 20, 0)
        layout.setSpacing(12)

        # Logo с градиентом через rich text
        logo = QLabel(
            f'<span style="color:{ACCENT_PINK}; font-size:17px; font-weight:700;">'
            f'✦ Rozitta</span>'
            f'<span style="color:rgba(255,255,255,0.35); font-size:17px;"> / </span>'
            f'<span style="color:{TEXT_PRIMARY}; font-size:17px; font-weight:700;">'
            f'Parser</span>'
        )
        logo.setTextFormat(Qt.TextFormat.RichText)
        logo.setStyleSheet("background: transparent; border: none;")
        layout.addWidget(logo)

        layout.addStretch(1)

        self._status_pill = StatusPill()
        layout.addWidget(self._status_pill)

        return header

    # ── Sidebar ───────────────────────────────────────────────────────────

    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setFixedWidth(196)
        sidebar.setStyleSheet(f"background-color: rgba(18,18,18,0.6);")

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(10, 14, 10, 14)
        layout.setSpacing(3)

        # Метка секции
        section_lbl = QLabel("ШАГИ")
        section_lbl.setStyleSheet(f"""
            QLabel {{
                color: rgba(255,255,255,0.3);
                font-size: 10px;
                font-weight: 600;
                letter-spacing: 1.3px;
                padding: 6px 10px 3px;
                background: transparent;
            }}
        """)
        layout.addWidget(section_lbl)

        # Nav кнопки
        self._nav_auth     = NavButton(1, "Авторизация")
        self._nav_chats    = NavButton(2, "Чаты")
        self._nav_settings = NavButton(3, "Настройки")

        self._nav_auth.clicked.connect(lambda: self._on_nav_clicked(0))
        self._nav_chats.clicked.connect(lambda: self._on_nav_clicked(1))
        self._nav_settings.clicked.connect(lambda: self._on_nav_clicked(2))

        layout.addWidget(self._nav_auth)
        layout.addWidget(self._nav_chats)
        layout.addWidget(self._nav_settings)

        layout.addStretch(1)

        # Инфо о выбранном чате
        info_box = QWidget()
        info_box.setStyleSheet(f"""
            QWidget {{
                background-color: rgba(0,0,0,0.2);
                border: 1px dashed rgba(255,255,255,0.1);
                border-radius: {RADIUS_MD}px;
            }}
        """)
        info_layout = QVBoxLayout(info_box)
        info_layout.setContentsMargins(10, 10, 10, 10)
        info_layout.setSpacing(4)

        info_caption = QLabel("Выбранный чат")
        info_caption.setStyleSheet(
            f"color: {TEXT_SECONDARY}; font-size: 10px;"
            " background: transparent; border: none;"
        )
        info_layout.addWidget(info_caption)

        self._sidebar_chat_name = QLabel("не выбран")
        self._sidebar_chat_name.setStyleSheet(f"""
            QLabel {{
                color: {ACCENT_ORANGE};
                font-size: 12px;
                font-weight: 500;
                background: transparent;
                border: none;
            }}
        """)
        self._sidebar_chat_name.setWordWrap(True)
        info_layout.addWidget(self._sidebar_chat_name)

        layout.addWidget(info_box)

        # Кнопка выхода (скрыта до авторизации)
        self._logout_btn = QPushButton("⏻  Выйти")
        self._logout_btn.setVisible(False)
        self._logout_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._logout_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: rgba(220, 50, 50, 0.15);
                color: #E05555;
                border: 1px solid rgba(220, 50, 50, 0.35);
                border-radius: {RADIUS_MD}px;
                font-size: 12px;
                font-weight: 500;
                padding: 6px 10px;
                margin-top: 6px;
            }}
            QPushButton:hover {{
                background-color: rgba(220, 50, 50, 0.30);
                border-color: rgba(220, 50, 50, 0.60);
            }}
            QPushButton:pressed {{
                background-color: rgba(220, 50, 50, 0.45);
            }}
        """)
        self._logout_btn.clicked.connect(self._on_logout_clicked)
        layout.addWidget(self._logout_btn)

        return sidebar

    # ── Main content ──────────────────────────────────────────────────────

    def _build_main_content(self) -> QStackedWidget:
        stack = QStackedWidget()
        stack.setStyleSheet(f"QStackedWidget {{ background-color: {BG_PRIMARY}; }}")

        # Tab 0 — Авторизация
        tab0 = QWidget()
        tab0.setStyleSheet("background: transparent;")
        lay0 = QVBoxLayout(tab0)
        lay0.setContentsMargins(18, 18, 18, 18)
        self._auth_screen = AuthScreen(self._cfg)
        lay0.addWidget(self._auth_screen)
        lay0.addStretch(1)
        stack.addWidget(tab0)

        # Tab 1 — Чаты
        tab1 = QWidget()
        tab1.setStyleSheet("background: transparent;")
        lay1 = QVBoxLayout(tab1)
        lay1.setContentsMargins(18, 18, 18, 18)
        self._chats_screen = ChatsScreen(self._cfg)
        lay1.addWidget(self._chats_screen)
        stack.addWidget(tab1)

        # Tab 2 — Настройки парсинга (SettingsPanel UI-2)
        tab2 = QWidget()
        tab2.setStyleSheet("background: transparent;")
        lay2 = QVBoxLayout(tab2)
        lay2.setContentsMargins(0, 0, 0, 0)
        self._settings_screen = SettingsPanel(cfg=self._cfg)
        lay2.addWidget(self._settings_screen)
        stack.addWidget(tab2)

        return stack

    # ── Right panel ───────────────────────────────────────────────────────

    def _build_right_panel(self) -> QWidget:
        panel = QWidget()
        panel.setFixedWidth(308)
        panel.setStyleSheet("background-color: rgba(16,16,16,0.45);")

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Character section ──────────────────────────────────────────────
        char_wrap = QWidget()
        char_wrap.setStyleSheet(f"""
            QWidget {{
                background-color: rgba(0,0,0,0.12);
                border-bottom: 1px solid {BORDER_HEX};
            }}
        """)
        char_layout = QVBoxLayout(char_wrap)
        char_layout.setContentsMargins(14, 14, 14, 14)
        char_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._rozetta = RozittaWidget()
        self._rozetta.set_image_path('resource/rozitta_idle.png') # Загружаем аватар персонажа.

        self._greeting_sound = QSoundEffect()
        self._greeting_sound.setSource(QUrl.fromLocalFile("resource/frog-croaking-x1.wav"))
        self._greeting_sound.setVolume(0.8)

        self._rozetta.clicked.connect(lambda: self._greeting_sound.play())

        char_layout.addWidget(self._rozetta, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(char_wrap)

        # ── Log section (flex 1) ───────────────────────────────────────────
        log_wrap = QWidget()
        log_wrap.setStyleSheet("background: transparent;")
        log_layout = QVBoxLayout(log_wrap)
        log_layout.setContentsMargins(13, 10, 13, 4)
        log_layout.setSpacing(6)

        log_heading = QLabel("⚙  Журнал")
        log_heading.setStyleSheet(f"""
            QLabel {{
                color: {TEXT_PRIMARY};
                font-size: 13px;
                font-weight: 600;
                background: transparent;
            }}
        """)
        log_layout.addWidget(log_heading)

        self._log = LogWidget()
        log_layout.addWidget(self._log, 1)
        layout.addWidget(log_wrap, 1)

        # ── Progress section ───────────────────────────────────────────────
        prog_wrap = QWidget()
        prog_wrap.setStyleSheet("background: transparent;")
        prog_layout = QVBoxLayout(prog_wrap)
        prog_layout.setContentsMargins(13, 0, 13, 8)
        prog_layout.setSpacing(4)

        prog_row = QHBoxLayout()
        prog_row.setSpacing(0)

        prog_caption = QLabel("Прогресс")
        prog_caption.setStyleSheet(
            f"color: {TEXT_SECONDARY}; font-size: 11px; background: transparent;"
        )
        prog_row.addWidget(prog_caption)
        prog_row.addStretch(1)

        self._progress_pct = QLabel("0%")
        self._progress_pct.setStyleSheet(
            f"color: {TEXT_SECONDARY}; font-size: 11px; background: transparent;"
        )
        prog_row.addWidget(self._progress_pct)
        prog_layout.addLayout(prog_row)

        self._progress_bar = QProgressBar()
        self._progress_bar.setFixedHeight(5)
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setStyleSheet(QSS_PROGRESS)
        prog_layout.addWidget(self._progress_bar)
        layout.addWidget(prog_wrap)

        # ── Start / Stop buttons ───────────────────────────────────────────
        start_wrap = QWidget()
        start_wrap.setStyleSheet("background: transparent;")
        start_layout = QVBoxLayout(start_wrap)
        start_layout.setContentsMargins(13, 6, 13, 13)
        start_layout.setSpacing(0)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self._start_btn = QPushButton("▶  НАЧАТЬ ПАРСИНГ")
        self._start_btn.setFixedHeight(40)
        self._start_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {ACCENT_ORANGE};
                border: 1px solid {ACCENT_ORANGE};
                border-radius: {RADIUS_MD}px;
                color: #ffffff;
                font-size: 13px;
                font-weight: 600;
                font-family: {FONT_FAMILY};
            }}
            QPushButton:hover {{
                background-color: #E08500;
                border-color: #E08500;
            }}
            QPushButton:pressed {{
                background-color: #C07400;
            }}
            QPushButton:disabled {{
                background-color: #5A3500;
                border-color: #5A3500;
                color: #888888;
            }}
        """)
        btn_row.addWidget(self._start_btn, 1)

        self._stop_btn = QPushButton("⏹  Стоп")
        self._stop_btn.setFixedHeight(40)
        self._stop_btn.setVisible(False)
        self._stop_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: #8B1A1A;
                border: 1px solid #B02020;
                border-radius: {RADIUS_MD}px;
                color: #ffffff;
                font-size: 13px;
                font-weight: 600;
                font-family: {FONT_FAMILY};
                min-width: 80px;
            }}
            QPushButton:hover {{
                background-color: #A02020;
                border-color: #C03030;
            }}
            QPushButton:pressed {{
                background-color: #6B1010;
            }}
        """)
        btn_row.addWidget(self._stop_btn, 0)

        start_layout.addLayout(btn_row)
        layout.addWidget(start_wrap)

        return panel

    # ── Вспомогательные ───────────────────────────────────────────────────

    def _vline(self) -> QFrame:
        """Тонкий вертикальный разделитель."""
        line = QFrame()
        line.setFrameShape(QFrame.Shape.VLine)
        line.setFixedWidth(1)
        line.setStyleSheet(f"background-color: {BORDER_HEX}; border: none;")
        return line

    # ──────────────────────────────────────────────────────────────────────
    # ПОДКЛЮЧЕНИЕ СИГНАЛОВ
    # ──────────────────────────────────────────────────────────────────────

    def _connect_signals(self) -> None:
        # AuthScreen
        self._auth_screen.auth_complete.connect(self._on_auth_complete)
        self._auth_screen.log_message.connect(self._log.append_info)
        self._auth_screen.character_state.connect(self._rozetta.set_state)
        self._auth_screen.character_tip.connect(self._rozetta.set_tip)

        # ChatsScreen
        self._chats_screen.chat_selected.connect(self._on_chat_selected)
        self._chats_screen.log_message.connect(self._log.append_info)
        self._chats_screen.request_topics.connect(self._on_request_topics)
        self._chats_screen.refresh_requested.connect(self._on_refresh_chats)

        # SettingsPanel
        self._settings_screen.parse_requested.connect(self._on_parse_requested)
        self._settings_screen.load_members_requested.connect(self._on_load_members)
        self._settings_screen.log_message.connect(self._log.append_info)

        # RozittaWidget
        self._rozetta.clicked.connect(
            lambda: self._log.append_info("Привет! Я Розитта 👋")
        )

        # StartBtn / StopBtn в правой панели
        self._start_btn.clicked.connect(self._on_start_btn_clicked)
        self._stop_btn.clicked.connect(self._on_stop_clicked)

    # ──────────────────────────────────────────────────────────────────────
    # НАВИГАЦИЯ
    # ──────────────────────────────────────────────────────────────────────

    def _on_nav_clicked(self, index: int) -> None:
        """Клик по NavBtn — переключить вкладку, если она уже достигнута."""
        if index <= self._current_step:
            self._switch_tab(index)

    def _switch_tab(self, index: int) -> None:
        """Переключить QStackedWidget + обновить NavBtn без смены _current_step."""
        self._stack.setCurrentIndex(index)
        nav_btns = [self._nav_auth, self._nav_chats, self._nav_settings]
        for i, btn in enumerate(nav_btns):
            if i < self._current_step:
                btn.set_state("done")
            elif i == index:
                btn.set_state("active")
            else:
                btn.set_state("default")

    def _set_step(self, index: int) -> None:
        """
        Установить текущий шаг и переключить вкладку.
          0 — Auth active
          1 — Chats active  (Auth done)
          2 — Settings active (Auth + Chats done)
          3 — Все done (парсинг завершён)
        """
        self._current_step = index
        tab_index = min(index, 2)
        self._stack.setCurrentIndex(tab_index)

        nav_btns = [self._nav_auth, self._nav_chats, self._nav_settings]
        for i, btn in enumerate(nav_btns):
            if i < index:
                btn.set_state("done")
            elif i == index:
                btn.set_state("active")
            else:
                btn.set_state("default")

    # ──────────────────────────────────────────────────────────────────────
    # СТАТУС
    # ──────────────────────────────────────────────────────────────────────

    def _set_status(self, state: str, text: str) -> None:
        """Обновить StatusPill в хедере. state: 'offline'|'online'|'busy'"""
        self._status_pill.set_status(state, text)

    # ──────────────────────────────────────────────────────────────────────
    # ТОСТЫ
    # ──────────────────────────────────────────────────────────────────────

    def _show_toast(self, message: str, toast_type: str = "info",
                    duration: int = 3200) -> None:
        """Показать всплывающее уведомление в правом верхнем углу."""
        toast = ToastWidget(message, toast_type, duration,
                            parent=self.centralWidget())
        toast.adjustSize()
        cw = self.centralWidget()
        x = cw.width() - toast.width() - 18
        # Смещаемся ниже уже существующих тостов
        active = sum(
            1 for c in cw.children()
            if isinstance(c, ToastWidget) and c is not toast and c.isVisible()
        )
        y = 60 + active * (toast.height() + 7)
        toast.move(x, y)
        toast.show()
        toast.raise_()

    # ──────────────────────────────────────────────────────────────────────
    # ПРОГРЕСС
    # ──────────────────────────────────────────────────────────────────────

    def _update_progress(self, value: int) -> None:
        self._progress_bar.setValue(value)
        self._progress_pct.setText(f"{value}%")

    # ──────────────────────────────────────────────────────────────────────
    # СЛОТЫ: АВТОРИЗАЦИЯ
    # ──────────────────────────────────────────────────────────────────────

    def _on_auth_complete(self, client, user) -> None:
        """
        AuthWorker завершил авторизацию.
        auth_complete = Signal(object, object) → (TelegramClient | None, User | None).
        """
        if user is None:
            return

        name = getattr(user, "first_name", "") or ""
        self._log.append_success(f"✅ Авторизован: {name}" if name else "✅ Авторизован")
        self._set_step(1)
        self._set_status("online", f"Авторизован: {name}" if name else "Авторизован")
        self._rozetta.set_state("success")
        self._rozetta.set_tip("Авторизация успешна!")
        self._show_toast("Авторизация прошла успешно!", "success")
        self._logout_btn.setVisible(True)

        # client всегда None — отключён внутри AuthWorker до эмита сигнала.
        # Дополнительный disconnect не нужен и опасен (cross-loop).
        # Задержка 300 мс: даём AuthWorker.run() завершить finally:loop.close()
        # и полностью освободить SQLite-файл сессии до старта ChatsWorker.
        from PySide6.QtCore import QTimer
        QTimer.singleShot(300, self._load_chats)

    # ──────────────────────────────────────────────────────────────────────
    # СЛОТЫ: ВЫХОД
    # ──────────────────────────────────────────────────────────────────────

    def _on_logout_clicked(self) -> None:
        self._logout_btn.setEnabled(False)
        self._log.append_info("⏻ Выход из аккаунта...")
        self._rozetta.set_state("process")
        self._rozetta.set_tip("Выхожу...")
        worker = LogoutWorker(self._cfg)
        worker.log_message.connect(self._log.append_info,    Qt.UniqueConnection)
        worker.logout_done.connect(self._on_logout_done,     Qt.UniqueConnection)
        worker.error.connect(self._on_logout_error,          Qt.UniqueConnection)
        self._start_worker(worker)

    def _on_logout_done(self) -> None:
        self._logout_btn.setVisible(False)
        self._logout_btn.setEnabled(True)
        self._set_status("offline", "Не авторизован")
        self._rozetta.set_state("idle")
        self._rozetta.set_tip("")
        self._sidebar_chat_name.setText("не выбран")
        self._auth_screen.reset()   # разблокировать форму и кнопку "Войти"
        self._set_step(0)
        self._log.append_success("✅ Выход выполнен. Авторизуйтесь снова.")
        self._show_toast("Выход выполнен", "success")

    def _on_logout_error(self, message: str) -> None:
        self._logout_btn.setEnabled(True)
        self._log.append_error(f"❌ {message}")
        self._rozetta.set_state("error")
        self._show_toast(message[:80], "error")

    # ──────────────────────────────────────────────────────────────────────
    # СЛОТЫ: ЧАТЫ
    # ──────────────────────────────────────────────────────────────────────

    def _load_chats(self, force_refresh: bool = False) -> None:
        from features.chats.ui import ChatsWorker
        worker = ChatsWorker(self._cfg, force_refresh=force_refresh)
        worker.chats_loaded.connect(self._on_chats_loaded,       Qt.UniqueConnection)
        worker.log_message.connect(self._log.append_info,        Qt.UniqueConnection)
        worker.error.connect(self._on_worker_error,              Qt.UniqueConnection)
        worker.character_state.connect(self._rozetta.set_state,  Qt.UniqueConnection)
        self._start_worker(worker)
        self._rozetta.set_state("process")
        self._rozetta.set_tip("Загружаю список чатов...")

    def _on_refresh_chats(self) -> None:
        self._load_chats(force_refresh=True)

    def _on_chats_loaded(self, chats: list) -> None:
        self._chats_screen.inject_chats(chats)
        self._rozetta.set_state("success")
        self._rozetta.set_tip(f"Загружено {len(chats)} чатов")
        self._log.append_success(f"✅ Загружено чатов: {len(chats)}")
        self._show_toast(f"Загружено {len(chats)} чатов", "success", 2000)

    def _on_chat_selected(self, chat: dict) -> None:
        self._settings_screen.set_chat(chat)
        self._set_step(2)
        title = chat.get("title", "")
        self._rozetta.set_tip(f"Выбран: {title}")
        short = title[:22] + "…" if len(title) > 22 else title
        self._sidebar_chat_name.setText(short)
        self._show_toast(f'Чат "{title}" выбран', "info", 2000)

        # Для каналов — лениво проверяем linked_chat_id при выборе,
        # а не при загрузке всего списка (экономит 3+ минуты)
        if chat.get("type") == "channel" and not chat.get("linked_chat_id"):
            from features.chats.ui import LinkedGroupWorker
            lw = LinkedGroupWorker(chat, self._cfg)
            lw.linked_found.connect(self._on_linked_group_found, Qt.UniqueConnection)
            lw.log_message.connect(self._log.append_info,        Qt.UniqueConnection)
            self._start_worker(lw)

    def _on_linked_group_found(self, updated_chat: dict) -> None:
        """Получен linked_chat_id — обновляем настройки парсера."""
        self._settings_screen.set_chat(updated_chat)
        title = updated_chat.get("title", "")
        linked = updated_chat.get("linked_chat_id")
        self._log.append_info(
            f"💬 {title}: найдена группа комментариев (id={linked})"
        )

    def _on_request_topics(self, chat_id) -> None:
        chat_id = int(chat_id)
        from features.chats.ui import TopicsWorker
        worker = TopicsWorker(chat_id, self._cfg)
        worker.topics_loaded.connect(self._on_topics_loaded,  Qt.UniqueConnection)
        worker.log_message.connect(self._log.append_info,     Qt.UniqueConnection)
        worker.error.connect(self._on_worker_error,           Qt.UniqueConnection)
        self._start_worker(worker)
        self._rozetta.set_tip("Загружаю ветки форума...")

    def _on_topics_loaded(self, topics: dict) -> None:
        self._chats_screen.inject_topics(topics)
        count = sum(len(v) for v in topics.values())
        self._log.append_success(f"✅ Загружено веток: {count}")

    # ──────────────────────────────────────────────────────────────────────
    # СЛОТЫ: УЧАСТНИКИ
    # ──────────────────────────────────────────────────────────────────────

    def _on_load_members(self, chat: dict) -> None:
        from features.chats.ui import MembersWorker
        worker = MembersWorker(chat, self._cfg)
        worker.members_loaded.connect(self._settings_screen.populate_members, Qt.UniqueConnection)
        worker.log_message.connect(self._log.append_info,                     Qt.UniqueConnection)
        worker.error.connect(self._on_worker_error,                           Qt.UniqueConnection)
        self._start_worker(worker)
        self._rozetta.set_tip("Загружаю участников...")

    # ──────────────────────────────────────────────────────────────────────
    # СЛОТЫ: ПАРСИНГ
    # ──────────────────────────────────────────────────────────────────────

    def _on_start_btn_clicked(self) -> None:
        """Кнопка НАЧАТЬ ПАРСИНГ в правой панели."""
        params = self._settings_screen.get_params()
        if params is None:
            self._show_toast("Выберите чат перед запуском", "error")
            # Переключить на вкладку чатов для выбора
            if self._current_step >= 1:
                self._switch_tab(1)
            return
        self._on_parse_requested(params)

    def _on_parse_requested(self, params: ParseParams) -> None:
        import os
        session_file = self._cfg.session_path + ".session"
        if not os.path.exists(session_file):
            self._log.append_error("❌ Нет активной сессии Telegram")
            self._show_toast("Нет активной сессии Telegram", "error")
            return

        # Сохраняем настройки парсинга в cfg → config.json
        try:
            from config import save_config
            self._cfg.split_mode = params.split_mode
            # Собираем активные медиа-ключи из кнопок напрямую
            media_keys = []
            sp = self._settings_screen
            if getattr(sp, "_media_photo", None) and sp._media_photo.isChecked():
                media_keys.append("photo")
            if getattr(sp, "_media_video", None) and sp._media_video.isChecked():
                media_keys.append("video")
            if getattr(sp, "_media_file",  None) and sp._media_file.isChecked():
                media_keys.append("file")
            if getattr(sp, "_media_voice", None) and sp._media_voice.isChecked():
                media_keys.append("voice")
            if getattr(sp, "_media_round", None) and sp._media_round.isChecked():
                media_keys.append("video_note")
            self._cfg.media_filter = media_keys
            save_config(self._cfg)
        except Exception as exc:
            logger.warning("_on_parse_requested: save_config failed: %s", exc)

        # Проверяем: ChatsWorker / TopicsWorker могли ещё не закрыть соединение с SQLite-сессией.
        # Ждём завершения всех Telethon-воркеров перед стартом ParseWorker.
        from features.chats.ui import ChatsWorker as _ChatsWorker, TopicsWorker as _TopicsWorker
        for w in list(self._active_workers):
            if isinstance(w, (_ChatsWorker, _TopicsWorker)) and w.isRunning():
                name = type(w).__name__
                self._log.append_info(f"⏳ Жду завершения {name} перед парсингом...")
                w.wait(30_000)   # max 30 сек (загрузка чатов может быть долгой)

        self._update_progress(0)
        self._start_btn.setEnabled(False)
        self._start_btn.setText("⏳  ВЫПОЛНЯЕТСЯ...")
        self._stop_btn.setVisible(True)
        self._settings_screen.set_parsing(True)
        self._rozetta.set_state("process")
        self._rozetta.set_tip("Парсинг в процессе...")
        self._set_status("busy", f"Парсинг: {params.chat.get('title', '')}...")

        # 300 мс — даём ChatsWorker завершить loop.close() и освободить SQLite
        QTimer.singleShot(300, lambda: self._start_parse_worker(params))

    def _start_parse_worker(self, params: ParseParams) -> None:
        worker = ParseWorker(params, self._cfg)
        worker.log_message.connect(self._log.append_info,        Qt.UniqueConnection)
        worker.progress.connect(self._update_progress,           Qt.UniqueConnection)
        worker.finished.connect(self._on_parse_finished,         Qt.UniqueConnection)
        worker.error.connect(self._on_parse_error,               Qt.UniqueConnection)
        worker.character_state.connect(self._rozetta.set_state,  Qt.UniqueConnection)
        self._start_worker(worker)

    def _on_parse_finished(self, result) -> None:
        self._update_progress(100)
        count = getattr(result, "messages_count", "?")
        self._log.append_success(f"✅ Парсинг завершён: {count} сообщений")

        # Запускаем STT только если хотя бы один чип активен
        params = self._settings_screen.get_params()
        stt_enabled = params and (params.stt_voice or params.stt_videomessage or params.stt_video)
        if stt_enabled:
            self._set_status("busy", "Распознавание речи...")
            self._rozetta.set_tip("Распознаю голосовые...")
            self._last_parse_result = result
            self._run_stt(result)
        else:
            self._last_collect_result = result
            self._on_stt_finished(result)

    def _on_parse_error(self, message: str) -> None:
        self._update_progress(0)
        self._start_btn.setEnabled(True)
        self._start_btn.setText("▶  НАЧАТЬ ПАРСИНГ")
        self._stop_btn.setVisible(False)
        self._settings_screen.set_parsing(False)
        self._rozetta.set_state("error")
        self._rozetta.set_tip("Ошибка парсинга")
        self._log.append_error(f"❌ Ошибка парсинга: {message}")
        self._set_status("online", "Авторизован")
        self._show_toast(f"Ошибка: {message[:60]}", "error")

    # ──────────────────────────────────────────────────────────────────────
    # STT
    # ──────────────────────────────────────────────────────────────────────

    def _run_stt(self, collect_result) -> None:
        import os
        from core.stt.worker import STTWorker
        from core.utils import sanitize_filename
        from config import DB_FILENAME

        chat_id = getattr(collect_result, "chat_id", None)
        if chat_id is None:
            self._run_export(collect_result)
            return

        db_path = getattr(collect_result, "db_path", "") or ""
        if not db_path:
            chat_title = getattr(collect_result, "chat_title", "") or ""
            chat_dir = os.path.join(str(self._cfg.output_dir), sanitize_filename(chat_title))
            db_path  = os.path.join(chat_dir, DB_FILENAME)

        self._last_collect_result = collect_result
        self._update_progress(0)
        worker = STTWorker(
            db_path=db_path,
            chat_id=chat_id,
            model_size=self._cfg.stt_model,
            language=self._cfg.stt_language,
        )
        worker.log_message.connect(self._log.append_info,          Qt.UniqueConnection)
        worker.progress.connect(self._update_progress,             Qt.UniqueConnection)
        worker.error.connect(self._on_stt_error,                   Qt.UniqueConnection)
        worker.finished.connect(self._on_stt_finished_slot,        Qt.UniqueConnection)
        self._start_worker(worker)

    def _on_stt_finished_slot(self) -> None:
        """Именованный слот для STTWorker.finished (Qt.UniqueConnection требует не-лямбду)."""
        self._on_stt_finished(self._last_collect_result)

    def _on_stt_finished(self, collect_result) -> None:
        fmts = self._settings_screen.get_export_formats()
        label = " + ".join(f.upper() for f in fmts)
        self._set_status("busy", f"Генерация {label}...")
        self._rozetta.set_tip("Создаю документ...")
        self._run_export(collect_result)

    def _on_stt_error(self, message: str) -> None:
        self._log.append_error(f"⚠️ STT ошибка (экспорт продолжается): {message}")
        # Если проблема в отсутствии faster-whisper — показываем диалог с командой
        if "faster-whisper" in message.lower() or "faster_whisper" in message.lower():
            self._auth_screen._show_install_dialog(
                title   = "Требуется библиотека faster-whisper",
                text    = (
                    "Для распознавания голосовых сообщений нужна библиотека "
                    "<b>faster-whisper</b>.<br><br>"
                    "Установите её командой и перезапустите приложение:"
                ),
                command = "pip install faster-whisper",
            )

    # ──────────────────────────────────────────────────────────────────────
    # ЭКСПОРТ
    # ──────────────────────────────────────────────────────────────────────

    def _run_export(self, collect_result) -> None:
        import os
        from features.export.ui import ExportWorker, ExportParams
        from core.utils import sanitize_filename
        from config import DB_FILENAME

        # Guard: не запускать второй ExportWorker если первый ещё работает
        for w in self._active_workers:
            if isinstance(w, ExportWorker):
                logger.warning("_run_export: ExportWorker уже запущен, пропускаем дублирующий вызов")
                return

        chat = self._settings_screen._current_chat or {}
        params = self._settings_screen.get_params()
        split_mode = params.split_mode if params else "none"

        chat_title = (
            getattr(collect_result, "chat_title", None)
            or chat.get("title", "export")
        )
        db_path = getattr(collect_result, "db_path", "") or ""
        if db_path:
            chat_dir = os.path.dirname(db_path)
        else:
            chat_dir = os.path.join(str(self._cfg.output_dir), sanitize_filename(chat_title))
            db_path  = os.path.join(chat_dir, DB_FILENAME)

        export_params = ExportParams(
            chat_id=chat.get("id"),
            chat_title=chat_title,
            split_mode=split_mode,
            include_comments=params.include_comments if params else False,
            output_dir=chat_dir,
            db_path=db_path,
            export_formats=self._settings_screen.get_export_formats(),
            ai_split=self._settings_screen.get_ai_split(),
        )

        worker = ExportWorker(export_params)
        worker.log_message.connect(self._log.append_info,        Qt.UniqueConnection)
        worker.export_complete.connect(self._on_export_complete, Qt.UniqueConnection)
        worker.error.connect(self._on_export_error,              Qt.UniqueConnection)
        worker.character_state.connect(self._rozetta.set_state,  Qt.UniqueConnection)
        self._start_worker(worker)

    def _on_export_complete(self, paths: list) -> None:
        self._update_progress(100)
        self._start_btn.setEnabled(True)
        self._start_btn.setText("▶  НАЧАТЬ ПАРСИНГ")
        self._stop_btn.setVisible(False)
        self._settings_screen.set_parsing(False)
        self._rozetta.set_state("success")
        count = len(paths)
        self._rozetta.set_tip(f"Готово! {count} файл(ов)")
        self._log.append_success(f"✅ Экспорт завершён: {count} файл(ов)")
        for p in paths:
            self._log.append_success(f"   📄 {p}")
        self._set_status("online", "Авторизован")
        self._show_toast(f"Готово! Создано {count} файл(ов)", "success")
        self._set_step(3)

    def _on_export_error(self, message: str) -> None:
        self._update_progress(0)
        self._start_btn.setEnabled(True)
        self._start_btn.setText("▶  НАЧАТЬ ПАРСИНГ")
        self._stop_btn.setVisible(False)
        self._settings_screen.set_parsing(False)
        self._rozetta.set_state("error")
        self._rozetta.set_tip("Ошибка экспорта")
        self._log.append_error(f"❌ Ошибка экспорта: {message}")
        self._set_status("online", "Авторизован")
        self._show_toast(f"Ошибка экспорта: {message[:50]}", "error")

    # ──────────────────────────────────────────────────────────────────────
    # ОБЩИЕ СЛОТЫ
    # ──────────────────────────────────────────────────────────────────────

    def _on_worker_error(self, message: str) -> None:
        self._log.append_error(f"❌ {message}")
        self._rozetta.set_state("error")
        self._show_toast(message[:80], "error")

    # ──────────────────────────────────────────────────────────────────────
    # УПРАВЛЕНИЕ ВОРКЕРАМИ
    # ──────────────────────────────────────────────────────────────────────

    def _start_worker(self, worker: QThread) -> None:
        self._active_workers.append(worker)
        worker.finished.connect(
            lambda *_: self._on_worker_done(worker),
            Qt.ConnectionType.SingleShotConnection,
        )
        worker.start()

    def _on_worker_done(self, worker: QThread) -> None:
        try:
            self._active_workers.remove(worker)
        except ValueError:
            pass
        worker.deleteLater()

    def _on_stop_clicked(self) -> None:
        """Кнопка Стоп — прерывает текущие воркеры."""
        self._stop_all_workers()
        self._start_btn.setEnabled(True)
        self._start_btn.setText("▶  НАЧАТЬ ПАРСИНГ")
        self._stop_btn.setVisible(False)
        self._settings_screen.set_parsing(False)
        self._update_progress(0)
        self._rozetta.set_state("idle")
        self._rozetta.set_tip("")
        self._set_status("online", "Авторизован")
        self._log.append_info("⏹ Операция остановлена пользователем")

    def _stop_all_workers(self) -> None:
        for worker in list(self._active_workers):
            if worker.isRunning():
                worker.quit()
                if not worker.wait(3000):
                    worker.terminate()
                    worker.wait(1000)

    # ──────────────────────────────────────────────────────────────────────
    # ЖИЗНЕННЫЙ ЦИКЛ ОКНА
    # ──────────────────────────────────────────────────────────────────────

    def closeEvent(self, event: QCloseEvent) -> None:
        logger.info("MainWindow closing, stopping workers...")
        self._stop_all_workers()
        event.accept()
        logger.info("MainWindow closed")
