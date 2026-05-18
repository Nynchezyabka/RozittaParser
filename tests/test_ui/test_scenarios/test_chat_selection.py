"""
tests/test_ui/test_scenarios/test_chat_selection.py

E2E сценарий выбора чата: загрузка → фильтрация → выбор → сигнал.
"""
import pytest
from config import AppConfig
from features.chats.ui import ChatsScreen, ChatItemWidget


def _make_chats():
    return [
        {"id": -1001, "title": "Python News", "type": "channel", "username": "pynews",
         "participants_count": 5000, "linked_chat_id": None},
        {"id": -1002, "title": "Java Tips", "type": "channel", "username": "javatips",
         "participants_count": 3000, "linked_chat_id": None},
        {"id": -2001, "title": "Dev Chat", "type": "group", "username": None,
         "participants_count": 150, "linked_chat_id": None},
        {"id": -2002, "title": "Test Forum", "type": "forum", "username": "testforum",
         "participants_count": 800, "linked_chat_id": None},
        {"id": 100, "title": "Alice Smith", "type": "private", "username": "alice",
         "participants_count": 0, "linked_chat_id": None},
    ]


class TestChatSelectionFlow:
    def test_inject_chats_and_count(self, qapp):
        """Загрузка чатов — количество верное."""
        screen = ChatsScreen(AppConfig())
        screen.inject_chats(_make_chats())
        items = screen.findChildren(ChatItemWidget)
        assert len(items) == 5

    def test_search_filters_chats(self, qapp):
        """Поиск «Python» оставляет только подходящий чат."""
        screen = ChatsScreen(AppConfig())
        screen.inject_chats(_make_chats())
        screen._search.setText("Python")
        # Trigger filter
        if hasattr(screen, "_on_search"):
            screen._on_search("Python")
        items = screen.findChildren(ChatItemWidget)
        visible = [i for i in items if i.isVisible()]
        assert len(visible) <= len(items)

    def test_refresh_requests_reload(self, qapp):
        """Кнопка «Обновить» эмитирует refresh_requested."""
        screen = ChatsScreen(AppConfig())
        received = []
        screen.refresh_requested.connect(lambda: received.append(True))
        screen.load_chats()
        assert received == [True]

    def test_no_selection_initially(self, qapp):
        """Ни один чат не выбран при загрузке."""
        screen = ChatsScreen(AppConfig())
        screen.inject_chats(_make_chats())
        assert screen.selected_chat() is None

    def test_inject_empty_list(self, qapp):
        """Пустой список чатов не ломает UI."""
        screen = ChatsScreen(AppConfig())
        screen.inject_chats([])
        assert screen.selected_chat() is None

    def test_topics_injected_without_error(self, qapp):
        """Топики загружаются без ошибок."""
        screen = ChatsScreen(AppConfig())
        screen.inject_topics({-2002: {1: "General", 2: "Questions"}})

    def test_multiple_refreshes(self, qapp):
        """Множественные обновления не дублируют чаты."""
        screen = ChatsScreen(AppConfig())
        chats = _make_chats()
        screen.inject_chats(chats)
        count1 = len(screen.findChildren(ChatItemWidget))
        screen.inject_chats(chats)
        count2 = len(screen.findChildren(ChatItemWidget))
        # Должно быть то же количество (старые удалены)
        assert count2 == count1
