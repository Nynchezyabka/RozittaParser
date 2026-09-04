"""
FILE: ui/main_window.py.

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
import os
import tempfile
import time
from typing import Optional

from PySide6.QtCore import Qt, QThread, Signal, QTimer, QUrl
from PySide6.QtGui import QCloseEvent, QColor, QDesktopServices, QFont
from PySide6.QtMultimedia import QSoundEffect

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QLabel, QSizePolicy, QProgressBar, QStackedWidget,
    QFrame, QPushButton, QSpinBox,
    QScrollArea, QGridLayout, QDialog,
    QListWidget, QListWidgetItem, QLineEdit,
)

from config import AppConfig
from core.database import DBManager
from features.export.filters import UserFilter
from core.ui_shared.styles import (
    BG_PRIMARY, ACCENT_ORANGE, ACCENT_PINK,
    ACCENT_SOFT_ORANGE,
    TEXT_PRIMARY, TEXT_SECONDARY,
    OVERLAY_HEX, OVERLAY2_HEX, BORDER_HEX,
    RADIUS_MD, FONT_FAMILY, FONT_SIZE_BODY, FONT_SIZE_SMALL,
    COLOR_SUCCESS, COLOR_ERROR, COLOR_WARNING,
    QSS_PROGRESS, QSS_INPUT,
)
from core.ui_shared.widgets import (
    RozittaWidget, LogWidget,
    ModernCard, SectionTitle, ToggleSwitch,
    MediaButton, ChipButton, SplitModeButton, PresetButton,
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
            # shadow = f"0 0 6px {COLOR_SUCCESS}"
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
    # N-1: смена пресета меняет смысл кнопки запуска. Без сигнала подпись
    # обновлялась только из _on_*_finished, то есть после первого прогона.
    preset_changed          = Signal()

    def __init__(self, cfg: "AppConfig | None" = None, parent=None):
        super().__init__(parent)
        self._cfg           = cfg
        self._current_chat: Optional[dict] = None
        self._selected_user_id: Optional[int] = None
        self._user_mode:    str             = "messages_only"
        self._split_mode:   str             = "none"
        self._split_buttons: list[SplitModeButton] = []
        self._parsing:      bool            = False
        self._members_cache: list = []
        # N-1: список грузится при открытии модалки; период запомнен, чтобы
        # не гонять скан истории заново на каждое открытие.
        self._members_loading: bool = False
        self._members_loaded_period = None
        self._members_dialog = None
        self._build()

        # Ограничения пересобираются при смене набора форматов. Подключаем
        # после _build(): обработчик читает виджеты обеих секций сразу, а на
        # момент сборки одна из них ещё не существует.
        for _fmt_btn in (self._fmt_docx, self._fmt_json,
                         self._fmt_md, self._fmt_html):
            _fmt_btn.toggled.connect(lambda _=False: self._apply_export_limits())

        if cfg:
            self._restore_from_cfg(cfg)
        self._apply_export_limits()

    def _restore_from_cfg(self, cfg) -> None:
        """Восстанавливает последние настройки из AppConfig после сборки UI."""

        # Режим разбивки
        # Ровно одна кнопка активна: setChecked(True) без снятия остальных
        # оставлял «Единый» подсвеченным вместе с сохранённым режимом,
        # а _split_mode уходил в сохранённый — выгрузка шла не туда.
        if cfg.split_mode and cfg.split_mode != "none":
            known = {btn.mode for btn in self._split_buttons}
            if cfg.split_mode in known:
                for btn in self._split_buttons:
                    btn.setChecked(btn.mode == cfg.split_mode)
                self._split_mode = cfg.split_mode

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
    # UI-CLEAN-4: ПРЕСЕТЫ
    # ──────────────────────────────────────────────────────────────────────

    # media: photo, video, file, voice, round; fmt: docx/json/md/html
    _PRESETS = {
        "archive": dict(
            label="💾 Сохранить архив",
            hint="DOCX и HTML — читать и искать по архиву самостоятельно",
            media=("photo", "video", "file", "voice", "round"),
            comments=True, stt_voice=True, stt_round=True,
            formats=("docx", "html"), ai_split=False,
        ),
        "ai": dict(
            label="💬 Спросить у чат-бота",
            hint="MD кусками — вставлять в окно чата",
            media=("voice", "round"),
            comments=True, stt_voice=True, stt_round=True,
            formats=("md",), ai_split=True,
        ),
        "kb": dict(
            label="🗂 Архив для ИИ-агента",
            hint="MD и JSON с оглавлением — агент ищет сам",
            media=("voice", "round"),
            comments=True, stt_voice=True, stt_round=True,
            formats=("md", "json"), ai_split=False,
            build_kb=True,
        ),
        "members": dict(
            label="👥 Список участников",
            hint="Кто писал в чате и сколько сообщений — отдельный DOCX",
            media=(),
            comments=False, stt_voice=False, stt_round=False,
            formats=("docx",), ai_split=False,
            members_only=True,
        ),
    }  # ── KB preset stage 10 (UI) ──

    @staticmethod
    def _widget_set_on(widget, value: bool) -> None:
        """Защитный сеттер: у кастомных виджетов API различается."""
        if widget is None:
            return
        if hasattr(widget, "setActive"):
            widget.setActive(bool(value))
        elif hasattr(widget, "setChecked"):
            widget.setChecked(bool(value))

    @staticmethod
    def _widget_on_change(widget, slot) -> None:
        """Защитное подключение к первому доступному сигналу изменения."""
        for sig_name in ("clicked", "toggled", "stateChanged"):
            sig = getattr(widget, sig_name, None)
            if sig is not None and hasattr(sig, "connect"):
                sig.connect(slot)
                return

    def _build_presets_section(self) -> QWidget:
        card, layout = self._card()
        layout.addWidget(SectionTitle("⚡", "Быстрый выбор"))

        # Сетка 2×2: столбцом четыре карточки занимали 489 px, здесь — около
        # 290. Подписи рассчитаны на две строки половинной ширины.
        row = QGridLayout()
        row.setSpacing(8)
        row.setContentsMargins(0, 0, 0, 0)
        self._preset_buttons: dict[str, QPushButton] = {}

        for idx, (key, spec) in enumerate(self._PRESETS.items()):
            btn = PresetButton(spec["label"], spec.get("hint", ""), key)
            btn.clicked.connect(lambda _=False, k=key: self._apply_preset(k))
            self._preset_buttons[key] = btn
            row.addWidget(btn, idx // 2, idx % 2)

        layout.addLayout(row)

        self._members_only_hint = QLabel(
            "Будет создан только список участников. Сообщения не выгружаются"
        )
        self._members_only_hint.setWordWrap(True)
        self._members_only_hint.setStyleSheet(
            f"color: {COLOR_WARNING}; font-size: 11px; background: transparent;"
        )
        self._members_only_hint.setVisible(False)
        layout.addWidget(self._members_only_hint)

        # Тонкий разделитель: ниже — не ещё один пресет, а ручная правка.
        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setFixedHeight(1)
        divider.setStyleSheet(f"background-color: {BORDER_HEX}; border: none;")
        layout.addWidget(divider)

        layout.addWidget(self._build_export_body())

        self._applying_preset = False
        return card

    def _wire_preset_watchers(self) -> None:
        """Любое ручное изменение состава/формата → «Свой вариант».

        Вызывается из _build() ПОСЛЕ сборки всех секций: виджеты
        медиа/STT/форматов создаются позже секции пресетов (hotfix).
        """
        watched = [
            self._media_photo, self._media_video, self._media_file,
            self._media_voice, self._media_round,
            self._stt_voice, self._stt_round,
            self._toggle_comments, self._toggle_ai_split,
            # _toggle_build_kb намеренно НЕ в watched: чекбокс редактируемый,
            # переключение KB не сбрасывает текущий пресет (Variant B, #96)
            self._fmt_docx, self._fmt_json, self._fmt_md, self._fmt_html,
        ]
        for w in watched:
            self._widget_on_change(w, self._mark_custom_preset)

    def _apply_preset(self, key: str) -> None:
        """Выставляет все настройки состава/формата по пресету."""
        spec = self._PRESETS[key]
        self._applying_preset = True
        self._is_custom = False
        try:
            media_map = {
                "photo": self._media_photo, "video": self._media_video,
                "file": self._media_file, "voice": self._media_voice,
                "round": self._media_round,
            }
            for mkey, widget in media_map.items():
                self._widget_set_on(widget, mkey in spec["media"])

            self._widget_set_on(self._stt_voice, spec["stt_voice"])
            self._widget_set_on(self._stt_round, spec["stt_round"])
            self._widget_set_on(self._toggle_comments, spec["comments"])
            self._widget_set_on(self._toggle_redownload, False)
            self._widget_set_on(self._toggle_takeout, False)
            self._widget_set_on(self._toggle_ai_split, spec["ai_split"])
            self._widget_set_on(self._toggle_build_kb, spec.get("build_kb", False))  # ── KB preset stage 10 (UI) ──

            fmt_map = {
                "docx": self._fmt_docx, "json": self._fmt_json,
                "md": self._fmt_md, "html": self._fmt_html,
            }
            for fkey, widget in fmt_map.items():
                widget.setChecked(fkey in spec["formats"])

            # Разбивка — единый файл
            for btn in self._split_buttons:
                btn.setChecked(btn.mode == "none")
            self._split_mode = "none"

            for pkey, btn in self._preset_buttons.items():
                btn.setChecked(pkey == key)
            # Галочка кнопки означает «блок раскрыт», а не «свой вариант»:
            # трогать её здесь нельзя, иначе выбор пресета схлопывает панель
            # под руками. Состояние состава живёт в _is_custom, он выставлен
            # в начале метода, и подпись обновится сама.
            self._update_manual_header()
            self._apply_export_limits()
            self._log_signal_safe(f"⚡ Пресет: {spec['label']}")
        finally:
            self._applying_preset = False
        self.preset_changed.emit()

    def _mark_custom_preset(self, *_args) -> None:
        """Ручное изменение состава → подпись «Свой вариант»."""
        if getattr(self, "_applying_preset", False):
            return
        if not hasattr(self, "_preset_buttons"):
            return
        for btn in self._preset_buttons.values():
            btn.setChecked(False)
        self._is_custom = True
        self._update_manual_header()
        self.preset_changed.emit()

    def _update_manual_header(self) -> None:
        """
        Подпись кнопки раскрытия.

        Галочка кнопки означает «блок раскрыт», поэтому состояние «состав
        разошёлся с пресетом» живёт в тексте, а не в setChecked — иначе два
        смысла в одном свойстве.

        Текущий набор форматов показывается всегда: свёрнутый блок не должен
        прятать уже сделанный выбор.
        """
        if not hasattr(self, "_preset_custom_btn"):
            return
        formats = [f.upper() for f in self.get_export_formats()]
        title = "Свой вариант" if getattr(self, "_is_custom", False) \
            else "Настроить вручную"
        arrow = "▾" if self._preset_custom_btn.isChecked() else "▸"
        self._preset_custom_btn.setText(
            "⚙️  {0} — {1}   {2}".format(title, ", ".join(formats) or "ничего", arrow)
        )

    def _log_signal_safe(self, msg: str) -> None:
        sig = getattr(self, "log_message", None)
        if sig is not None and hasattr(sig, "emit"):
            sig.emit(msg)

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
        cl.addWidget(self._build_presets_section())   # UI-CLEAN-4
        cl.addWidget(self._build_media_section())
        cl.addWidget(self._build_stt_section())
        cl.addWidget(self._build_date_section())
        cl.addWidget(self._build_members_opener())   # N-1: карточка → модалка
        cl.addWidget(self._build_split_section())
        # Форматы переехали внутрь «Быстрого выбора», отдельной карточки нет.
        cl.addWidget(self._build_options_section())
        self._wire_preset_watchers()   # UI-CLEAN-4 hotfix: после ВСЕХ секций
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

    def _option_row(self, label: str, toggle: ToggleSwitch,
                    hint: Optional[str] = None) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)
        lbl = QLabel(label)
        lbl.setStyleSheet(
            f"color: {TEXT_PRIMARY}; font-size: 13px; background: transparent;"
        )
        if hint:
            # UI-CLEAN-3: подпись + серая подсказка простым языком
            col = QVBoxLayout()
            col.setSpacing(2)
            col.addWidget(lbl)
            hint_lbl = QLabel(hint)
            hint_lbl.setWordWrap(True)
            hint_lbl.setStyleSheet(
                f"color: {TEXT_SECONDARY}; font-size: 11px; background: transparent;"
            )
            col.addWidget(hint_lbl)
            row.addLayout(col, 1)
        else:
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
        layout.addWidget(SectionTitle("📥", "Что скачать на диск", accent=True))

        # «Медиафайлы» — категория, она не отвечает на вопрос «что произойдёт».
        # Плюс нигде не было сказано, что текст выгружается независимо от этих
        # кнопок: сняв все пять, человек мог решить, что не получит ничего.
        caption = QLabel("Текст сохраняется всегда — здесь только вложения")
        caption.setWordWrap(True)
        caption.setStyleSheet(
            f"color: {TEXT_SECONDARY}; font-size: 11px; background: transparent;"
        )
        layout.addWidget(caption)

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

        # Видимость последствия: что именно уедет на диск.
        self._media_summary = QLabel()
        self._media_summary.setWordWrap(True)
        self._media_summary.setStyleSheet(
            f"color: {TEXT_SECONDARY}; font-size: 11px; background: transparent;"
        )
        layout.addWidget(self._media_summary)

        for _btn in (self._media_photo, self._media_video, self._media_file,
                     self._media_voice, self._media_round):
            _btn.toggled.connect(lambda _=False: self._update_media_summary())
        self._update_media_summary()

        return card

    def _update_media_summary(self) -> None:
        """Строка итога под кнопками: что скачается вместе с текстом."""
        names = [
            (self._media_photo, "фото"),
            (self._media_video, "видео"),
            (self._media_file, "файлы"),
            (self._media_voice, "голосовые"),
            (self._media_round, "кружки"),
        ]
        chosen = [n for btn, n in names if btn.isChecked()]
        self._media_summary.setText(
            "Скачаются: " + ", ".join(chosen) if chosen
            else "Вложения не скачиваются — только текст"
        )

    def _build_stt_section(self) -> ModernCard:
        card, layout = self._card()
        layout.addWidget(SectionTitle("🎙️", "Распознавание речи"))

        chips_row = QHBoxLayout()
        chips_row.setSpacing(8)

        self._stt_voice = ChipButton("🎤", "Голосовые", "voice", True)
        self._stt_round = ChipButton("📹", "Кружочки", "video_note", True)

        chips_row.addWidget(self._stt_voice)
        chips_row.addWidget(self._stt_round)
        chips_row.addStretch(1)
        layout.addLayout(chips_row)

        # Место, где человек упирается в ограничение: включил распознавание,
        # а видео не расшифровалось. Ссылка серым, чтобы не перетягивать
        # внимание с настройки.
        stt_hint = QLabel(
            'Голосовые и кружочки распознаются и попадают прямо в текст '
            'документа. Видео и длинные аудио расшифровывает '
            '<a href="https://github.com/Nynchezyabka/RozittaTranscriber" '
            f'style="color: {ACCENT_ORANGE};">Rozitta Transcriber</a> — '
            'отдельными файлами рядом с архивом'
        )
        stt_hint.setWordWrap(True)
        stt_hint.setOpenExternalLinks(True)
        stt_hint.setStyleSheet(
            f"color: {TEXT_SECONDARY}; font-size: 11px; background: transparent;"
        )
        layout.addWidget(stt_hint)

        return card

    def _build_date_section(self) -> ModernCard:
        card, layout = self._card()
        layout.addWidget(SectionTitle("📅", "Период"))
        self._date_widget = DateRangeWidget()
        layout.addWidget(self._date_widget)
        return card

    @property
    def date_from(self):
        start_dt, _ = self._date_widget.get_date_range()
        return start_dt.date() if start_dt is not None else None

    @property
    def date_to(self):
        _, end_dt = self._date_widget.get_date_range()
        return end_dt.date() if end_dt is not None else None

    def _build_members_opener(self) -> QWidget:
        """
        N-1: в панели остаётся строка-итог, сам фильтр живёт в модалке.

        Карточку собирает всё тот же _build_members_section(), и принадлежит
        она панели. Поэтому обработчики FEAT-6 продолжают работать со своими
        self._members_* без переподключения — окно её только показывает.
        """
        self._members_card = self._build_members_section()

        self._members_btn = QPushButton()
        self._members_btn.setFixedHeight(38)
        self._members_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._members_btn.setEnabled(self._current_chat is not None)
        self._members_btn.setStyleSheet(
            f"QPushButton {{ background-color: {OVERLAY2_HEX};"
            f" border: 1px solid {BORDER_HEX};"
            f" border-radius: {RADIUS_MD}px;"
            f" color: {TEXT_PRIMARY}; font-size: 13px;"
            " text-align: left; padding: 0 14px; }"
            f"QPushButton:hover:enabled {{ background-color: {OVERLAY_HEX}; }}"
            " QPushButton:disabled { color: rgba(255,255,255,0.25); }"
        )
        self._members_btn.clicked.connect(self._open_members_dialog)
        self._update_members_button()
        return self._members_btn

    def _open_members_dialog(self) -> None:
        """Открывает окно фильтра и запрашивает список, если он устарел."""
        if self._members_dialog is None:
            self._members_dialog = ParticipantsDialog(
                self._members_card, parent=self
            )
        self._request_members_if_needed()
        self._members_dialog.exec()
        self._update_members_button()

    def _request_members_if_needed(self) -> None:
        """
        Загрузка при открытии окна — со статусом вместо кнопки.

        Повтор только при смене периода: MembersWorker сканирует историю
        через Telethon, это десятки секунд на живом чате.
        """
        if self._current_chat is None:
            self._members_count_lbl.setText("Сначала выберите чат")
            return
        if self._members_loading:
            return
        period = (self.date_from, self.date_to)
        if self._members_cache and period == self._members_loaded_period:
            return
        self._members_loading = True
        self._members_loaded_period = period
        self._members_count_lbl.setText(
            "⏳  Собираю участников за выбранный период..."
        )
        self.load_members_requested.emit(self._current_chat)

    def _update_members_button(self) -> None:
        """Подпись строки-итога: что фильтр сделает с выгрузкой."""
        mode = getattr(self, "_pfilter_mode", "none")
        n = len(getattr(self, "_pfilter_selected", {}))
        if mode == "none" or not n:
            state = "все"
        elif mode == "include":
            state = f"только выбранные ({n})"
        else:
            state = f"кроме выбранных ({n})"
        self._members_btn.setText(f"👥  Участники: {state}          ›")

    def notify_members_failed(self, message: str) -> None:
        """
        MembersWorker упал — снять «идёт загрузка», иначе повторное открытие
        окна молча ничего не запросит.
        """
        self._members_loading = False
        self._members_loaded_period = None
        self._members_count_lbl.setText("Не удалось загрузить участников")

    def _build_members_section(self) -> ModernCard:
        card, layout = self._card()
        layout.addWidget(SectionTitle("👥", "Участники"))

        # UI-CLEAN-3: объясняем, что фильтр влияет на документ, а не на скачивание
        subtitle = QLabel(
            "Скачивается всегда весь чат. Здесь вы выбираете, "
            "чьи сообщения попадут в документ"
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet(
            f"color: {TEXT_SECONDARY}; font-size: 11px; background: transparent;"
        )
        layout.addWidget(subtitle)

        # Режим поиска
        mode_row = QHBoxLayout()
        mode_row.setSpacing(8)

        self._mode_btn_messages = QPushButton("Только сообщения")
        self._mode_btn_all      = QPushButton("Сообщения + ответы")

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
                    min-width: min-content;
                }}
                QPushButton:checked {{
                    background-color: {ACCENT_SOFT_ORANGE};
                    border-color: {ACCENT_ORANGE};
                    color: {ACCENT_ORANGE};
                    font-weight: 300;
                }}
                QPushButton:hover:!checked {{
                    background-color: {OVERLAY_HEX};
                }}
            """)

        self._mode_btn_messages.setChecked(True)
        self._mode_btn_messages.clicked.connect(
            lambda: self._set_user_mode("messages_only")
        )
        self._mode_btn_all.clicked.connect(
            lambda: self._set_user_mode("threads")
        )

        mode_row.addWidget(self._mode_btn_messages)
        mode_row.addWidget(self._mode_btn_all)
        mode_row.addStretch(1)
        layout.addLayout(mode_row)

        # UI-CLEAN-3: режимы недоступны, пока не выбран участник
        self._mode_hint_lbl = QLabel("ℹ️ Станет доступно, когда выберете участника")
        self._mode_hint_lbl.setStyleSheet(
            f"color: {TEXT_SECONDARY}; font-size: 11px; background: transparent;"
        )
        layout.addWidget(self._mode_hint_lbl)
        self._mode_btn_messages.setEnabled(False)
        self._mode_btn_all.setEnabled(False)

        # ── FEAT-6: фильтр участников — режим, поиск, список с отметками ──
        self._pfilter_mode:     str  = "none"
        self._pfilter_selected: dict = {}

        pf_row = QHBoxLayout()
        pf_row.setSpacing(6)
        self._pf_buttons: dict = {}
        for _mode, _caption in (("none",    "Все"),
                                ("include", "Только выбранные"),
                                ("exclude", "Кроме выбранных")):
            _btn = QPushButton(_caption)
            _btn.setCheckable(True)
            _btn.setFixedHeight(30)
            _btn.setCursor(Qt.CursorShape.PointingHandCursor)
            _btn.clicked.connect(
                lambda _checked=False, m=_mode: self._set_participant_mode(m)
            )
            self._pf_buttons[_mode] = _btn
            pf_row.addWidget(_btn)
        self._pf_buttons["none"].setChecked(True)
        layout.addLayout(pf_row)

        self._members_search = QLineEdit()
        self._members_search.setPlaceholderText("Поиск участника")
        self._members_search.setClearButtonEnabled(True)
        self._members_search.setFixedHeight(30)
        self._members_search.setStyleSheet(QSS_INPUT)
        self._members_search.setEnabled(False)
        self._members_search.textChanged.connect(self._filter_members_list)
        layout.addWidget(self._members_search)

        self._members_list = QListWidget()
        self._members_list.setFixedHeight(150)
        self._members_list.setEnabled(False)
        self._members_list.itemChanged.connect(self._on_member_item_changed)
        layout.addWidget(self._members_list)

        self._members_count_lbl = QLabel("Фильтр выключен — в выгрузке все")
        self._members_count_lbl.setStyleSheet(
            f"color: {TEXT_SECONDARY}; font-size: 11px; background: transparent;"
        )
        layout.addWidget(self._members_count_lbl)

        # MembersWorker получает date_from/date_to — список зависит от периода,
        # но в интерфейсе это нигде не было сказано.
        self._members_period_lbl = QLabel(
            "ℹ️ Список собран за выбранный период. Измените даты — "
            "он соберётся заново при следующем открытии этого окна."
        )
        self._members_period_lbl.setWordWrap(True)
        self._members_period_lbl.setStyleSheet(
            f"color: {TEXT_SECONDARY}; font-size: 11px; background: transparent;"
        )
        layout.addWidget(self._members_period_lbl)

        self._apply_participant_mode_style()

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

        # D-4: причина недоступности пишется текстом, а не тултипом —
        # выключенный виджет не получает событий мыши, подсказка не всплывает.
        self._split_hint = QLabel("Разбивка по постам доступна только для каналов")
        self._split_hint.setWordWrap(True)
        self._split_hint.setStyleSheet(
            f"color: {TEXT_SECONDARY}; font-size: 11px; background: transparent;"
        )
        self._split_hint.setVisible(False)
        layout.addWidget(self._split_hint)

        return card

    def _build_export_body(self) -> QWidget:
        """
        Кнопка раскрытия и блок ручной настройки — без собственной карточки.

        Живёт внутри «Быстрого выбора»: пресет и ручная правка формата — одно
        решение, и принимать его человек должен в одном месте. Отдельной
        карточкой блок уезжал на Y=1785 при окне в 900 и выглядел пропавшим.
        """
        box = QWidget()
        box.setStyleSheet("background: transparent;")
        outer = QVBoxLayout(box)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)

        self._preset_custom_btn = QPushButton()
        self._preset_custom_btn.setCheckable(True)
        self._preset_custom_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._preset_custom_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {TEXT_SECONDARY};"
            f" border: 1px solid {BORDER_HEX}; border-radius: 8px;"
            f" padding: 7px 13px; font-size: 12px; text-align: left; }}"
            f" QPushButton:hover {{ background-color: {OVERLAY_HEX};"
            f" color: {TEXT_PRIMARY}; }}"
            f" QPushButton:checked {{ border-color: {ACCENT_ORANGE};"
            f" color: {ACCENT_ORANGE}; }}"
        )
        outer.addWidget(self._preset_custom_btn)

        # Дальше по методу имя layout указывает на содержимое контейнера,
        # поэтому девяносто строк ниже не переписываются: они и так кладут
        # виджеты в layout, просто теперь это раскладка скрытого блока.
        self._manual_box = QWidget()
        self._manual_box.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(self._manual_box)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(8)
        outer.addWidget(self._manual_box)
        self._manual_box.setVisible(False)

        self._preset_custom_btn.toggled.connect(self._manual_box.setVisible)
        self._preset_custom_btn.toggled.connect(
            lambda _=False: self._update_manual_header()
        )

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

        self._fmt_docx.setChecked(True)  # По умолчанию только DOCX

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
        ai_row = self._option_row("🤖  Адаптировать для ИИ", self._toggle_ai_split)
        layout.addLayout(ai_row)

        # Р-8: причина недоступности пишется текстом — на выключенном
        # переключателе тултип не всплывает, событий мыши он не получает.
        self._ai_hint = QLabel(
            "Нарезка по объёму нужна корпусу для нейросети — "
            "доступна при выбранных MD или JSON"
        )
        self._ai_hint.setWordWrap(True)
        self._ai_hint.setStyleSheet(
            f"color: {TEXT_SECONDARY}; font-size: 11px; background: transparent;"
        )
        self._ai_hint.setVisible(False)
        layout.addWidget(self._ai_hint)

        # Размер чанка — показывается только когда AI-split включён
        chunk_row = QHBoxLayout()
        chunk_row.setSpacing(6)
        chunk_lbl = QLabel("Слов в одном файле:")
        chunk_lbl.setStyleSheet(
            f"color: {TEXT_SECONDARY}; font-size: 11px; background: transparent;"
        )
        self._ai_chunk_spin = QSpinBox()
        self._ai_chunk_spin.setRange(10_000, 2_000_000)
        self._ai_chunk_spin.setSingleStep(50_000)
        self._ai_chunk_spin.setValue(300_000)
        self._ai_chunk_spin.setFixedWidth(110)
        self._ai_chunk_spin.setFixedHeight(28)
        self._ai_chunk_spin.setStyleSheet(QSS_INPUT)
        self._ai_chunk_spin.setEnabled(False)  # заблокирован пока тоггл выкл
        chunk_row.addSpacing(4)
        chunk_row.addWidget(chunk_lbl)
        chunk_row.addWidget(self._ai_chunk_spin)
        chunk_row.addStretch()
        self._ai_chunk_row_widget = QWidget()
        self._ai_chunk_row_widget.setLayout(chunk_row)
        self._ai_chunk_row_widget.setStyleSheet("background: transparent;")
        layout.addWidget(self._ai_chunk_row_widget)

        # Связываем тоггл и спинбокс
        self._toggle_ai_split.toggled.connect(self._ai_chunk_spin.setEnabled)

        # ── KB toggle ───────────────────────────────────────────────────
        self._toggle_build_kb = ToggleSwitch(checked=False)  # ── KB preset stage 10 (UI) ──
        kb_row = self._option_row(
            self.tr("🧠  Создать оглавление и инструкцию для ИИ"),
            self._toggle_build_kb,
            hint=self.tr(
                "Подготовит архив для внешних LLM: оглавление, "
                "инструкция, YAML-метаданные, паспорт архива"
            ),
        )
        layout.addLayout(kb_row)

        return box

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
        return fmt or ["docx"]  # fallback

    def get_ai_split(self) -> bool:
        """Возвращает состояние чекбокса 'Адаптировать для ИИ'."""

        return self._toggle_ai_split.isChecked()

    def get_ai_split_chunk_words(self) -> int:
        """Возвращает размер AI-чанка в словах."""

        return self._ai_chunk_spin.value()

    def get_build_kb(self) -> bool:
        """Возвращает состояние чекбокса 'База знаний для ИИ'."""  # ── KB preset stage 10 (UI) ──

        return self._toggle_build_kb.isChecked()

    def _build_options_section(self) -> ModernCard:
        card, layout = self._card()
        layout.addWidget(SectionTitle("⚙️", "Параметры"))

        self._toggle_comments = ToggleSwitch(checked=False)
        self._toggle_redownload = ToggleSwitch(checked=False)
        self._toggle_takeout = ToggleSwitch(checked=False)

        layout.addLayout(self._option_row(
            "Скачивать комментарии под постами", self._toggle_comments,
            hint="То, что участники пишут в обсуждении под каждым постом канала. "
                 "Скачанные комментарии попадут в документ",
        ))
        layout.addLayout(self._option_row(
            "Скачать всё заново", self._toggle_redownload,
            hint="Выключено: продолжим с места остановки, уже скачанное пропустим",
        ))
        layout.addLayout(self._option_row(
            "⚡ Takeout API", self._toggle_takeout,
            hint="Быстрее для больших чатов, особенно с VPN. "
                 "Если не уверены — не включайте",
        ))
        return card

    # ──────────────────────────────────────────────────────────────────────
    # ВНУТРЕННИЕ СЛОТЫ
    # ──────────────────────────────────────────────────────────────────────

    def _set_user_mode(self, mode: str) -> None:
        self._user_mode = mode
        self._mode_btn_messages.setChecked(mode == "messages_only")
        self._mode_btn_all.setChecked(mode == "threads")

    def _update_mode_buttons_enabled(self, *_args) -> None:
        """
        UI-CLEAN-3: режимы участника активны только при выбранном участнике.

        FEAT-6: режим веток требует РОВНО ОДНОГО отмеченного в режиме
        «только выбранные» — get_thread_pairs(chat_id, user_id) принимает
        один ID, мультивыбор и исключение в нём смысла не имеют.
        """
        mode     = getattr(self, "_pfilter_mode", "none")
        selected = getattr(self, "_pfilter_selected", {})
        has_user = (mode == "include" and len(selected) == 1)
        self._mode_btn_messages.setEnabled(has_user)
        self._mode_btn_all.setEnabled(has_user)
        if hasattr(self, "_mode_hint_lbl"):
            self._mode_hint_lbl.setVisible(not has_user)
        if not has_user:
            # без участника режим всегда «только сообщения» (канон #21)
            self._set_user_mode("messages_only")

    def _on_split_mode(self, mode: str) -> None:
        self._split_mode = mode
        for btn in self._split_buttons:
            btn.setChecked(btn.mode == mode)

    # ──────────────────────────────────────────────────────────────────────
    # FEAT-6: фильтр участников
    # ──────────────────────────────────────────────────────────────────────

    def _set_participant_mode(self, mode: str) -> None:
        """Переключает режим фильтра: none / include / exclude."""
        self._pfilter_mode = mode
        for _m, _btn in self._pf_buttons.items():
            _btn.setChecked(_m == mode)

        active = (mode != "none") and bool(self._members_list.count())
        self._members_list.setEnabled(active)
        self._members_search.setEnabled(active)

        self._apply_participant_mode_style()
        self._refresh_member_items()
        self._update_members_count_label()
        self._update_mode_buttons_enabled()

    def _indicator_icon_path(self, kind: str) -> str:
        """
        Путь к PNG-иконке индикатора списка: "cross" или "check".

        Рисуется QPainter'ом при первом обращении и кладётся в системный
        temp. Так крестик получается настоящим, но в сборку не нужно
        добавлять файлы (никаких правок --add-data в PyInstaller).
        """
        cache = getattr(self, "_indicator_icons", None)
        if cache is None:
            cache = {}
            self._indicator_icons = cache
        path = cache.get(kind)
        if path and os.path.isfile(path):
            return path

        from PySide6.QtGui import QPainter, QPen, QPixmap

        size = 14
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pm)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            pen = QPen(QColor(COLOR_ERROR if kind == "cross" else ACCENT_ORANGE))
            pen.setWidth(2)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            if kind == "cross":
                m = 4
                painter.drawLine(m, m, size - m, size - m)
                painter.drawLine(size - m, m, m, size - m)
            else:
                painter.drawLine(3, 8, 6, 11)
                painter.drawLine(6, 11, 11, 4)
        finally:
            painter.end()

        path = os.path.join(
            tempfile.gettempdir(), f"rozitta_indicator_{kind}.png"
        )
        pm.save(path, "PNG")
        cache[kind] = path
        return path

    def _apply_participant_mode_style(self) -> None:
        """
        Оформление списка и кнопок режима.

        В режиме «кроме выбранных» в квадратике красный крестик; кнопка
        режима при этом выглядит как остальные — красный на кнопке читался
        как ошибка, а не как выбранный режим.
        """
        icon = self._indicator_icon_path(
            "cross" if self._pfilter_mode == "exclude" else "check"
        )
        icon_url = icon.replace("\\", "/")

        self._members_list.setStyleSheet(
            f"QListWidget {{ background-color: {OVERLAY2_HEX};"
            f" border: 1px solid {BORDER_HEX};"
            f" border-radius: {RADIUS_MD}px;"
            f" color: {TEXT_PRIMARY};"
            f" font-size: {FONT_SIZE_BODY}px; }}"
            "QListWidget::item { padding: 4px 6px; }"
            "QListWidget::indicator { width: 14px; height: 14px;"
            f" border: 1px solid {BORDER_HEX}; border-radius: 3px;"
            " background: transparent; }"
            f"QListWidget::indicator:checked {{ image: url({icon_url}); }}"
        )

        for _m, _btn in self._pf_buttons.items():
            on = (_m == self._pfilter_mode)
            fg = ACCENT_ORANGE if on else TEXT_SECONDARY
            bd = ACCENT_ORANGE if on else BORDER_HEX
            _btn.setStyleSheet(
                f"QPushButton {{ background-color: {OVERLAY2_HEX};"
                f" border: 1px solid {bd};"
                f" border-radius: {RADIUS_MD}px;"
                f" color: {fg}; font-size: 11px; }}"
                f"QPushButton:hover {{ background-color: {OVERLAY_HEX}; }}"
            )

    def _refresh_member_items(self) -> None:
        """
        Исключённые — серые и зачёркнутые, выбранные — полужирные.

        Крестик рисует индикатор (см. _indicator_icon_path), поэтому
        префикса в тексте больше нет.
        """
        self._members_list.blockSignals(True)
        try:
            for i in range(self._members_list.count()):
                item = self._members_list.item(i)
                data = item.data(Qt.ItemDataRole.UserRole) or {}
                name = data.get("name", "")
                checked = item.checkState() == Qt.CheckState.Checked
                excluded = checked and self._pfilter_mode == "exclude"

                font: QFont = item.font()
                font.setStrikeOut(excluded)
                font.setBold(checked and self._pfilter_mode == "include")
                item.setFont(font)

                item.setText(name)
                item.setForeground(
                    QColor(TEXT_SECONDARY if excluded else TEXT_PRIMARY)
                )
        finally:
            self._members_list.blockSignals(False)

    def _on_member_item_changed(self, item: QListWidgetItem) -> None:
        data = item.data(Qt.ItemDataRole.UserRole) or {}
        uid = data.get("id")
        if not uid:
            return
        if item.checkState() == Qt.CheckState.Checked:
            self._pfilter_selected[uid] = data.get("name") or str(uid)
        else:
            self._pfilter_selected.pop(uid, None)

        self._refresh_member_items()
        self._update_members_count_label()
        self._update_mode_buttons_enabled()

    def _filter_members_list(self, text: str) -> None:
        """Поиск по списку: скрывает несовпавшие строки, отметки сохраняются."""
        needle = (text or "").strip().lower()
        for i in range(self._members_list.count()):
            item = self._members_list.item(i)
            data = item.data(Qt.ItemDataRole.UserRole) or {}
            name = (data.get("name") or "").lower()
            item.setHidden(bool(needle) and needle not in name)

    def _update_members_count_label(self) -> None:
        n = len(self._pfilter_selected)
        if self._pfilter_mode == "none":
            text = "Фильтр выключен — в выгрузке все"
        elif self._pfilter_mode == "include":
            text = f"В выгрузке только: {n}"
        else:
            text = f"Исключено из выгрузки: {n} (останутся заглушки)"
        self._members_count_lbl.setText(text)

    def get_user_filter(self) -> UserFilter:
        """FEAT-6: фильтр участников для ExportParams."""
        mode = getattr(self, "_pfilter_mode", "none")
        selected = getattr(self, "_pfilter_selected", {})
        if mode == "none" or not selected:
            return UserFilter.make("none", [])
        return UserFilter.make(mode, list(selected.keys()), dict(selected))
    # ──────────────────────────────────────────────────────────────────────
    # ПУБЛИЧНЫЙ API (совместим с ParseSettingsScreen)
    # ──────────────────────────────────────────────────────────────────────

    def set_chat(self, chat: dict) -> None:
        self._current_chat = chat
        title = chat.get("title", "")
        short = (title[:38] + "…") if len(title) > 38 else title
        self._chat_label.setText(short or "не выбран")
        self._apply_export_limits()

    def is_members_only(self) -> bool:
        """True → выбран режим «Список участников», сообщения не выгружаются."""
        btn = self._preset_buttons.get("members")
        return bool(btn is not None and btn.isChecked())

    def _apply_export_limits(self) -> None:
        """
        Ограничения разбивки — один метод на все причины.

        D-4 / I3: «по постам» имеет смысл только для broadcast-канала. В группе
        у каждого сообщения is_comment = 0, каждое считается постом и получает
        свой файл — десять тысяч сообщений дают десять тысяч файлов.

        Р-8: «по дням» и «по месяцам» реализованы только в DocxGenerator;
        `ai_split` осмыслен только для MD и JSON. Раньше и то и другое молча
        игнорировалось.

        Разводить это по двум обработчикам нельзя: строка-пояснение одна,
        и они бы её перетирали.
        """
        chat       = self._current_chat
        is_channel = bool(chat) and chat.get("type") == "channel"

        # Режим списка участников: всё, что не влияет на результат, гаснет.
        members_only = self.is_members_only()
        for w in (self._media_photo, self._media_video, self._media_file,
                  self._media_voice, self._media_round,
                  self._stt_voice, self._stt_round,
                  self._preset_custom_btn, self._members_search,
                  self._members_list):
            if w is not None:
                w.setEnabled(not members_only)
        # Строка «Участники» открывает модалку — без выбранного чата
        # открывать нечего.
        self._members_btn.setEnabled(
            not members_only and self._current_chat is not None
        )
        for _b in self._pf_buttons.values():
            _b.setEnabled(not members_only)
        for _b in self._split_buttons:
            _b.setEnabled(not members_only)
        if members_only:
            self._members_only_hint.setVisible(True)
            self._split_hint.setVisible(False)
            self._ai_hint.setVisible(False)
            return
        self._members_only_hint.setVisible(False)
        docx_on    = self._fmt_docx.isChecked()
        corpus_on  = self._fmt_md.isChecked() or self._fmt_json.isChecked()

        self._split_post.setEnabled(is_channel)
        self._split_day.setEnabled(docx_on)
        self._split_month.setEnabled(docx_on)

        # Сброс режима «по постам» — только когда чат уже выбран. На старте
        # _split_mode восстановлен из сохранённой конфигурации, а чата ещё нет:
        # гасить кнопку можно, терять сохранённый выбор нельзя.
        if chat is not None and not is_channel and self._split_mode == "post":
            self._on_split_mode("none")
        if not docx_on and self._split_mode in ("day", "month"):
            self._on_split_mode("none")

        self._toggle_ai_split.setEnabled(corpus_on)
        if not corpus_on and self._toggle_ai_split.isChecked():
            self._toggle_ai_split.setChecked(False)

        reasons = []
        if not is_channel:
            reasons.append("«Посты» — только для каналов")
        if not docx_on:
            reasons.append("«По дням» и «Месяцы» — только для DOCX")
        self._split_hint.setText("   ·   ".join(reasons))
        self._split_hint.setVisible(bool(reasons))

        self._ai_hint.setVisible(not corpus_on)
        self._update_manual_header()

    def populate_members(self, users: list[dict]) -> None:
        self._members_cache = users.copy()
        self._pfilter_selected.clear()

        self._members_list.blockSignals(True)
        try:
            self._members_list.clear()
            for user in users:
                uid  = user.get("id", 0)
                name = user.get("name", str(uid))
                item = QListWidgetItem(name)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Unchecked)
                item.setData(Qt.ItemDataRole.UserRole,
                             {"id": uid, "name": name})
                self._members_list.addItem(item)
        finally:
            self._members_list.blockSignals(False)

        active = self._pfilter_mode != "none"
        self._members_list.setEnabled(active)
        self._members_search.setEnabled(active)
        self._members_search.clear()

        self._members_loading = False
        self._refresh_member_items()
        self._update_members_count_label()
        self._update_mode_buttons_enabled()
        self._update_members_button()
        self.log_message.emit(f"Загружено участников: {len(users)}")

    def get_params(self) -> Optional[ParseParams]:
        if self._current_chat is None:
            return None

        # FEAT-6: user_id/username выводятся из выбора.
        # Ровно один отмеченный в режиме «только выбранные» сохраняет старое
        # поведение: суффикс имени файла и доступный режим веток.
        # Любой другой случай — None, имя файла соберёт UserFilter.name_part().
        if (self._pfilter_mode == "include"
                and len(self._pfilter_selected) == 1):
            _uid = next(iter(self._pfilter_selected))
            self.user_id  = _uid or None
            self.username = self._pfilter_selected[_uid] or None
        else:
            self.user_id  = None
            self.username = None

        # Даты
        date_from = None
        date_to = None
        start_dt, end_dt = self._date_widget.get_date_range()
        if start_dt is not None:
            date_from = start_dt.date()
        if end_dt is not None:
            date_to = end_dt.date()

        # D-4: та же проверка на выходе. При старте _split_mode
        # восстанавливается из сохранённой конфигурации ещё до выбора чата,
        # то есть мимо set_chat().
        split_mode = self._split_mode
        if split_mode == "post" and self._current_chat.get("type") != "channel":
            split_mode = "none"

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
            user_id              = self.user_id or 0,
            username             = self.username or "",
            split_mode           = split_mode,
            include_comments     = self._toggle_comments.isChecked(),
            re_download          = self._toggle_redownload.isChecked(),
            use_takeout          = self._toggle_takeout.isChecked(),
        )

    def set_parsing(self, active: bool) -> None:
        self._parsing = active
        self.setEnabled(not active)


