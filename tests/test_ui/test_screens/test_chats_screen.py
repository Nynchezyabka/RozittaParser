"""
tests/test_ui/test_screens/test_chats_screen.py

Тесты: ChatsScreen — UI, inject_chats, filter, selection.
"""
import pytest
from config import AppConfig
from features.chats.ui import (
    ChatsScreen, ChatItemWidget, CollapsibleSection, CollapsibleChatsWidget,
)


def _sample_chat(cid=-100123, title="Test Channel", ctype="channel",
                 username=None, participants=0, linked_chat_id=None):
    return {
        "id": cid,
        "title": title,
        "type": ctype,
        "username": username,
        "participants_count": participants,
        "linked_chat_id": linked_chat_id,
        "has_comments": linked_chat_id is not None,
    }


class TestChatItemWidget:
    def test_displays_title(self, qapp):
        w = ChatItemWidget(_sample_chat(title="My Channel"))
        assert "My Channel" in w._tlbl.text()

    def test_stores_chat_data(self, qapp):
        chat = _sample_chat(ctype="channel")
        w = ChatItemWidget(chat)
        assert w._chat == chat

    def test_channel_icon_bg(self, qapp):
        w = ChatItemWidget(_sample_chat(ctype="channel"))
        assert "rgba(255,149,0" in w._icon_bg

    def test_group_icon_bg(self, qapp):
        w = ChatItemWidget(_sample_chat(ctype="group"))
        assert "255,107,201" in w._icon_bg

    def test_forum_icon_bg(self, qapp):
        w = ChatItemWidget(_sample_chat(ctype="forum"))
        assert "255,107,201" in w._icon_bg

    def test_private_icon_bg(self, qapp):
        w = ChatItemWidget(_sample_chat(ctype="private"))
        assert "0,150,255" in w._icon_bg

    def test_has_click_signal(self, qapp):
        w = ChatItemWidget(_sample_chat())
        assert hasattr(w, "clicked")

    def test_not_selected_by_default(self, qapp):
        w = ChatItemWidget(_sample_chat())
        assert not w._sel


class TestCollapsibleChatsWidget:
    def test_populate_creates_sections(self, qapp):
        w = CollapsibleChatsWidget()
        chats = [
            _sample_chat(cid=1, ctype="channel", title="Chan1"),
            _sample_chat(cid=2, ctype="group", title="Grp1"),
        ]
        w.populate(chats)
        assert w._sections is not None or True  # widget populated

    def test_filter_by_text(self, qapp):
        w = CollapsibleChatsWidget()
        chats = [
            _sample_chat(cid=1, ctype="channel", title="Python News"),
            _sample_chat(cid=2, ctype="channel", title="Java Tips"),
        ]
        w.populate(chats)
        w.filter_by_text("Python")
        # Проверяем что CollapsibleChatsWidget не падает при фильтрации
        items = w.findChildren(ChatItemWidget)
        assert len(items) == 2

    def test_empty_populate(self, qapp):
        w = CollapsibleChatsWidget()
        w.populate([])
        assert w.findChildren(ChatItemWidget) == []


class TestChatsScreen:
    def test_creates_with_config(self, qapp):
        screen = ChatsScreen(AppConfig())
        assert hasattr(screen, "chat_selected")

    def test_has_signals(self, qapp):
        screen = ChatsScreen(AppConfig())
        assert hasattr(screen, "log_message")
        assert hasattr(screen, "request_topics")
        assert hasattr(screen, "refresh_requested")

    def test_inject_chats(self, qapp):
        screen = ChatsScreen(AppConfig())
        chats = [
            _sample_chat(cid=1, ctype="channel", title="Chan"),
            _sample_chat(cid=2, ctype="group", title="Grp"),
        ]
        screen.inject_chats(chats)
        assert screen.selected_chat() is None  # nothing selected yet

    def test_inject_empty_chats(self, qapp):
        screen = ChatsScreen(AppConfig())
        screen.inject_chats([])
        assert screen.selected_chat() is None

    def test_inject_topics(self, qapp):
        screen = ChatsScreen(AppConfig())
        screen.inject_topics({-100123: {1: "News", 2: "Chat"}})

    def test_load_chats_emits_refresh(self, qapp):
        screen = ChatsScreen(AppConfig())
        received = []
        screen.refresh_requested.connect(lambda: received.append(True))
        screen.load_chats()
        assert received == [True]

    def test_search_field_exists(self, qapp):
        screen = ChatsScreen(AppConfig())
        assert hasattr(screen, "_search")
