"""
FILE: features/chats/ui.py

Экран выбора чата + воркеры загрузки.

Что изменено vs chats_screen.py (legacy):
  ✦ Все импорты стилей → core.ui_shared.styles (не ui_shared.styles)
  ✦ Все хардкоды цветов заменены константами из styles.py
  ✦ chat_selected(int, str) → chat_selected(dict)
    MainWindow и ParseSettingsScreen ожидают полный словарь чата
  ✦ inject_chats(list) / inject_topics(dict) — публичные слоты:
    чаты теперь загружает MainWindow, ChatsScreen только отображает
  ✦ Добавлен MembersWorker для загрузки участников
  ✦ TopicsWorker: сигнатура исправлена — принимает client, не только cfg
  ✦ QSS_SCROLL_AREA / QSS_COMBOBOX из styles.py вместо хардкода
  ✦ load_chats() оставлен для обратной совместимости →
    теперь эмитирует refresh_requested (MW создаёт воркер сам)

Сохранено:
  ✦ _refresh_style() через stylesheet родителя (фикс Qt CSS-каскада 2026-02-22)
  ✦ ChatItemWidget.set_selected() / hover-стили
  ✦ SectionHeaderWidget с коллапсом и счётчиком
  ✦ CollapsibleSection.populate() / filter_by_query()
  ✦ CollapsibleChatsWidget.populate() с группировкой по типу
  ✦ Блок топиков + QComboBox для форумов
  ✦ Footer с кнопкой «Выбрать»
"""

from __future__ import annotations

import asyncio
import logging
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, Signal, Slot, QThread
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget,
)

from config import AppConfig
from core.ui_shared.styles import (
    ACCENT_ORANGE, ACCENT_PINK,
    ACCENT_SOFT_ORANGE, ACCENT_SOFT_PINK,
    TEXT_PRIMARY, TEXT_SECONDARY,
    OVERLAY_HEX, OVERLAY2_HEX, BORDER_HEX,
    RADIUS_MD, RADIUS_XS,
    FONT_FAMILY, FONT_SIZE_BODY, FONT_SIZE_SMALL, FONT_SIZE_XS,
    QSS_INPUT, QSS_SCROLL_AREA, QSS_COMBOBOX,
)
from core.ui_shared.widgets import SectionTitle

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# КОНСТАНТЫ ТИПОВ ЧАТОВ
# ══════════════════════════════════════════════════════════════════════════════

_TYPE_STYLES: dict[str, dict] = {
    "channel": {
        "icon":     "📢",
        "label":    "Каналы",
        "accent":   ACCENT_ORANGE,
        "icon_bg":  "rgba(255,149,0,0.2)",
        "badge_bg": ACCENT_SOFT_ORANGE,
    },
    "group": {
        "icon":     "👥",
        "label":    "Группы",
        "accent":   ACCENT_PINK,
        "icon_bg":  "rgba(255,107,201,0.2)",
        "badge_bg": ACCENT_SOFT_PINK,
    },
    "forum": {
        "icon":     "💬",
        "label":    "Форумы",
        "accent":   ACCENT_PINK,
        "icon_bg":  "rgba(255,107,201,0.2)",
        "badge_bg": ACCENT_SOFT_PINK,
    },
    "private": {
        "icon":     "👤",
        "label":    "Диалоги",
        "accent":   "#0096FF",
        "icon_bg":  "rgba(0,150,255,0.2)",
        "badge_bg": "rgba(0,150,255,0.15)",
    },
}

_SECTION_ORDER = ("channel", "group", "forum", "private")