class ConfirmStartDialog(QDialog):
    """UI-CLEAN-3: окно «Проверьте перед стартом» (утверждённый макет A).

    Показывает пользователю, что именно будет скачано и собрано
    в документ, ДО запуска парсинга.

    Args:
        rows: список кортежей (название, значение, акцент: bool)
              из MainWindow._build_start_summary().
    """

    def __init__(self, rows: list, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Проверьте перед стартом")
        self.setModal(True)
        self.setMinimumWidth(430)
        self.setStyleSheet(f"QDialog {{ background-color: {BG_PRIMARY}; }}")

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(6)

        header = QLabel("Проверьте перед стартом")
        header.setStyleSheet(
            f"color: {TEXT_PRIMARY}; font-size: 16px; font-weight: 500;"
            " background: transparent;"
        )
        root.addWidget(header)

        sub = QLabel("Вот что сейчас будет скачано и собрано в документ")
        sub.setStyleSheet(
            f"color: {TEXT_SECONDARY}; font-size: 12px; background: transparent;"
        )
        root.addWidget(sub)
        root.addSpacing(8)

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(7)
        for i, (name, value, accent) in enumerate(rows):
            name_lbl = QLabel(name)
            name_lbl.setStyleSheet(
                f"color: {TEXT_SECONDARY}; font-size: 13px; background: transparent;"
            )
            value_lbl = QLabel(value)
            value_lbl.setWordWrap(True)
            color = ACCENT_ORANGE if accent else TEXT_PRIMARY
            value_lbl.setStyleSheet(
                f"color: {color}; font-size: 13px; background: transparent;"
            )
            grid.addWidget(name_lbl, i, 0, Qt.AlignmentFlag.AlignTop)
            grid.addWidget(value_lbl, i, 1)
        grid.setColumnStretch(1, 1)
        root.addLayout(grid)
        root.addSpacing(10)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        btn_row.addStretch(1)

        edit_btn = QPushButton("Изменить")
        edit_btn.setFixedHeight(32)
        edit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        edit_btn.setStyleSheet(
            f"QPushButton {{ background-color: {OVERLAY2_HEX};"
            f" border: 1px solid {BORDER_HEX}; border-radius: {RADIUS_MD}px;"
            f" color: {TEXT_PRIMARY}; font-size: 13px; padding: 0 16px; }}"
            f" QPushButton:hover {{ background-color: {OVERLAY_HEX}; }}"
        )
        edit_btn.clicked.connect(self.reject)

        start_btn = QPushButton("▶  Начать")
        start_btn.setFixedHeight(32)
        start_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        start_btn.setDefault(True)
        start_btn.setStyleSheet(
            f"QPushButton {{ background-color: {ACCENT_ORANGE}; border: none;"
            f" border-radius: {RADIUS_MD}px; color: {BG_PRIMARY};"
            f" font-size: 13px; font-weight: 500; padding: 0 18px; }}"
        )
        start_btn.clicked.connect(self.accept)

        btn_row.addWidget(edit_btn)
        btn_row.addWidget(start_btn)
        root.addLayout(btn_row)


class ParticipantsDialog(QDialog):
    """
    N-1: окно фильтра участников.

    Ничего не строит само: показывает карточку, собранную SettingsPanel.
    Владелец виджетов — панель, поэтому вся логика FEAT-6 (отметки, режимы,
    поиск, зачёркивание) работает без единой правки, а панель становится
    короче на высоту карточки.
    """

    def __init__(self, content, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Участники")
        self.setModal(True)
        self.setMinimumWidth(460)
        self.setStyleSheet(f"QDialog {{ background-color: {BG_PRIMARY}; }}")

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)
        root.addWidget(content)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        done_btn = QPushButton("Готово")
        done_btn.setFixedHeight(32)
        done_btn.setDefault(True)
        done_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        done_btn.setStyleSheet(
            f"QPushButton {{ background-color: {ACCENT_ORANGE}; border: none;"
            f" border-radius: {RADIUS_MD}px; color: {BG_PRIMARY};"
            f" font-size: 13px; font-weight: 500; padding: 0 18px; }}"
        )
        done_btn.clicked.connect(self.accept)
        btn_row.addWidget(done_btn)
        root.addLayout(btn_row)


# ══════════════════════════════════════════════════════════════════════════════
# LOGOUT WORKER
# ══════════════════════════════════════════════════════════════════════════════

class LogoutWorker(QThread):
    """
    Выход: отключиться и забыть session-файл на этом компьютере.

    ⚠️ Чего этот воркер по умолчанию НЕ делает — `client.log_out()`.

    `log_out()` завершает **авторизацию на серверах Telegram**, а не сеанс
    приложения. При импорте из tdata приложение работает на том же ключе
    авторизации, что и Telegram Desktop: авторизация одна на двоих. Убивая
    свою, оно убивает десктоп — у человека с единственным устройством код
    входа приходить становится некуда. Ровно это и словил тестировщик
    3 сентября 2026, нажав кнопку с подписью «Выйти».

    Поэтому обычный выход локальный: отключиться, удалить `.session`.
    Авторизация аккаунта не трогается — при желании её видно и снимается
    в самом Telegram, в списке устройств.

    `terminate_session=True` возвращает прежнее поведение. Ни один элемент
    интерфейса его пока не включает: отдельный пункт с честным
    предупреждением — отдельная задача (правило #27 — интерфейс не
    обещает того, чего нет; здесь обратное — код не делает того, о чём
    интерфейс не предупредил).

    Signals:
        logout_done()      — успешный выход (session удалена)
        log_message(str)   — текстовые сообщения для лога
        error(str)         — ошибка (файл не удалён / logout failed)
    """

    logout_done  = Signal()
    log_message  = Signal(str)
    error        = Signal(str)

    def __init__(self, cfg: AppConfig, parent=None,
                 terminate_session: bool = False):
        super().__init__(parent)
        self._cfg = cfg
        self._terminate_session = terminate_session

    def run(self) -> None:
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(self._do_logout())
        except Exception as exc:
            self.error.emit(f"Ошибка выхода: {exc}")
        finally:
            loop.close()

    async def _do_logout(self) -> None:

        import gc
        cfg = self._cfg
        self.log_message.emit("⏻ Выход из Telegram...")
        from features.auth.api import AuthService
        client = AuthService.build_client(cfg)
        try:
            await client.connect()
            if self._terminate_session:
                await client.log_out()
                self.log_message.emit("✅ Авторизация завершена на сервере")
            else:
                # Только разрываем соединение. log_out() здесь убил бы
                # авторизацию Telegram целиком — вместе с Telegram Desktop,
                # если сессия пришла из tdata (см. docstring класса).
                self.log_message.emit(
                    "🔌 Отключаюсь (авторизацию Telegram не трогаю)")
        except Exception as exc:
            self.log_message.emit(f"⚠️ ошибка отключения (продолжаем): {exc}")
        finally:
            try:
                # client.disconnect() may be a coroutine or a regular function depending on
                # the client implementation. Handle both cases to avoid "None is not awaitable".
                import inspect
                maybe_awaitable = client.disconnect()
                if inspect.isawaitable(maybe_awaitable):
                    await maybe_awaitable
                else:
                    # If it's not awaitable, it was executed already (or is a regular function).
                    pass
            except Exception:
                logging.exception('Исключение в _do_logout.')
            # Явно закрываем SQLite-соединение session-файла
            try:
                sess = getattr(client, 'session', None)
                if sess is not None:
                    # sess may be a sqlite3.Connection or similar; call close() safely
                    try:
                        sess.close()
                    except Exception:
                        # In case sess doesn't support close or closing fails
                        logging.exception('Ошибка при закрытии session-файла в _do_logout.')
            except Exception:
                logging.exception('Исключение при закрытии сессии в _do_logout.')
            del client
            gc.collect()

        # Удалить session-файл
        session_file = str(cfg.session_path)
        if not session_file.endswith(".session"):
            session_file += ".session"
        if not self._remove_session_file(session_file):
            return

        self.logout_done.emit()

    # Сколько раз пробовать удалить session-файл и с какой паузой.
    # Полсекунды суммарно: дескриптор, который держат дольше, держат
    # всерьёз, и ждать его молча — хуже, чем сказать об этом.
    _RM_ATTEMPTS = 5
    _RM_PAUSE_S  = 0.1

    def _remove_session_file(self, session_file: str) -> bool:
        """
        Удаляет session-файл, переживая задержавшийся дескриптор.

        Windows не даёт удалить файл, пока его кто-то держит открытым, и
        отдаёт PermissionError. SQLite-соединение закрывается строкой выше,
        но освобождение дескриптора не мгновенно — с первой попытки удаление
        иногда не проходит, и выход раньше падал целиком.

        Returns:
            True — файла больше нет (или его и не было).
            False — не удалось; ошибка уже отправлена в error.
        """
        last_exc: Optional[OSError] = None
        for attempt in range(self._RM_ATTEMPTS):
            try:
                if not os.path.exists(session_file):
                    return True
                os.remove(session_file)
                self.log_message.emit("🗑 Session-файл удалён")
                return True
            except OSError as exc:
                last_exc = exc
                if attempt + 1 < self._RM_ATTEMPTS:
                    time.sleep(self._RM_PAUSE_S)

        self.error.emit(
            f"Не удалось удалить session-файл: {last_exc}. "
            "Скорее всего он ещё занят — закройте приложение и удалите "
            f"вручную: {session_file}"
        )
        return False


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
        # Папка последней успешной выгрузки — для кнопки «Открыть папку».
        # Берётся из пути созданного файла, а не собирается из названия чата.
        self._output_folder: Optional[str] = None

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
        sidebar.setStyleSheet("background-color: rgba(18,18,18,0.6);")

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(10, 14, 10, 14)
        layout.setSpacing(3)

        # Метка секции
        section_lbl = QLabel("ШАГИ")
        section_lbl.setStyleSheet("""
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
        # Подпись «Выйти» читается как «выйти из приложения» — так теперь и
        # работает. Подсказка проговаривает границу явно: раньше эта кнопка
        # завершала авторизацию Telegram целиком, вместе с Desktop.
        self._logout_btn.setToolTip(
            "Забыть сессию на этом компьютере.\n"
            "Авторизация Telegram останется — её видно в списке устройств."
        )
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
                outline: none;
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
        # Загружаем аватар персонажа. Ищем сначала в assets/, потом в корне приложения.
        import os as _os
        _base = _os.path.dirname(_os.path.abspath(__file__))  # папка ui/
        _app_root = _os.path.dirname(_base)  # корень приложения
        for _candidate in (
                _os.path.join(_app_root, "assets", "rozitta_idle.png"),
                _os.path.join(_app_root, "rozitta_idle.png"),
                "assets/rozitta_idle.png",
                "rozitta_idle.png",
        ):
            if _os.path.exists(_candidate):
                self._rozetta.set_image_path(_candidate)
                break
        self._greeting_sound = QSoundEffect()
        _sound_candidates = (
            _os.path.join(_app_root, "assets", "frog-croaking-x1.wav"),
            _os.path.join(_app_root, "frog-croaking-x1.wav"),
            "assets/frog-croaking-x1.wav",
            "frog-croaking-x1.wav",
        )
        for _candidate in _sound_candidates:
            if _os.path.exists(_candidate):
                self._greeting_sound.setSource(QUrl.fromLocalFile(_candidate))
                break
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

        self._start_btn = QPushButton("▶  НАЧАТЬ ЭКСПОРТ")
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

        # Появляется только после успешной выгрузки: до неё открывать нечего,
        # а папка чата может ещё не существовать. Прячется при следующем
        # запуске — иначе повела бы к результату прошлого прогона.
        self._open_folder_btn = QPushButton("📂  Открыть папку")
        self._open_folder_btn.setFixedHeight(40)
        self._open_folder_btn.setVisible(False)
        self._open_folder_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._open_folder_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {OVERLAY2_HEX};
                border: 1px solid {ACCENT_ORANGE};
                border-radius: {RADIUS_MD}px;
                color: {ACCENT_ORANGE};
                font-size: 13px;
                font-weight: 600;
                font-family: {FONT_FAMILY};
                /* Поля скупые не для красоты: в ряду остаётся 234px, а с
                   полями по 14 кнопке нужно 238 — подпись обрезалась бы. */
                padding: 0 6px;
            }}
            QPushButton:hover {{
                background-color: {ACCENT_SOFT_ORANGE};
            }}
            QPushButton:pressed {{
                background-color: #3A2A10;
            }}
        """)
        btn_row.addWidget(self._open_folder_btn, 0)

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
        # Update Archive stage 1: правый клик на чате → обновление архива
        self._chats_screen.update_archive_requested.connect(
            self._run_update_archive, Qt.UniqueConnection
        )

        # SettingsPanel
        self._settings_screen.parse_requested.connect(self._on_parse_requested)
        self._settings_screen.load_members_requested.connect(self._on_load_members)
        self._settings_screen.log_message.connect(self._log.append_info)
        self._settings_screen.preset_changed.connect(
            self._reset_start_btn_text, Qt.UniqueConnection
        )

        # RozittaWidget
        self._rozetta.clicked.connect(
            lambda: self._log.append_info("Привет! Я Розитта 👋")
        )

        # StartBtn / StopBtn в правой панели
        self._start_btn.clicked.connect(self._on_start_btn_clicked)
        self._stop_btn.clicked.connect(self._on_stop_clicked)
        # Правило #13: именованный метод, не лямбда — иначе UniqueConnection
        # не сработает и обработчик подключится повторно.
        self._open_folder_btn.clicked.connect(
            self._on_open_folder_clicked, Qt.UniqueConnection
        )

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
        worker.log_message.connect(self._log.append_info, Qt.UniqueConnection)
        worker.logout_done.connect(self._on_logout_done, Qt.UniqueConnection)
        worker.error.connect(self._on_logout_error, Qt.UniqueConnection)
        self._start_worker(worker)

    def _on_logout_done(self) -> None:
        self._logout_btn.setVisible(False)
        self._logout_btn.setEnabled(True)
        self._set_status("offline", "Не авторизован")
        self._rozetta.set_state("idle")
        self._rozetta.set_tip("")
        self._sidebar_chat_name.setText("не выбран")
        self._auth_screen.reset()  # разблокировать форму и кнопку "Войти"
        self._set_step(0)
        self._log.append_success(
            "✅ Сессия забыта на этом компьютере. Авторизация Telegram цела — "
            "снять её можно в самом Telegram, в списке устройств."
        )
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
        worker.chats_loaded.connect(self._on_chats_loaded, Qt.UniqueConnection)
        worker.log_message.connect(self._log.append_info, Qt.UniqueConnection)
        worker.error.connect(self._on_worker_error, Qt.UniqueConnection)
        worker.character_state.connect(self._rozetta.set_state, Qt.UniqueConnection)
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
            lw.log_message.connect(self._log.append_info, Qt.UniqueConnection)
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
        worker.topics_loaded.connect(self._on_topics_loaded, Qt.UniqueConnection)
        worker.log_message.connect(self._log.append_info, Qt.UniqueConnection)
        worker.error.connect(self._on_worker_error, Qt.UniqueConnection)
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
        worker = MembersWorker(
            chat=chat,
            cfg=self._cfg,
            date_from=self._settings_screen.date_from,
            date_to=self._settings_screen.date_to,
        )
        worker.members_loaded.connect(self._settings_screen.populate_members, Qt.UniqueConnection)
        worker.members_loaded.connect(self._cache_members, Qt.UniqueConnection)
        worker.log_message.connect(self._log.append_info, Qt.UniqueConnection)
        worker.error.connect(self._on_worker_error, Qt.UniqueConnection)
        worker.error.connect(
            self._settings_screen.notify_members_failed, Qt.UniqueConnection
        )
        self._start_worker(worker)
        self._rozetta.set_tip("Загружаю участников...")

    def _cache_members(self, members: list) -> None:
        self._members_cache = members
    # ──────────────────────────────────────────────────────────────────────
    # СЛОТЫ: ПАРСИНГ
    # ──────────────────────────────────────────────────────────────────────

    def _set_btn_row_done(self) -> None:
        """
        Ряд после успешной выгрузки: главная кнопка — «Открыть папку».

        Панель шириной 308px не вмещает две подписанные кнопки: запуску
        честно нужно 223px, «📂 Открыть папку» просит 232 при 274 доступных.
        Поэтому меняются ролями — после выгрузки человек идёт смотреть файлы,
        а не запускать заново, и главное действие выглядит главным.
        Запуск остаётся на месте значком с подсказкой, а не исчезает.

        Ширину держит setFixedWidth: растяжку в раскладке двигать не нужно,
        остаток ряда и так достаётся папке — она единственная растяжимая,
        когда запуск зафиксирован, а «Стоп» спрятан. Проверено мутацией:
        снятая растяжка ничего не меняла, значит и ставить её нечестно.
        """
        self._start_btn.setText("▶")
        self._start_btn.setFixedWidth(40)
        self._start_btn.setToolTip("Начать экспорт заново")
        self._open_folder_btn.setVisible(True)

    def _set_btn_row_normal(self) -> None:
        """Обычный ряд: запуск во всю ширину, папки нет."""
        self._open_folder_btn.setVisible(False)
        self._start_btn.setMinimumWidth(0)
        self._start_btn.setMaximumWidth(16777215)
        self._start_btn.setToolTip("")
        self._reset_start_btn_text()

    def _show_open_folder(self, paths: list) -> None:
        """
        Перестраивает ряд под результат: показывает «Открыть папку».

        Папка берётся из первого созданного файла, а не собирается заново из
        названия чата: имя чата проходит через sanitize_filename, и вторая
        сборка легко разойдётся с первой — кнопка повела бы в несуществующую
        папку (тот же класс расхождения, из-за которого CollectResult возит
        db_path готовым).

        Пустой список или исчезнувшая папка — ряд остаётся обычным:
        интерфейс не обещает того, чего нет (правило #27).
        """
        self._output_folder = None

        if not paths:
            self._set_btn_row_normal()
            return
        folder = os.path.dirname(os.path.abspath(str(paths[0])))
        if not os.path.isdir(folder):
            self._set_btn_row_normal()
            return

        self._output_folder = folder
        self._set_btn_row_done()

    def _on_open_folder_clicked(self) -> None:
        """Открывает папку выгрузки в файловом менеджере системы."""
        folder = getattr(self, "_output_folder", None)
        if not folder or not os.path.isdir(folder):
            self._show_toast("Папка не найдена", "error")
            self._set_btn_row_normal()
            return

        # QDesktopServices берёт на себя разницу между Explorer, Finder и
        # xdg-open — сборка идёт под все три платформы (build_binaries.yml).
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(folder)):
            logger.warning("не удалось открыть папку: %s", folder)
            self._show_toast("Не удалось открыть папку", "error")

    def _reset_start_btn_text(self) -> None:
        """Подпись кнопки говорит о результате в момент нажатия."""
        self._start_btn.setText(
            "▶  ВЫГРУЗИТЬ СПИСОК"
            if self._settings_screen.is_members_only()
            else "▶  НАЧАТЬ ЭКСПОРТ"
        )

    def _on_start_btn_clicked(self) -> None:
        """Кнопка НАЧАТЬ ПАРСИНГ в правой панели."""

        params = self._settings_screen.get_params()
        if params is None:
            self._show_toast("Выберите чат перед запуском", "error")
            # Переключить на вкладку чатов для выбора
            if self._current_step >= 1:
                self._switch_tab(1)
            return

        # UI-CLEAN-3 P2: окно «Проверьте перед стартом»
        # N-1: в режиме списка сводка другая — медиа, комментарии и разбивка
        # к результату отношения не имеют (правило #27).
        members_only = self._settings_screen.is_members_only()
        rows = (self._build_members_summary(params) if members_only
                else self._build_start_summary(params))
        dialog = ConfirmStartDialog(rows, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        if members_only:
            self._run_members_export(params)
            return
        self._on_parse_requested(params)

    @staticmethod
    def _period_value(params: ParseParams) -> str:
        """Строка периода для окна подтверждения — одна на обе сводки."""
        if params.date_from or params.date_to:
            d_from = params.date_from.strftime("%d.%m.%Y") if params.date_from else "…"
            d_to = params.date_to.strftime("%d.%m.%Y") if params.date_to else "…"
            return f"{d_from} — {d_to}"
        return "за всё время"

    def _build_members_summary(self, params: ParseParams) -> list:
        """
        N-1: сводка для режима «Список участников».

        Три строки вместо восьми: в этом режиме не скачивается ничего,
        кроме истории для подсчёта, и не создаётся ничего, кроме одного DOCX.
        """
        chat = params.chat or {}
        title = chat.get("title", "—")
        chat_val = f"{title} (канал)" if chat.get("type") == "channel" else title
        return [
            ("Чат", chat_val, False),
            ("Период", self._period_value(params), False),
            ("Результат", "Список участников, один файл DOCX. "
                          "Сообщения не выгружаются", True),
        ]

    def _run_members_export(self, params: ParseParams) -> None:
        """
        N-1: выгрузка списка участников — мимо ParseWorker, STT и ExportWorker.

        Список собирает MembersWorker (скан истории через Telethon, десятки
        секунд), сам DOCX собирается быстро и остаётся в GUI-потоке.
        """
        from features.chats.ui import MembersWorker

        session_file = self._cfg.session_path + ".session"
        if not os.path.exists(session_file):
            self._log.append_error("❌ Нет активной сессии Telegram")
            self._show_toast("Нет активной сессии Telegram", "error")
            return

        self._members_export_chat = params.chat or {}

        self._update_progress(0)
        # Новый прогон — прошлая папка больше не результат этой кнопки,
        # и ряд обязан вернуться к обычному виду до смены подписи ниже.
        self._set_btn_row_normal()
        self._start_btn.setEnabled(False)
        self._start_btn.setText("⏳  СОБИРАЮ СПИСОК...")
        self._settings_screen.set_parsing(True)
        self._rozetta.set_state("process")
        self._rozetta.set_tip("Собираю список участников...")
        self._set_status("busy", "Список участников...")

        worker = MembersWorker(
            chat=self._members_export_chat,
            cfg=self._cfg,
            date_from=params.date_from,
            date_to=params.date_to,
        )
        worker.members_loaded.connect(
            self._on_members_export_loaded, Qt.UniqueConnection
        )
        worker.log_message.connect(self._log.append_info, Qt.UniqueConnection)
        worker.error.connect(self._on_export_error, Qt.UniqueConnection)
        self._start_worker(worker)

    def _on_members_export_loaded(self, users: list) -> None:
        """N-1: список собран → DOCX. Пустой список файлом не становится."""
        from core.utils import sanitize_filename
        from features.export.participants import export_participants_docx

        chat = getattr(self, "_members_export_chat", None) or {}
        title = chat.get("title") or "Export"

        if not users:
            self._on_export_error(
                "участники не найдены — за выбранный период в чате нет "
                "сообщений либо Telegram не отдал историю"
            )
            return

        out_dir = os.path.join(
            str(self._cfg.output_dir), sanitize_filename(title)
        )
        try:
            path = export_participants_docx(users, title, out_dir)
        except Exception as exc:
            logger.exception("_on_members_export_loaded: docx failed")
            self._on_export_error(str(exc))
            return

        self._log.append_success(f"✅ Участников в списке: {len(users)}")
        self._on_export_complete([path])

    def _build_start_summary(self, params: ParseParams) -> list:
        """UI-CLEAN-3: строки сводки для окна подтверждения.

        Returns:
            Список кортежей (название, значение, акцент: bool).
        """
        chat = params.chat or {}
        title = chat.get("title", "—")
        is_channel = chat.get("type") == "channel"
        chat_val = f"{title} (канал)" if is_channel else title

        period_val = self._period_value(params)

        media_names = [
            name for flag, name in (
                (params.download_photo, "фото"),
                (params.download_video, "видео"),
                (params.download_voice, "голосовые"),
                (params.download_videomessage, "кружочки"),
                (params.download_file, "файлы"),
            ) if flag
        ]
        media_val = ", ".join(media_names) if media_names else "только текст"

        if is_channel:
            comments_val = ("скачаем и добавим в документ"
                            if params.include_comments else "не скачиваем")
        else:
            comments_val = "нет (доступны только в каналах)"

        # FEAT-6: считаем от фильтра, а не от params.user_id — при мультивыборе
        # и в режиме «кроме выбранных» user_id всегда None, и строка всегда
        # показывала «все», что было неправдой.
        _uf = self._settings_screen.get_user_filter()
        if _uf.is_active:
            user_val = _uf.header_line(max_names=5)
            if _uf.mode == "include" and params.user_filter_mode == "threads":
                user_val += " · сообщения + ответы"
        elif params.user_id:
            who = params.username or f"ID {params.user_id}"
            mode = ("сообщения + ответы"
                    if params.user_filter_mode == "threads" else "только сообщения")
            user_val = f"{who} · {mode}"
        else:
            user_val = "все"

        formats = [
            f.upper()
            for f in (self._settings_screen.get_export_formats() or ["docx"])
        ]
        split_names = {"none": "одним файлом", "day": "по дням",
                       "month": "по месяцам",
                       "post": "по постам (отдельный файл на каждый пост)"}
        split_val = split_names.get(params.split_mode, params.split_mode)

        rows = [
            ("Чат", chat_val, False),
            ("Период", period_val, False),
            ("Файлы", media_val, False),
            ("Комментарии", comments_val, bool(params.include_comments)),
            ("Участники", user_val, False),
            ("Документ", f"{', '.join(formats)} · {split_val}", False),
        ]

        stt_names = [
            name for flag, name in (
                (params.stt_voice, "голосовые"),
                (params.stt_videomessage, "кружочки"),
            ) if flag
        ]
        if stt_names:
            rows.append(("Речь в текст", ", ".join(stt_names), False))
        # FEAT-5: здесь появится строка «Описание изображений» при включённом VLM

        # ── KB preset stage 10 (UI) ──
        if self._settings_screen.get_build_kb():
            rows.append((self.tr("База знаний для ИИ"), self.tr("✓ Вкл"), True))

        # UI-CLEAN-3 P3: в канале сообщения участников — это комментарии.
        # Участник выбран, а комментарии выключены → документ будет почти пуст.
        if is_channel and params.user_id and not params.include_comments:
            rows.append((
                "⚠️ Внимание",
                "В канале сообщения участников — это комментарии. "
                "Комментарии выключены, поэтому документ по выбранному "
                "участнику окажется почти пустым",
                True,
            ))
        return rows

    def _on_parse_requested(self, params: ParseParams) -> None:
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
            if getattr(sp, "_media_file", None) and sp._media_file.isChecked():
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
                w.wait(30_000)  # max 30 сек (загрузка чатов может быть долгой)

        self._update_progress(0)
        # Новый прогон — прошлая папка больше не результат этой кнопки,
        # и ряд обязан вернуться к обычному виду до смены подписи ниже.
        self._set_btn_row_normal()
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
        worker.log_message.connect(self._log.append_info, Qt.UniqueConnection)
        worker.progress.connect(self._update_progress, Qt.UniqueConnection)
        worker.finished.connect(self._on_parse_finished, Qt.UniqueConnection)
        worker.error.connect(self._on_parse_error, Qt.UniqueConnection)
        worker.character_state.connect(self._rozetta.set_state, Qt.UniqueConnection)
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
        self._reset_start_btn_text()
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
            db_path = os.path.join(chat_dir, DB_FILENAME)

        self._last_collect_result = collect_result
        self._update_progress(0)
        worker = STTWorker(
            db_path=db_path,
            chat_id=chat_id,
            model_size=self._cfg.stt_model,
            language=self._cfg.stt_language,
        )
        worker.log_message.connect(self._log.append_info, Qt.UniqueConnection)
        worker.progress.connect(self._update_progress, Qt.UniqueConnection)
        worker.error.connect(self._on_stt_error, Qt.UniqueConnection)
        worker.finished.connect(self._on_stt_finished_slot, Qt.UniqueConnection)
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
        date_from_str = str(params.date_from) if (params and params.date_from) else None
        date_to_str = str(params.date_to) if (params and params.date_to) else None

        chat_title = (
                getattr(collect_result, "chat_title", None)
                or chat.get("title", "export")
        )
        db_path = getattr(collect_result, "db_path", "") or ""
        if db_path:
            chat_dir = os.path.dirname(db_path)
        else:
            chat_dir = os.path.join(str(self._cfg.output_dir), sanitize_filename(chat_title))
            db_path = os.path.join(chat_dir, DB_FILENAME)

  
        export_params = ExportParams(
            chat_id=chat.get("id"),
            chat_title=chat_title,
            split_mode=split_mode,
            topic_id=chat.get("selected_topic_id"),
            topic_name=chat.get("selected_topic_name"),
            user_id=params.user_id or None,
            username=params.username if params else None,
            user_filter_mode=params.user_filter_mode if params else "none",
            user_filter=self._settings_screen.get_user_filter(),
            include_comments=params.include_comments if params else False,
            output_dir=chat_dir,
            db_path=db_path,
            period_label=getattr(collect_result, "period_label", "alltime"),
            export_formats=self._settings_screen.get_export_formats(),
            ai_split=self._settings_screen.get_ai_split(),
            ai_split_chunk_words=self._settings_screen.get_ai_split_chunk_words() if hasattr(self._settings_screen, 'get_ai_split_chunk_words') else 300_000,
            build_kb=self._settings_screen.get_build_kb(),  # ── KB preset stage 10 (UI) ──
            date_from=date_from_str,
            date_to=date_to_str,
        )

        worker = ExportWorker(export_params)
        worker.log_message.connect(self._log.append_info, Qt.UniqueConnection)
        worker.export_complete.connect(self._on_export_complete, Qt.UniqueConnection)
        worker.error.connect(self._on_export_error, Qt.UniqueConnection)
        worker.character_state.connect(self._rozetta.set_state, Qt.UniqueConnection)
        self._start_worker(worker)

    def _on_export_complete(self, paths: list) -> None:
        self._update_progress(100)
        self._start_btn.setEnabled(True)
        self._reset_start_btn_text()
        self._stop_btn.setVisible(False)
        self._show_open_folder(paths)
        self._settings_screen.set_parsing(False)
        self._rozetta.set_state("success")
        count = len(paths)
        self._rozetta.set_tip(f"Готово! {count} файл(ов)")
        self._log.append_success(f"✅ Экспорт завершён: {count} файл(ов)")
        for p in paths:
            self._log.append_success(f"   📄 {p}")
        self._greeting_sound.play()
        self._set_status("online", "Авторизован")
        self._show_toast(f"Готово! Создано {count} файл(ов)", "success")
        self._set_step(3)

    def _on_export_error(self, message: str) -> None:
        self._update_progress(0)
        self._start_btn.setEnabled(True)
        self._reset_start_btn_text()
        self._stop_btn.setVisible(False)
        self._settings_screen.set_parsing(False)
        self._rozetta.set_state("error")
        self._rozetta.set_tip("Ошибка экспорта")
        self._log.append_error(f"❌ Ошибка экспорта: {message}")
        self._set_status("online", "Авторизован")
        self._show_toast(f"Ошибка экспорта: {message[:50]}", "error")

    # ──────────────────────────────────────────────────────────────────────
    # UPDATE ARCHIVE — кнопка в правой панели (stage 1b, вариант A1)
    # ──────────────────────────────────────────────────────────────────────

    def _has_archive_passport(self, chat: dict) -> bool:
        """Проверяет наличие archive_passport.json в папке чата.

        Папка: <output_dir>/<sanitize_filename(title)>/archive_passport.json
        """
        import os as _os
        from core.utils import sanitize_filename

        title = chat.get("title")
        if not title:
            return False
        try:
            chat_dir = _os.path.join(
                str(self._cfg.output_dir), sanitize_filename(title)
            )
            passport = _os.path.join(chat_dir, "archive_passport.json")
            return _os.path.isfile(passport)
        except Exception:
            return False

    def _show_no_archive_dialog(self, chat: dict) -> None:
        """Диалог «Архив ещё не создан» — предложение пройти первый парсинг."""
        from PySide6.QtWidgets import (
            QDialog, QVBoxLayout, QLabel, QPushButton, QHBoxLayout,
        )

        title = chat.get("title") or "Без названия"
        short = title[:40] + "…" if len(title) > 40 else title

        dlg = QDialog(self)
        dlg.setWindowTitle("Архив ещё не создан")
        dlg.setFixedSize(420, 200)
        dlg.setStyleSheet(f"""
            QDialog {{
                background-color: {BG_PRIMARY};
                color: {TEXT_PRIMARY};
            }}
            QLabel {{
                background: transparent;
                color: {TEXT_PRIMARY};
                font-family: {FONT_FAMILY};
            }}
        """)

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(10)

        icon_lbl = QLabel("\U0001F4E6")  # 📦
        icon_lbl.setStyleSheet("font-size: 28px; background: transparent;")
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon_lbl)

        heading = QLabel("Архив ещё не создан")
        heading.setStyleSheet(
            f"font-size: 15px; font-weight: 700; "
            f"color: {ACCENT_ORANGE}; background: transparent;"
        )
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(heading)

        body = QLabel(
            f"У чата «{short}» нет сохранённого архива.\n"
            "Запустите первый парсинг, чтобы создать архив —\n"
            "затем его можно будет обновлять."
        )
        body.setStyleSheet(
            f"font-size: 12px; color: {TEXT_SECONDARY}; background: transparent;"
        )
        body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body.setWordWrap(True)
        layout.addWidget(body)

        layout.addStretch()

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        btn_row.addStretch()

        btn_cancel = QPushButton("Отмена")
        btn_cancel.setFixedHeight(32)
        btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancel.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                border: 1px solid {BORDER_HEX};
                border-radius: {RADIUS_MD}px;
                color: {TEXT_SECONDARY};
                font-size: 12px;
                font-weight: 500;
                padding: 0 18px;
                font-family: {FONT_FAMILY};
            }}
            QPushButton:hover {{
                border-color: {TEXT_SECONDARY};
                color: {TEXT_PRIMARY};
            }}
        """)
        btn_cancel.clicked.connect(dlg.reject)

        btn_go = QPushButton("▶  Перейти к парсингу")
        btn_go.setFixedHeight(32)
        btn_go.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_go.setStyleSheet(f"""
            QPushButton {{
                background-color: {ACCENT_ORANGE};
                border: 1px solid {ACCENT_ORANGE};
                border-radius: {RADIUS_MD}px;
                color: #ffffff;
                font-size: 12px;
                font-weight: 600;
                padding: 0 18px;
                font-family: {FONT_FAMILY};
            }}
            QPushButton:hover {{
                background-color: #E08500;
                border-color: #E08500;
            }}
        """)
        btn_go.clicked.connect(dlg.accept)

        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_go)
        layout.addLayout(btn_row)

        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._switch_tab(2)  # на вкладку «Настройки парсинга»
            self._show_toast("Настройте параметры и нажмите «Начать парсинг»", "info", 3000)

    # ──────────────────────────────────────────────────────────────────────
    # ОБНОВЛЕНИЕ АРХИВА — Update Archive stage 1 (stub)
    # ──────────────────────────────────────────────────────────────────────

    def _run_update_archive(self, chat: dict) -> None:
        """Запускает фоновое обновление архива чата (Шаг 1 stub)."""
        from features.update_archive.worker import UpdateArchiveWorker

        # Guard: не запускать второй UpdateArchiveWorker
        for w in self._active_workers:
            if isinstance(w, UpdateArchiveWorker):
                logger.warning("_run_update_archive: уже запущен, пропускаем")
                return

        title = chat.get("title", "?") or "?"
        self._set_status("busy", "Обновление архива...")
        self._rozetta.set_state("process")
        self._rozetta.set_tip("Обновляю архив...")
        self._log.append_info(f"\N{CYCLONE} Обновление архива: \u00ab{title}\u00bb")

        worker = UpdateArchiveWorker(chat=chat, cfg=self._cfg)
        worker.log_message.connect(self._log.append_info, Qt.UniqueConnection)
        worker.progress.connect(self._update_progress, Qt.UniqueConnection)
        worker.character_state.connect(self._rozetta.set_state, Qt.UniqueConnection)
        worker.finished.connect(self._on_update_archive_finished, Qt.UniqueConnection)
        worker.error.connect(self._on_update_archive_error, Qt.UniqueConnection)
        self._start_worker(worker)

    def _on_update_archive_finished(self, report: dict) -> None:
        """Слот: UpdateArchiveWorker.finished — показать отчёт."""
        from features.update_archive.report_dialog import UpdateReportDialog

        self._update_progress(100)
        self._rozetta.set_state("success")
        self._rozetta.set_tip("Архив обновлён")
        self._set_status("online", "Авторизован")
        self._log.append_success("\N{WHITE HEAVY CHECK MARK} Обновление архива завершено")

        # Показать диалог отчёта
        dlg = UpdateReportDialog(report, parent=self)
        dlg.exec()

        self._show_toast("Архив обновлён", "success")

    def _on_update_archive_error(self, message: str) -> None:
        """Слот: UpdateArchiveWorker.error."""
        self._update_progress(0)
        self._rozetta.set_state("error")
        self._rozetta.set_tip("Ошибка обновления")
        self._set_status("online", "Авторизован")
        self._log.append_error(f"\N{CROSS MARK} Ошибка обновления архива: {message}")
        self._show_toast(f"Ошибка: {message[:60]}", "error")

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
        self._reset_start_btn_text()
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
