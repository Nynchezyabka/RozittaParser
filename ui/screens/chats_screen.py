"""
ui/screens/chats_screen.py — Экран выбора чата

Workflow:
    1. ChatsWorker загружает диалоги → populate() распределяет по 4 секциям
    2. Секции: Каналы / Группы / Форумы / Диалоги — коллапсируемые
    3. Каналы с linked_chat_id → бейдж «💬 обсуждение»
    4. Форумы → кнопка «📂 ветки» → TopicsWorker → QComboBox топиков
    5. chat_selected(int, str) → переход к парсингу

Исправления 2026-02-22:
    - KeyError на chat['emoji']: поле отсутствует в API, заменено на type-иконки
    - Текст невидим: QListWidget::item не наследует color от QListWidget.
      Решение: полный переход на QWidget-карточки с явными цветами в CSS родителя.
    - Добавлены коллапсируемые секции по типу чата.

Совместимость с main_window.py:
    ChatsScreen.chat_selected = Signal(int, str)  — сохранена сигнатура
    ChatsScreen.load_chats()                       — сохранён публичный метод
    ChatsScreen.log_message = Signal(str)          — сохранена
    ChatsScreen.character_state = Signal(str)      — сохранена
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget,
)

from config import AppConfig
from features.chats.ui import ChatsWorker, TopicsWorker

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Константы (совпадают с HTML-макетом Rozitta_prototype.html)
# ─────────────────────────────────────────────────────────────────────────────

_TYPE_STYLES: dict = {
    "channel": {
        "icon": "📢", "label": "Каналы",
        "accent": "#FF9500",
        "icon_bg": "rgba(255,149,0,0.2)",
        "badge_bg": "rgba(255,149,0,0.15)",
    },
    "group": {
        "icon": "👥", "label": "Группы",
        "accent": "#FF6BC9",
        "icon_bg": "rgba(255,107,201,0.2)",
        "badge_bg": "rgba(255,107,201,0.15)",
    },
    "forum": {
        "icon": "💬", "label": "Форумы",
        "accent": "#FF6BC9",
        "icon_bg": "rgba(255,107,201,0.2)",
        "badge_bg": "rgba(255,107,201,0.15)",
    },
    "private": {
        "icon": "👤", "label": "Диалоги",
        "accent": "#0096FF",
        "icon_bg": "rgba(0,150,255,0.2)",
        "badge_bg": "rgba(0,150,255,0.15)",
    },
}
_SECTION_ORDER = ("channel", "group", "forum", "private")

_TEXT_TITLE = "#F0F0F0"
_TEXT_META = "#CCCCCC"


def _fmt(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


# ─────────────────────────────────────────────────────────────────────────────
# ChatItemWidget
# ─────────────────────────────────────────────────────────────────────────────

class ChatItemWidget(QWidget):
    """
    Карточка одного чата.

    Критически важно: _refresh_style() включает правила для дочерних QLabel
    прямо в stylesheet РОДИТЕЛЯ. Qt CSS-каскад гарантирует видимость текста
    при любом динамическом изменении фона через setStyleSheet().
    """
    clicked = Signal(object)  # chat dict
    dclicked = Signal(object)  # chat dict
    topics_clicked = Signal(int)  # chat_id

    def __init__(self, chat: dict, parent=None) -> None:
        super().__init__(parent)
        self._chat = chat
        self._sel = False
        self._hov = False

        ctype = chat.get("type", "private")
        s = _TYPE_STYLES.get(ctype, _TYPE_STYLES["private"])
        self._accent = s["accent"]
        self._icon_bg = s["icon_bg"]

        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(72)

        row = QHBoxLayout(self)
        row.setContentsMargins(10, 6, 10, 6)
        row.setSpacing(10)

        # Иконка
        ico = QLabel(s["icon"])
        ico.setObjectName("chatIco")
        ico.setFixedSize(38, 38)
        ico.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ico.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        row.addWidget(ico)

        # Текстовый блок
        col = QVBoxLayout()
        col.setSpacing(3)
        col.setContentsMargins(0, 0, 0, 0)

        self._tlbl = QLabel(chat.get("title") or "Без названия")
        self._tlbl.setObjectName("chatTitle")
        self._tlbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._tlbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        col.addWidget(self._tlbl)

        # Мета
        parts: list = []
        if u := chat.get("username"):
            parts.append(f"@{u}")
        cnt = chat.get("participants_count") or 0
        if cnt:
            parts.append(f"{_fmt(cnt)} участников")
        meta_text = " · ".join(parts) if parts else f"ID: {chat.get('id', '')}"

        meta_row = QHBoxLayout()
        meta_row.setSpacing(6)
        meta_row.setContentsMargins(0, 0, 0, 0)

        mlbl = QLabel(meta_text)
        mlbl.setObjectName("chatMeta")
        mlbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        meta_row.addWidget(mlbl)

        # Бейдж для канала с linked group
        if ctype == "channel" and chat.get("linked_chat_id"):
            badge = QPushButton("💬 обсуждение")
            badge.setObjectName("linkedBadge")
            badge.setFixedHeight(20)
            badge.setCursor(Qt.CursorShape.PointingHandCursor)
            badge.clicked.connect(lambda: self.clicked.emit(self._chat))
            meta_row.addWidget(badge)

        # Кнопка «загрузить ветки» для форума
        if ctype == "forum":
            topic_btn = QPushButton("📂 ветки")
            topic_btn.setObjectName("topicBtn")
            topic_btn.setFixedHeight(20)
            topic_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            cid = chat.get("id", 0)
            topic_btn.clicked.connect(
                lambda _=False, c=cid: self.topics_clicked.emit(c)
            )
            meta_row.addWidget(topic_btn)

        meta_row.addStretch()
        col.addLayout(meta_row)
        row.addLayout(col, stretch=1)

        if cnt:
            cl = QLabel(_fmt(cnt))
            cl.setObjectName("chatCount")
            cl.setFixedWidth(40)
            cl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            cl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            row.addWidget(cl)

        self._refresh_style()

    def _refresh_style(self) -> None:
        """
        Все цвета дочерних QLabel задаются ЗДЕСЬ, в stylesheet родителя.
        Это единственный надёжный способ гарантировать видимость текста при
        динамическом изменении фона через setStyleSheet().
        """
        if self._sel:
            bg, br = "rgba(255,149,0,0.12)", "#FF9500"
        elif self._hov:
            bg, br = "rgba(255,255,255,0.07)", "rgba(255,255,255,0.08)"
        else:
            bg, br = "rgba(255,255,255,0.03)", "rgba(255,255,255,0.08)"

        self.setStyleSheet(f"""
            ChatItemWidget {{
                background: {bg};
                border: 1px solid {br};
                border-radius: 8px;
            }}
            ChatItemWidget QLabel#chatTitle {{
                color: {_TEXT_TITLE};
                font-size: 12px;
                font-weight: bold;
                background: transparent;
            }}
            ChatItemWidget QLabel#chatMeta {{
                color: {_TEXT_META};
                font-size: 10px;
                background: transparent;
            }}
            ChatItemWidget QLabel#chatCount {{
                color: {self._accent};
                font-size: 10px;
                font-weight: bold;
                background: transparent;
            }}
            ChatItemWidget QLabel#chatIco {{
                background: {self._icon_bg};
                border-radius: 19px;
                font-size: 18px;
            }}
            ChatItemWidget QPushButton#linkedBadge {{
                background: rgba(255,107,201,0.15);
                color: #FF6BC9;
                border: 1px solid rgba(255,107,201,0.5);
                border-radius: 10px;
                font-size: 9px;
                padding: 0 6px;
            }}
            ChatItemWidget QPushButton#topicBtn {{
                background: transparent;
                color: #FF6BC9;
                border: 1px solid rgba(255,107,201,0.5);
                border-radius: 10px;
                font-size: 9px;
                padding: 0 6px;
            }}
            ChatItemWidget QPushButton#topicBtn:hover {{
                background: #FF6BC9;
                color: #2B2B2B;
            }}
        """)

    def set_selected(self, v: bool) -> None:
        self._sel = v
        self._refresh_style()

    def enterEvent(self, _e) -> None:
        self._hov = True
        if not self._sel:
            self._refresh_style()

    def leaveEvent(self, _e) -> None:
        self._hov = False
        if not self._sel:
            self._refresh_style()

    def mousePressEvent(self, _e) -> None:
        self.clicked.emit(self._chat)

    def mouseDoubleClickEvent(self, _e) -> None:
        self.dclicked.emit(self._chat)

    @property
    def chat(self) -> dict:
        return self._chat

    def matches(self, q: str) -> bool:
        return (
                q in (self._chat.get("title") or "").lower()
                or q in (self._chat.get("username") or "").lower()
        )


# ─────────────────────────────────────────────────────────────────────────────
# SectionHeaderWidget
# ─────────────────────────────────────────────────────────────────────────────

class SectionHeaderWidget(QWidget):
    toggled = Signal(bool)

    def __init__(self, chat_type: str, count: int = 0,
                 expanded: bool = True, parent=None) -> None:
        super().__init__(parent)
        self._exp = expanded
        s = _TYPE_STYLES.get(chat_type, _TYPE_STYLES["private"])

        self.setFixedHeight(44)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setStyleSheet("""
            SectionHeaderWidget {
                background: rgba(255,255,255,0.04);
                border-radius: 8px;
            }
            SectionHeaderWidget:hover {
                background: rgba(255,255,255,0.07);
            }
            SectionHeaderWidget QLabel { background: transparent; }
        """)

        row = QHBoxLayout(self)
        row.setContentsMargins(10, 0, 10, 0)
        row.setSpacing(8)

        ico = QLabel(s["icon"])
        ico.setFixedSize(28, 28)
        ico.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ico.setStyleSheet(
            f"background:{s['icon_bg']};border-radius:14px;font-size:14px;"
        )
        row.addWidget(ico)

        lbl = QLabel(s["label"])
        lbl.setStyleSheet(
            f"color:{s['accent']};font-size:13px;font-weight:bold;"
        )
        row.addWidget(lbl)
        row.addStretch()

        self._cnt = QLabel(str(count))
        self._cnt.setFixedSize(28, 18)
        self._cnt.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._cnt.setStyleSheet(
            f"background:{s['badge_bg']};color:{s['accent']};"
            f"border-radius:9px;font-size:11px;font-weight:bold;"
        )
        row.addWidget(self._cnt)

        self._arr = QLabel()
        self._arr.setFixedSize(16, 16)
        self._arr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._arr.setStyleSheet(f"color:{_TEXT_META};font-size:14px;")
        row.addWidget(self._arr)
        self._set_arrow()

    def _set_arrow(self) -> None:
        self._arr.setText("∨" if self._exp else "›")

    def mousePressEvent(self, _e) -> None:
        self._exp = not self._exp
        self._set_arrow()
        self.toggled.emit(self._exp)

    def update_count(self, n: int) -> None:
        self._cnt.setText(str(n))


# ─────────────────────────────────────────────────────────────────────────────
# CollapsibleSection
# ─────────────────────────────────────────────────────────────────────────────

class CollapsibleSection(QWidget):
    item_clicked = Signal(object)
    item_dclicked = Signal(object)
    topics_clicked = Signal(int)

    def __init__(self, chat_type: str, parent=None) -> None:
        super().__init__(parent)
        self._items: List[ChatItemWidget] = []
        self._sel_w: Optional[ChatItemWidget] = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 4)
        root.setSpacing(3)

        self._hdr = SectionHeaderWidget(chat_type, count=0, expanded=True)
        self._hdr.toggled.connect(self._body.setVisible)
        root.addWidget(self._hdr)

        self._body = QWidget()
        self._body.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._body.setStyleSheet("background: transparent;")
        self._bl = QVBoxLayout(self._body)
        self._bl.setContentsMargins(0, 2, 0, 2)
        self._bl.setSpacing(3)
        root.addWidget(self._body)

    def populate(self, chats: List[dict]) -> None:
        for w in self._items:
            self._bl.removeWidget(w)
            w.deleteLater()
        self._items.clear()
        self._sel_w = None

        for chat in chats:
            w = ChatItemWidget(chat, parent=self._body)
            w.clicked.connect(self._on_click)
            w.dclicked.connect(self.item_dclicked)
            w.topics_clicked.connect(self.topics_clicked)
            self._bl.addWidget(w)
            self._items.append(w)

        self._hdr.update_count(len(chats))
        self.setVisible(bool(chats))

    def filter_by_query(self, q: str) -> int:
        vis = 0
        for w in self._items:
            show = (not q) or w.matches(q)
            w.setVisible(show)
            if show:
                vis += 1
        self._hdr.update_count(vis)
        self.setVisible(vis > 0)
        return vis

    def clear_selection(self) -> None:
        if self._sel_w:
            self._sel_w.set_selected(False)
            self._sel_w = None

    def get_selected_chat(self) -> Optional[dict]:
        return self._sel_w.chat if self._sel_w else None

    def _on_click(self, chat: dict) -> None:
        target_id = chat.get("id")
        for w in self._items:
            if w.chat.get("id") == target_id:
                if self._sel_w and self._sel_w is not w:
                    self._sel_w.set_selected(False)
                w.set_selected(True)
                self._sel_w = w
        self.item_clicked.emit(chat)


# ─────────────────────────────────────────────────────────────────────────────
# CollapsibleChatsWidget
# ─────────────────────────────────────────────────────────────────────────────

class CollapsibleChatsWidget(QScrollArea):
    """QScrollArea с 4 коллапсируемыми секциями."""
    item_selected = Signal(dict)
    item_activated = Signal(dict)
    topics_clicked = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setStyleSheet("""
            QScrollArea { background: transparent; border: none; }
            QScrollBar:vertical {
                background: rgba(0,0,0,0.2); width: 5px; border-radius: 2px;
            }
            QScrollBar::handle:vertical {
                background: rgba(255,255,255,0.15); border-radius: 2px; min-height: 20px;
            }
            QScrollBar::handle:vertical:hover { background: rgba(255,255,255,0.3); }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        """)

        ctr = QWidget()
        ctr.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(ctr)
        lay.setContentsMargins(0, 0, 4, 0)
        lay.setSpacing(6)

        self._sections: Dict[str, CollapsibleSection] = {}
        for t in _SECTION_ORDER:
            sec = CollapsibleSection(t, parent=ctr)
            sec.item_clicked.connect(self._on_sel)
            sec.item_dclicked.connect(self.item_activated)
            sec.topics_clicked.connect(self.topics_clicked)
            lay.addWidget(sec)
            self._sections[t] = sec
            sec.setVisible(False)

        lay.addStretch()
        self.setWidget(ctr)
        self._cur_sec: Optional[CollapsibleSection] = None

    def populate(self, chats: List[dict]) -> None:
        grouped: Dict[str, List[dict]] = {t: [] for t in _SECTION_ORDER}
        for c in chats:
            t = c.get("type", "private")
            if t not in grouped:
                t = "private"
            grouped[t].append(c)
        for t, items in grouped.items():
            if t in self._sections:
                self._sections[t].populate(items)

    def filter_by_text(self, text: str) -> None:
        q = text.strip().lower()
        for sec in self._sections.values():
            sec.filter_by_query(q)

    def get_selected_chat(self) -> Optional[dict]:
        return self._cur_sec.get_selected_chat() if self._cur_sec else None

    def _on_sel(self, chat: dict) -> None:
        t = chat.get("type", "private")
        new_sec = self._sections.get(t) or self._sections["private"]
        if self._cur_sec and self._cur_sec is not new_sec:
            self._cur_sec.clear_selection()
        self._cur_sec = new_sec
        self.item_selected.emit(chat)


# ─────────────────────────────────────────────────────────────────────────────
# ChatsScreen  (публичный интерфейс совместим с main_window.py)
# ─────────────────────────────────────────────────────────────────────────────

class ChatsScreen(QWidget):
    """
    Главный экран выбора чата.

    Signals (сигнатура совместима с main_window.py):
        chat_selected(int, str) — chat_id, chat_title
        log_message(str)
        character_state(str)
    """
    chat_selected = Signal(int, str)  # chat_id, chat_title (совместимо с MW)
    log_message = Signal(str)
    character_state = Signal(str)

    def __init__(self, cfg: AppConfig, parent=None) -> None:
        super().__init__(parent)
        self._cfg = cfg
        self._chats_worker: Optional[ChatsWorker] = None
        self._topics_worker: Optional[TopicsWorker] = None
        self._sel_chat: Optional[dict] = None
        self._topics: Dict[int, str] = {}
        self._build_ui()

    # ── Public API ────────────────────────────────────────────────────

    def load_chats(self) -> None:
        """Запускает ChatsWorker для загрузки диалогов."""
        if self._chats_worker and self._chats_worker.isRunning():
            return
        self._set_loading(True)
        self._chats_worker = ChatsWorker(self._cfg)
        self._chats_worker.chats_loaded.connect(self._on_chats_loaded)
        self._chats_worker.log_message.connect(self.log_message.emit)
        self._chats_worker.error.connect(self._on_chats_error)
        self._chats_worker.character_state.connect(self.character_state.emit)
        self._chats_worker.start()
        self.log_message.emit("📥 Загрузка списка чатов...")
        self.character_state.emit("working")

    # ── UI ────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(12)

        # Заголовок + статус + обновить
        hdr = QHBoxLayout()
        hl = QLabel("📂 Ваши чаты")
        hl.setStyleSheet(
            "color:#F0F0F0;font-size:16px;font-weight:bold;background:transparent;"
        )
        hdr.addWidget(hl)
        hdr.addStretch()

        self._status = QLabel("")
        self._status.setStyleSheet("color:#CCCCCC;font-size:11px;background:transparent;")
        hdr.addWidget(self._status)

        self._btn_ref = QPushButton("↻")
        self._btn_ref.setFixedSize(32, 32)
        self._btn_ref.setToolTip("Обновить список чатов")
        self._btn_ref.setStyleSheet("""
            QPushButton {
                background: rgba(255,255,255,0.05); color: #CCCCCC;
                border: 1px solid rgba(255,255,255,0.1);
                border-radius: 6px; font-size: 16px;
            }
            QPushButton:hover { background: rgba(255,255,255,0.1); color: #F0F0F0; }
            QPushButton:pressed { background: rgba(255,149,0,0.2); }
            QPushButton:disabled { color: rgba(255,255,255,0.2); }
        """)
        self._btn_ref.clicked.connect(self._on_refresh)
        hdr.addWidget(self._btn_ref)
        root.addLayout(hdr)

        # Поиск
        self._search = QLineEdit()
        self._search.setPlaceholderText("🔍  Поиск по чатам...")
        self._search.setClearButtonEnabled(True)
        self._search.setStyleSheet("""
            QLineEdit {
                background: rgba(0,0,0,0.25); color: #F0F0F0;
                border: 1px solid rgba(255,255,255,0.1);
                border-radius: 8px; padding: 8px 12px; font-size: 12px;
            }
            QLineEdit:focus { border-color: #FF9500; }
        """)
        self._search.textChanged.connect(self._on_search)
        root.addWidget(self._search)

        # Список
        self._chats_widget = CollapsibleChatsWidget(self)
        self._chats_widget.item_selected.connect(self._on_sel)
        self._chats_widget.item_activated.connect(self._on_activated)
        self._chats_widget.topics_clicked.connect(self._load_topics)
        root.addWidget(self._chats_widget, stretch=1)

        # Блок топиков (скрыт до выбора форума)
        self._topics_frame = QFrame()
        self._topics_frame.setVisible(False)
        self._topics_frame.setStyleSheet("""
            QFrame {
                background: rgba(255,107,201,0.08);
                border: 1px solid rgba(255,107,201,0.3);
                border-radius: 8px;
            }
            QFrame QLabel { background: transparent; color: #CCCCCC; font-size: 11px; }
        """)
        tf_lay = QHBoxLayout(self._topics_frame)
        tf_lay.setContentsMargins(12, 8, 12, 8)
        tf_lay.addWidget(QLabel("📁 Ветка:"))
        self._topics_combo = QComboBox()
        self._topics_combo.setStyleSheet("""
            QComboBox {
                background: rgba(0,0,0,0.3); color: #F0F0F0;
                border: 1px solid rgba(255,255,255,0.15);
                border-radius: 6px; padding: 4px 8px; font-size: 12px;
            }
            QComboBox::drop-down { border: none; }
        """)
        tf_lay.addWidget(self._topics_combo, stretch=1)
        root.addWidget(self._topics_frame)

        # Footer
        footer = QFrame()
        footer.setStyleSheet("""
            QFrame {
                background: rgba(0,0,0,0.2);
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 8px;
            }
            QFrame QLabel { background: transparent; color: #CCCCCC; font-size: 11px; }
        """)
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(12, 8, 12, 8)

        self._sel_lbl = QLabel("Выбрано: —")
        self._sel_lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        fl.addWidget(self._sel_lbl)

        self._btn_open = QPushButton("Выбрать чат  ▶")
        self._btn_open.setEnabled(False)
        self._btn_open.setFixedHeight(32)
        self._btn_open.setMinimumWidth(130)
        self._btn_open.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 #FF9500, stop:1 #FF6BC9);
                color: white; border: none; border-radius: 6px;
                font-size: 12px; font-weight: bold; padding: 0 16px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 #E08600, stop:1 #E06BC9);
            }
            QPushButton:pressed { background: #CC7700; }
            QPushButton:disabled {
                background: rgba(255,255,255,0.05); color: rgba(255,255,255,0.2);
            }
        """)
        self._btn_open.clicked.connect(self._confirm_selection)
        fl.addWidget(self._btn_open)
        root.addWidget(footer)

    # ── Slots ─────────────────────────────────────────────────────────

    def _on_refresh(self) -> None:
        self._search.clear()
        self._topics_frame.setVisible(False)
        self.load_chats()

    def _on_search(self, text: str) -> None:
        self._chats_widget.filter_by_text(text)

    def _on_sel(self, chat: dict) -> None:
        self._sel_chat = chat
        name = chat.get("title", "?")
        cid = chat.get("id", "")
        self._sel_lbl.setText(f"Выбрано: {name}  ({cid})")
        self._btn_open.setEnabled(True)
        # Форум — подставляем топики если уже загружены
        if chat.get("type") == "forum":
            self._topics_frame.setVisible(True)
        else:
            self._topics_frame.setVisible(False)

    def _on_activated(self, chat: dict) -> None:
        self._sel_chat = chat
        self._confirm_selection()

    @Slot(list)
    def _on_chats_loaded(self, chats: List[dict]) -> None:
        self._chats_widget.populate(chats)
        self._status.setText(f"{len(chats)} чатов")
        self._set_loading(False)
        self.log_message.emit(f"✅ Загружено {len(chats)} чатов")
        self.character_state.emit("success")

    @Slot(str)
    def _on_chats_error(self, msg: str) -> None:
        self._set_loading(False)
        self._status.setText("Ошибка загрузки")
        self.log_message.emit(f"❌ Ошибка загрузки чатов: {msg}")
        self.character_state.emit("error")

    def _load_topics(self, chat_id: int) -> None:
        """Запускает TopicsWorker для загрузки веток форума."""
        if self._topics_worker and self._topics_worker.isRunning():
            return
        self.log_message.emit("📁 Загрузка веток форума...")
        self._topics_combo.clear()
        self._topics_frame.setVisible(True)
        self._topics_worker = TopicsWorker(self._cfg, chat_id)
        self._topics_worker.topics_loaded.connect(self._on_topics_loaded)
        self._topics_worker.log_message.connect(self.log_message.emit)
        self._topics_worker.error.connect(
            lambda e: self.log_message.emit(f"⚠️ Ветки: {e}")
        )
        self._topics_worker.start()

    @Slot(dict)
    def _on_topics_loaded(self, topics: Dict[int, str]) -> None:
        self._topics = topics
        self._topics_combo.clear()
        self._topics_combo.addItem("Все ветки", None)
        for tid, ttitle in topics.items():
            self._topics_combo.addItem(ttitle, tid)
        self.log_message.emit(f"✅ Загружено веток: {len(topics)}")

    def _confirm_selection(self) -> None:
        chat = self._sel_chat or self._chats_widget.get_selected_chat()
        if not chat:
            return
        chat_id = chat.get("id")
        chat_title = chat.get("title", "?")
        self.log_message.emit(f"✅ Выбран: {chat_title}")
        self.chat_selected.emit(chat_id, chat_title)

    def _set_loading(self, loading: bool) -> None:
        self._btn_ref.setEnabled(not loading)
        self._search.setEnabled(not loading)
        if loading:
            self._status.setText("Загрузка...")
            self._btn_open.setEnabled(False)