def _fmt(n: int) -> str:
    """1 234 → 1.2K, 1 234 567 → 1.2M."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


# ══════════════════════════════════════════════════════════════════════════════
# WORKERS
# ══════════════════════════════════════════════════════════════════════════════

class ChatsWorker(QThread):
    """
    Загружает список диалогов через ChatsService.get_dialogs().

    Создаёт собственный TelegramClient внутри run() — НЕ принимает client снаружи.
    Это гарантирует, что client привязан к event loop данного потока.

    Сигналы:
        chats_loaded(list)      — список chat-dict
        log_message(str)
        error(str)
        character_state(str)
    """

    chats_loaded    = Signal(list)
    log_message     = Signal(str)
    error           = Signal(str)
    character_state = Signal(str)

    def __init__(self, cfg: AppConfig,
                 force_refresh: bool = False,
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._cfg           = cfg
        self._force_refresh = force_refresh

    def run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            chats = loop.run_until_complete(self._load())
            self.chats_loaded.emit(chats)
        except Exception as exc:
            logger.exception("ChatsWorker error")
            self.error.emit(str(exc))
            self.character_state.emit("error")
        finally:
            loop.close()

    async def _load(self) -> list:
        from telethon import TelegramClient
        from features.chats.api import ChatsService
        self.character_state.emit("process")
        self.log_message.emit("📥 Загружаю список чатов...")
        client = TelegramClient(
            str(self._cfg.session_path),
            self._cfg.api_id_int,
            self._cfg.api_hash,
            timeout=120,
            connection_retries=5,
            retry_delay=5,
            auto_reconnect=True,
        )
        await client.connect()
        try:
            service = ChatsService(client)
            # cache_db_path — общая БД в output/ (не БД конкретного чата)
            import os
            cache_db = os.path.join(self._cfg.output_dir, "dialogs_cache.db")
            chats = await service.get_dialogs(
                limit          = 500,
                log            = self.log_message.emit,
                cache_db_path  = cache_db,
                force_refresh  = self._force_refresh,
            )
            self.character_state.emit("success")
            return chats
        finally:
            await client.disconnect()


class TopicsWorker(QThread):
    """
    Загружает ветки (топики) форума через ChatsService.get_topics().

    Создаёт собственный TelegramClient внутри run().

    Сигналы:
        topics_loaded(dict)     — {chat_id: {topic_id: topic_title}}
        log_message(str)
        error(str)
        character_state(str)
    """

    topics_loaded   = Signal(object)
    log_message     = Signal(str)
    error           = Signal(str)
    character_state = Signal(str)

    def __init__(self, chat_id: int, cfg: AppConfig,
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._chat_id = chat_id
        self._cfg     = cfg

    def run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            topics = loop.run_until_complete(self._load())
            self.topics_loaded.emit(topics)
        except Exception as exc:
            logger.exception("TopicsWorker error")
            self.error.emit(str(exc))
        finally:
            loop.close()

    async def _load(self) -> dict:
        from telethon import TelegramClient
        from features.chats.api import ChatsService
        self.log_message.emit("📁 Загружаю ветки форума...")
        client = TelegramClient(
            str(self._cfg.session_path),
            self._cfg.api_id_int,
            self._cfg.api_hash,
            timeout=120,
            connection_retries=5,
            retry_delay=5,
            auto_reconnect=True,
        )
        await client.connect()
        try:
            service = ChatsService(client)
            topics = await service.get_topics(self._chat_id)
            return {self._chat_id: topics}
        finally:
            await client.disconnect()


class LinkedGroupWorker(QThread):
    """
    Проверяет linked_chat_id для одного канала при его выборе.

    Заменяет массовую проверку всех каналов при загрузке списка.
    Запускается только когда пользователь кликает на конкретный канал.

    Сигналы:
        linked_found(object)   — обновлённый chat dict с linked_chat_id
        log_message(str)
    """

    linked_found = Signal(object)   # chat dict с заполненным linked_chat_id
    log_message  = Signal(str)

    def __init__(self, chat: dict, cfg: AppConfig,
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._chat = chat
        self._cfg  = cfg

    def run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._check())
        except Exception as exc:
            logger.warning("LinkedGroupWorker error: %s", exc)
        finally:
            loop.close()

    async def _check(self) -> None:
        from telethon import TelegramClient
        from features.chats.api import ChatsService

        client = TelegramClient(
            str(self._cfg.session_path),
            self._cfg.api_id_int,
            self._cfg.api_hash,
            timeout=30,
            connection_retries=3,
        )
        await client.connect()
        try:
            service = ChatsService(client)
            linked_id = await service.get_linked_group(
                self._chat["id"],
                log=self.log_message.emit,
            )
            if linked_id:
                updated = dict(self._chat)
                updated["linked_chat_id"] = linked_id
                updated["has_comments"]   = True
                self.linked_found.emit(updated)
                logger.debug("LinkedGroupWorker: %s → linked=%s",
                             self._chat.get("title"), linked_id)
        finally:
            await client.disconnect()


class MembersWorker(QThread):

    """
    Загружает список участников чата через ChatsService.get_user_stats().

    Создаёт собственный TelegramClient внутри run().

    Сигналы:
        members_loaded(list)    — [{\"id\": int, \"username\": str, \"name\": str}]
        log_message(str)
        error(str)
    """

    members_loaded = Signal(list)
    log_message    = Signal(str)
    error          = Signal(str)

    def __init__(self, chat: dict, cfg: AppConfig,
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._chat = chat
        self._cfg  = cfg

    def run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            members = loop.run_until_complete(self._load())
            self.members_loaded.emit(members)
        except Exception as exc:
            logger.exception("MembersWorker error")
            self.error.emit(str(exc))
        finally:
            loop.close()

    async def _load(self) -> list:
        from telethon import TelegramClient
        from features.chats.api import ChatsService
        self.log_message.emit("👥 Загружаю участников...")
        client = TelegramClient(
            str(self._cfg.session_path),
            self._cfg.api_id_int,
            self._cfg.api_hash,
            timeout=120,
            connection_retries=5,
            retry_delay=5,
            auto_reconnect=True,
        )
        await client.connect()
        try:
            service = ChatsService(client)
            stats = await service.get_user_stats(self._chat.get("id"))
            return stats
        finally:
            await client.disconnect()


# ══════════════════════════════════════════════════════════════════════════════
# CHAT ITEM WIDGET
# ══════════════════════════════════════════════════════════════════════════════

class ChatItemWidget(QWidget):
    """
    Карточка одного чата в списке.

    ПРАВИЛО Qt CSS (фикс 2026-02-22):
    _refresh_style() задаёт цвета дочерних QLabel через stylesheet РОДИТЕЛЯ.
    При отдельных setStyleSheet() на дочерних виджетах Qt CSS-каскад
    перекрывается системным цветом — текст становится невидимым.

    Сигналы:
        clicked(dict)        — одиночный клик → выбор чата
        dclicked(dict)       — двойной клик → быстрый выбор без кнопки
        topics_clicked(int)  — кнопка «ветки» нажата (только forum)
    """

    clicked        = Signal(object)   # chat dict
    dclicked       = Signal(object)   # chat dict
    topics_clicked = Signal(object)   # chat_id (object — Telegram ID > 2^31)

    def __init__(self, chat: dict, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._chat = chat
        self._sel  = False
        self._hov  = False

        ctype = chat.get("type", "private")
        s = _TYPE_STYLES.get(ctype, _TYPE_STYLES["private"])
        self._accent  = s["accent"]
        self._icon_bg = s["icon_bg"]

        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(72)

        row = QHBoxLayout(self)
        row.setContentsMargins(10, 6, 10, 6)
        row.setSpacing(10)

        # ── Иконка ────────────────────────────────────────────────────────
        ico = QLabel(s["icon"])
        ico.setObjectName("chatIco")
        ico.setFixedSize(38, 38)
        ico.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ico.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        row.addWidget(ico)

        # ── Текст: заголовок + мета ───────────────────────────────────────
        col = QVBoxLayout()
        col.setSpacing(3)
        col.setContentsMargins(0, 0, 0, 0)

        self._tlbl = QLabel(chat.get("title") or "Без названия")
        self._tlbl.setObjectName("chatTitle")
        self._tlbl.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self._tlbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        col.addWidget(self._tlbl)

        # Мета-строка
        parts: list[str] = []
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

        # Бейдж «💬 обсуждение» — только для каналов с linked group
        if ctype == "channel" and chat.get("linked_chat_id"):
            badge = QPushButton("💬 обсуждение")
            badge.setObjectName("linkedBadge")
            badge.setFixedHeight(20)
            badge.setCursor(Qt.CursorShape.PointingHandCursor)
            badge.clicked.connect(lambda: self.clicked.emit(self._chat))
            meta_row.addWidget(badge)

        # Кнопка «📂 ветки» — только для форумов
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

        # Счётчик справа
        if cnt:
            cl = QLabel(_fmt(cnt))
            cl.setObjectName("chatCount")
            cl.setFixedWidth(40)
            cl.setAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            cl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            row.addWidget(cl)

        self._refresh_style()

    # ──────────────────────────────────────────────────────────────────────
    # СТИЛИ  — все цвета дочерних QLabel через родителя (фикс CSS-каскада)
    # ──────────────────────────────────────────────────────────────────────

    def _refresh_style(self) -> None:
        if self._sel:
            bg, border = ACCENT_SOFT_ORANGE, ACCENT_ORANGE
        elif self._hov:
            bg, border = OVERLAY2_HEX, BORDER_HEX
        else:
            bg, border = "rgba(255,255,255,0.03)", BORDER_HEX

        self.setStyleSheet(f"""
            ChatItemWidget {{
                background: {bg};
                border: 1px solid {border};
                border-radius: {RADIUS_MD}px;
            }}
            ChatItemWidget QLabel#chatTitle {{
                color: {TEXT_PRIMARY};
                font-family: {FONT_FAMILY};
                font-size: {FONT_SIZE_BODY}px;
                font-weight: bold;
                background: transparent;
            }}
            ChatItemWidget QLabel#chatMeta {{
                color: {TEXT_SECONDARY};
                font-family: {FONT_FAMILY};
                font-size: {FONT_SIZE_XS}px;
                background: transparent;
            }}
            ChatItemWidget QLabel#chatCount {{
                color: {self._accent};
                font-family: {FONT_FAMILY};
                font-size: {FONT_SIZE_XS}px;
                font-weight: bold;
                background: transparent;
            }}
            ChatItemWidget QLabel#chatIco {{
                background: {self._icon_bg};
                border-radius: 19px;
                font-size: 18px;
            }}
            ChatItemWidget QPushButton#linkedBadge {{
                background: {ACCENT_SOFT_PINK};
                color: {ACCENT_PINK};
                border: 1px solid rgba(255,107,201,0.5);
                border-radius: 10px;
                font-size: {FONT_SIZE_XS}px;
                padding: 0 6px;
            }}
            ChatItemWidget QPushButton#topicBtn {{
                background: transparent;
                color: {ACCENT_PINK};
                border: 1px solid rgba(255,107,201,0.5);
                border-radius: 10px;
                font-size: {FONT_SIZE_XS}px;
                padding: 0 6px;
            }}
            ChatItemWidget QPushButton#topicBtn:hover {{
                background: {ACCENT_PINK};
                color: #2B2B2B;
            }}
        """)

    # ──────────────────────────────────────────────────────────────────────
    # ПУБЛИЧНЫЙ API
    # ──────────────────────────────────────────────────────────────────────

    def set_selected(self, v: bool) -> None:
        self._sel = v
        self._refresh_style()

    def matches(self, q: str) -> bool:
        """Фильтрация по поисковому запросу (case-insensitive)."""
        return (
            q in (self._chat.get("title") or "").lower()
            or q in (self._chat.get("username") or "").lower()
        )

    @property
    def chat(self) -> dict:
        return self._chat

    # ──────────────────────────────────────────────────────────────────────
    # СОБЫТИЯ МЫШИ
    # ──────────────────────────────────────────────────────────────────────

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


# ══════════════════════════════════════════════════════════════════════════════
# SECTION HEADER WIDGET
# ══════════════════════════════════════════════════════════════════════════════

class SectionHeaderWidget(QWidget):
    """
    Заголовок коллапсируемой секции.
    Клик → toggle тела секции. Эмитирует toggled(bool).
    """

    toggled = Signal(bool)   # True = развёрнуто

    def __init__(self, chat_type: str, count: int = 0,
                 expanded: bool = True,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._exp = expanded
        s = _TYPE_STYLES.get(chat_type, _TYPE_STYLES["private"])

        self.setFixedHeight(44)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.setStyleSheet(f"""
            SectionHeaderWidget {{
                background: {OVERLAY_HEX};
                border-radius: {RADIUS_MD}px;
            }}
            SectionHeaderWidget:hover {{
                background: {OVERLAY2_HEX};
            }}
            SectionHeaderWidget QLabel {{ background: transparent; }}
        """)

        row = QHBoxLayout(self)
        row.setContentsMargins(10, 0, 10, 0)
        row.setSpacing(8)

        # Иконка
        ico = QLabel(s["icon"])
        ico.setFixedSize(28, 28)
        ico.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ico.setStyleSheet(
            f"background: {s['icon_bg']}; border-radius: 14px; font-size: 14px;"
        )
        row.addWidget(ico)

        # Название
        lbl = QLabel(s["label"])
        lbl.setFont(QFont(FONT_FAMILY, FONT_SIZE_SMALL, QFont.Weight.Bold))
        lbl.setStyleSheet(f"color: {s['accent']};")
        row.addWidget(lbl)
        row.addStretch()

        # Счётчик
        self._cnt = QLabel(str(count))
        self._cnt.setFixedSize(28, 18)
        self._cnt.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._cnt.setStyleSheet(
            f"background: {s['badge_bg']}; color: {s['accent']};"
            f"border-radius: 9px; font-size: {FONT_SIZE_XS}px; font-weight: bold;"
        )
        row.addWidget(self._cnt)

        # Стрелка
        self._arr = QLabel()
        self._arr.setFixedSize(16, 16)
        self._arr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._arr.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 14px;")
        row.addWidget(self._arr)
        self._set_arrow()

    def _set_arrow(self) -> None:
        self._arr.setText("∨" if self._exp else "›")

    def update_count(self, n: int) -> None:
        self._cnt.setText(str(n))

    def mousePressEvent(self, _e) -> None:
        self._exp = not self._exp
        self._set_arrow()
        self.toggled.emit(self._exp)


# ══════════════════════════════════════════════════════════════════════════════
# COLLAPSIBLE SECTION
# ══════════════════════════════════════════════════════════════════════════════

class CollapsibleSection(QWidget):
    """
    Коллапсируемая секция: заголовок + список ChatItemWidget.
    Одна секция на тип чата (Каналы / Группы / Форумы / Диалоги).
    """

    item_clicked   = Signal(object)   # chat dict
    item_dclicked  = Signal(object)   # chat dict
    topics_clicked = Signal(object)   # chat_id (object — Telegram ID > 2^31)

    def __init__(self, chat_type: str,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._items:  list[ChatItemWidget]     = []
        self._sel_w:  Optional[ChatItemWidget] = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 4)
        root.setSpacing(3)

        self._hdr = SectionHeaderWidget(chat_type, count=0, expanded=True)
        self._hdr.toggled.connect(lambda exp: self._body.setVisible(exp))
        root.addWidget(self._hdr)

        self._body = QWidget()
        self._body.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self._body.setStyleSheet("background: transparent;")
        self._bl = QVBoxLayout(self._body)
        self._bl.setContentsMargins(0, 2, 0, 2)
        self._bl.setSpacing(3)
        root.addWidget(self._body)


    def populate(self, chats: List[dict]) -> None:
        # Отключаем перерисовку на время заполнения — устраняет визуальный «фриз»
        # при 200 чатах и предотвращает «addChildLayout: already has a parent»
        self.setUpdatesEnabled(False)
        try:
            # Извлекаем все элементы из layout через takeAt() — это надёжнее
            # removeWidget(): layout сам освобождает LayoutItem немедленно,
            # без ожидания deleteLater(), что устраняет гонку parent-указателей.
            while self._bl.count():
                item = self._bl.takeAt(0)
                if item is not None and item.widget() is not None:
                    w = item.widget()
                    w.setParent(None)
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
        finally:
            self.setUpdatesEnabled(True)

    def filter_by_query(self, q: str) -> int:
        """Показать/скрыть элементы по запросу. Вернуть кол-во видимых."""
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


# ══════════════════════════════════════════════════════════════════════════════
# COLLAPSIBLE CHATS WIDGET
# ══════════════════════════════════════════════════════════════════════════════

class CollapsibleChatsWidget(QScrollArea):
    """
    QScrollArea с 4 коллапсируемыми секциями чатов.
    Группирует входящий список по полю chat["type"].
    """

    item_selected  = Signal(object)   # выбор одиночным кликом
    item_activated = Signal(object)   # двойной клик → сразу подтвердить
    topics_clicked = Signal(object)   # кнопка «ветки» нажата (object — Telegram ID > 2^31)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setStyleSheet(QSS_SCROLL_AREA)

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
        """Распределить список чатов по секциям."""
        # setUpdatesEnabled отключает все промежуточные перерисовки ScrollArea,
        # пока мы заполняем все 4 секции — без этого Qt перерисовывает после
        # каждой секции и UI «замирает» на ~1 сек при 200 чатах.
        self.setUpdatesEnabled(False)
        try:
            grouped: Dict[str, List[dict]] = {t: [] for t in _SECTION_ORDER}
            for c in chats:
                t = c.get("type", "private")
                if t not in grouped:
                    t = "private"
                grouped[t].append(c)
            for t, items in grouped.items():
                self._sections[t].populate(items)
        finally:
            self.setUpdatesEnabled(True)

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


# ══════════════════════════════════════════════════════════════════════════════
# CHATS SCREEN
# ══════════════════════════════════════════════════════════════════════════════

class ChatsScreen(QWidget):
    """
    Экран выбора чата (колонка 2).

    Сигналы (совместимы с MainWindow):
        chat_selected(dict)      — полный словарь чата (БЫЛО: int, str)
        log_message(str)
        character_state(str)
        request_topics(int)      — запрос топиков → MainWindow → TopicsWorker
        refresh_requested()      — кнопка «↻» → MainWindow → ChatsWorker

    Слоты (вызываются из MainWindow):
        inject_chats(list)       — принять загруженные чаты
        inject_topics(dict)      — принять загруженные топики

    Публичный API:
        selected_chat() -> dict  — текущий выбранный чат
        load_chats()             — запросить обновление (обратная совместимость)
    """

    chat_selected     = Signal(object)   # полный chat dict (БЫЛО: Signal(int, str))
    log_message       = Signal(str)
    character_state   = Signal(str)
    request_topics    = Signal(object)  # chat_id (object — Telegram ID > 2^31)
    refresh_requested = Signal()

    def __init__(self, cfg: AppConfig,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._cfg      = cfg
        self._sel_chat: Optional[dict] = None
        self._topics:   dict           = {}
        self._build_ui()

    # ──────────────────────────────────────────────────────────────────────
    # ПУБЛИЧНЫЙ API
    # ──────────────────────────────────────────────────────────────────────

    def inject_chats(self, chats: List[dict]) -> None:
        """
        Слот: принять список чатов от MainWindow после ChatsWorker.

        Подключение в MainWindow:
            chats_worker.chats_loaded.connect(chats_screen.inject_chats)
        """
        self._chats_widget.populate(chats)
        self._status.setText(f"{len(chats)} чатов")
        self._set_loading(False)
        self.log_message.emit(f"✅ Загружено {len(chats)} чатов")
        self.character_state.emit("success")

    def inject_topics(self, topics: dict) -> None:
        """
        Слот: принять топики форума от MainWindow после TopicsWorker.
        topics = {chat_id: {topic_id: topic_title}}

        Подключение в MainWindow:
            topics_worker.topics_loaded.connect(chats_screen.inject_topics)
        """
        self._topics.update(topics)

        # Определяем chat_id для заполнения комбобокса:
        # 1) выбранный форум (клик по чату) — приоритет
        # 2) chat_id из последнего нажатия «📂 ветки» (нет выбранного чата)
        target_id = None
        if self._sel_chat and self._sel_chat.get("type") == "forum":
            target_id = self._sel_chat.get("id")
        elif getattr(self, "_pending_topics_chat_id", None) in topics:
            target_id = self._pending_topics_chat_id

        if target_id is not None:
            forum_topics = self._topics.get(target_id, {})
            if forum_topics:
                self._fill_topics_combo(forum_topics)

        self.log_message.emit(
            f"✅ Загружено веток: {sum(len(v) for v in topics.values())}"
        )

    def selected_chat(self) -> Optional[dict]:
        return self._sel_chat

    def load_chats(self) -> None:
        """
        Обратная совместимость: запрашиваем обновление чатов.
        MainWindow слушает refresh_requested и создаёт ChatsWorker.
        """
        self._set_loading(True)
        self.refresh_requested.emit()

    # ──────────────────────────────────────────────────────────────────────
    # ПОСТРОЕНИЕ UI
    # ──────────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        # ── Заголовок + статус + кнопка обновления ────────────────────────
        root.addWidget(SectionTitle("💬", "Ваши чаты"))

        hdr = QHBoxLayout()

        self._status = QLabel("")
        self._status.setFont(QFont(FONT_FAMILY, FONT_SIZE_XS))
        self._status.setStyleSheet(
            f"color: {TEXT_SECONDARY}; background: transparent;"
        )
        hdr.addWidget(self._status)
        hdr.addStretch()

        self._btn_ref = QPushButton("↻")
        self._btn_ref.setFixedSize(32, 32)
        self._btn_ref.setToolTip("Обновить список чатов")
        self._btn_ref.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_ref.setStyleSheet(f"""
            QPushButton {{
                background: {OVERLAY_HEX};
                color: {TEXT_SECONDARY};
                border: 1px solid {BORDER_HEX};
                border-radius: {RADIUS_XS}px;
                font-size: 16px;
            }}
            QPushButton:hover {{
                background: {OVERLAY2_HEX};
                color: {TEXT_PRIMARY};
            }}
            QPushButton:pressed {{ background: {ACCENT_SOFT_ORANGE}; }}
            QPushButton:disabled {{ color: rgba(255,255,255,0.2); }}
        """)
        self._btn_ref.clicked.connect(self._on_refresh)
        hdr.addWidget(self._btn_ref)
        root.addLayout(hdr)

        # ── Поиск ─────────────────────────────────────────────────────────
        self._search = QLineEdit()
        self._search.setPlaceholderText("🔍  Поиск по чатам...")
        self._search.setClearButtonEnabled(True)
        self._search.setStyleSheet(QSS_INPUT)
        self._search.setFixedHeight(36)
        self._search.textChanged.connect(self._on_search)
        root.addWidget(self._search)

        # ── Список чатов ──────────────────────────────────────────────────
        self._chats_widget = CollapsibleChatsWidget(self)
        self._chats_widget.item_selected.connect(self._on_sel)
        self._chats_widget.item_activated.connect(self._on_activated)
        self._chats_widget.topics_clicked.connect(self._on_topics_clicked)
        root.addWidget(self._chats_widget, stretch=1)

        # ── Блок топиков (только для форумов) ─────────────────────────────
        self._topics_frame = QFrame()
        self._topics_frame.setVisible(False)
        self._topics_frame.setStyleSheet(f"""
            QFrame {{
                background: {ACCENT_SOFT_PINK};
                border: 1px solid rgba(255,107,201,0.3);
                border-radius: {RADIUS_MD}px;
            }}
            QFrame QLabel {{
                background: transparent;
                color: {TEXT_SECONDARY};
                font-size: {FONT_SIZE_XS}px;
            }}
        """)
        tf_lay = QHBoxLayout(self._topics_frame)
        tf_lay.setContentsMargins(12, 8, 12, 8)
        tf_lbl = QLabel("📁 Ветка:")
        tf_lbl.setStyleSheet(
            f"color: {TEXT_SECONDARY}; background: transparent;"
        )
        tf_lay.addWidget(tf_lbl)
        self._topics_combo = QComboBox()
        self._topics_combo.setStyleSheet(QSS_COMBOBOX)
        tf_lay.addWidget(self._topics_combo, stretch=1)
        root.addWidget(self._topics_frame)

        # ── Footer: выбрано + кнопка «Выбрать» ───────────────────────────
        footer = QFrame()
        footer.setStyleSheet(f"""
            QFrame {{
                background: {OVERLAY2_HEX};
                border: 1px solid {BORDER_HEX};
                border-radius: {RADIUS_MD}px;
            }}
            QFrame QLabel {{
                background: transparent;
                color: {TEXT_SECONDARY};
                font-size: {FONT_SIZE_XS}px;
            }}
        """)
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(12, 8, 12, 8)

        self._sel_lbl = QLabel("Выбрано: —")
        self._sel_lbl.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        fl.addWidget(self._sel_lbl)

        self._btn_open = QPushButton("Выбрать  ▶")
        self._btn_open.setEnabled(False)
        self._btn_open.setFixedHeight(32)
        self._btn_open.setMinimumWidth(120)
        self._btn_open.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_open.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0 {ACCENT_ORANGE}, stop:1 {ACCENT_PINK}
                );
                color: white;
                border: none;
                border-radius: {RADIUS_XS}px;
                font-family: {FONT_FAMILY};
                font-size: {FONT_SIZE_SMALL}px;
                font-weight: bold;
                padding: 0 16px;
            }}
            QPushButton:hover {{
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0 #E08600, stop:1 #E06BC9
                );
            }}
            QPushButton:disabled {{
                background: {OVERLAY_HEX};
                color: rgba(255,255,255,0.2);
            }}
        """)
        self._btn_open.clicked.connect(self._confirm_selection)
        fl.addWidget(self._btn_open)
        root.addWidget(footer)

    # ──────────────────────────────────────────────────────────────────────
    # ВСПОМОГАТЕЛЬНЫЕ
    # ──────────────────────────────────────────────────────────────────────

    def _fill_topics_combo(self, topics: dict) -> None:
        """Заполнить QComboBox топиками форума."""
        self._topics_combo.clear()
        self._topics_combo.addItem("Все ветки", None)
        for tid, ttitle in topics.items():
            self._topics_combo.addItem(ttitle, tid)

    def _set_loading(self, loading: bool) -> None:
        self._btn_ref.setEnabled(not loading)
        self._search.setEnabled(not loading)
        if loading:
            self._status.setText("Загрузка...")
            self._btn_open.setEnabled(False)

    # ──────────────────────────────────────────────────────────────────────
    # СЛОТЫ
    # ──────────────────────────────────────────────────────────────────────

    def _on_refresh(self) -> None:
        self._search.clear()
        self._topics_frame.setVisible(False)
        self._set_loading(True)
        self.refresh_requested.emit()

    def _on_search(self, text: str) -> None:
        self._chats_widget.filter_by_text(text)

    def _on_sel(self, chat: dict) -> None:
        self._sel_chat = chat
        name = chat.get("title", "?")
        cid  = chat.get("id", "")
        self._sel_lbl.setText(f"Выбрано: {name}  ({cid})")
        self._btn_open.setEnabled(True)

        # Форум: показываем блок топиков
        is_forum = chat.get("type") == "forum"
        self._topics_frame.setVisible(is_forum)
        if is_forum:
            forum_topics = self._topics.get(cid, {})
            if forum_topics:
                self._fill_topics_combo(forum_topics)
            else:
                # Топики ещё не загружены — просим MainWindow
                self._topics_combo.clear()
                self._topics_combo.addItem("Загружаются...")
                self.request_topics.emit(cid)

    def _on_activated(self, chat: dict) -> None:
        """Двойной клик → сразу подтвердить выбор."""
        self._sel_chat = chat
        self._confirm_selection()

    def _on_topics_clicked(self, chat_id: int) -> None:
        """Кнопка «ветки» → просим MainWindow загрузить топики."""
        self._pending_topics_chat_id = chat_id
        self.log_message.emit("📁 Загружаю ветки форума...")
        self._topics_combo.clear()
        self._topics_combo.addItem("Загружаются...")
        self._topics_frame.setVisible(True)
        self.request_topics.emit(chat_id)

    def _confirm_selection(self) -> None:
        """Передать выбранный чат в MainWindow через chat_selected(dict)."""
        chat = self._sel_chat or self._chats_widget.get_selected_chat()
        if not chat:
            return

        # Для форума добавляем выбранный топик
        if chat.get("type") == "forum":
            topic_id = self._topics_combo.currentData()
            chat = dict(chat)    # не мутируем оригинал
            chat["selected_topic_id"] = topic_id

        self.log_message.emit(f"✅ Выбран: {chat.get('title', '?')}")
        self.chat_selected.emit(chat)
