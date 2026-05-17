"""
Telegram API fixtures loader для UI тестов.

Telegram использует MTProto протокол, а не HTTP, поэтому классический WireMock
неприменим. Эта библиотека предоставляет альтернативу: предзагруженные JSON
ответы, которые конвертируются в Telethon объекты.

Пример использования:
    from tests.fixtures.loader import TelegramApiMock

    mock = TelegramApiMock()
    client = mock.client

    # get_dialogs вернёт данные из mixed.json
    dialogs = await client.get_dialogs(limit=10)
"""

import json
import os
from pathlib import Path
from typing import Any, Optional
from unittest.mock import AsyncMock

_FIXTURES_DIR = Path(__file__).parent / "telegram_api"


class TelegramApiMock:
    """
    Мок Telegram API с предзагруженными JSON ответами.

    Пример использования:
        mock = TelegramApiMock()
        client = mock.client

        # get_dialogs вернёт данные из mixed.json
        dialogs = await client.get_dialogs(limit=10)
    """

    def __init__(self, fixtures_dir: Optional[Path] = None):
        self._fixtures_dir = fixtures_dir or _FIXTURES_DIR
        self._cached: dict[str, Any] = {}

        # Создаём mock-клиент
        self._client = AsyncMock()
        self._setup_methods()

    def _load_json(self, path: str) -> Any:
        """Загружает JSON файл с кэшированием."""
        if path in self._cached:
            return self._cached[path]

        full_path = self._fixtures_dir / path
        if not full_path.exists():
            raise FileNotFoundError(f"Fixture not found: {full_path}")

        with open(full_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            self._cached[path] = data
            return data

    def _setup_methods(self):
        """Настраивает методы mock-клиента."""

        # === Auth ===
        self._client.connect = AsyncMock(return_value=None)
        self._client.disconnect = AsyncMock(return_value=None)
        self._client.is_user_authorized = AsyncMock(return_value=False)
        self._client.sign_in = AsyncMock()
        self._client.log_out = AsyncMock()

        # === get_me ===
        async def get_me():
            data = self._load_json("users/user_me.json")
            return self._dict_to_user(data)

        self._client.get_me = AsyncMock(side_effect=get_me)

        # === get_dialogs ===
        async def get_dialogs(limit=100):
            data = self._load_json("dialogs/mixed.json")
            return self._dict_to_dialogs(data, limit)

        self._client.get_dialogs = AsyncMock(side_effect=get_dialogs)

        # === get_entity ===
        self._client.get_entity = AsyncMock(side_effect=self._get_entity_mock)

        # === get_messages ===
        async def get_messages(entity, limit=100):
            data = self._load_json("messages/with_media.json")
            return self._dict_to_messages(data, limit)

        self._client.get_messages = AsyncMock(side_effect=get_messages)

        # === get_participants ===
        async def get_participants(entity, limit=100):
            data = self._load_json("users/participants_10.json")
            return self._dict_to_users(data, limit)

        self._client.get_participants = AsyncMock(side_effect=get_participants)

        # === get_forum_topics ===
        async def get_forum_topics(channel, limit=100):
            data = self._load_json("topics/multiple.json")
            return self._dict_to_topics(data)

        self._client.get_forum_topics = AsyncMock(side_effect=get_forum_topics)

    async def _get_entity_mock(self, entity):
        """Мок для get_entity — возвращает базовый объект."""
        # Упрощённая реализация для тестов
        if hasattr(entity, 'id'):
            if entity.id == -1001234567890:
                # Возвращаем mock объект канала
                from dataclasses import dataclass
                from telethon.tl import types

                @dataclass
                class MockChannel:
                    id: int
                    title: str
                    username: str

                return MockChannel(
                    id=-1001234567890,
                    title="Test Channel",
                    username="test_channel"
                )
        return entity

    @property
    def client(self) -> AsyncMock:
        """Возвращает mock-клиент Telethon."""
        return self._client

    def _dict_to_user(self, data: dict) -> Any:
        """Конвертирует dict в User (упрощённо для тестов)."""
        return data

    def _dict_to_dialogs(self, data: list, limit: int) -> list:
        """Конвертирует dict в список Dialog (упрощённо для тестов)."""
        return [self._dict_to_dialog(d) for d in data[:limit]]

    def _dict_to_dialog(self, data: dict) -> Any:
        """Конвертирует dict в Dialog (упрощённо для тестов)."""
        return data

    def _dict_to_messages(self, data: list, limit: int) -> list:
        """Конвертирует dict в список Message (упрощённо для тестов)."""
        return [self._dict_to_message(m) for m in data[:limit]]

    def _dict_to_message(self, data: dict) -> Any:
        """Конвертирует dict в Message (упрощённо для тестов)."""
        return data

    def _dict_to_users(self, data: list, limit: int) -> list:
        """Конвертирует dict в список User (упрощённо для тестов)."""
        return [self._dict_to_user(u) for u in data[:limit]]

    def _dict_to_topics(self, data: list) -> list:
        """Конвертирует dict в список ForumTopic (упрощённо для тестов)."""
        return [self._dict_to_topic(t) for t in data]

    def _dict_to_topic(self, data: dict) -> Any:
        """Конвертирует dict в ForumTopic (упрощённо для тестов)."""
        return data