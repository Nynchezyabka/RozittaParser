"""
tests/conftest.py — Общие фикстуры для всех тестов Rozitta Parser.
"""
import pytest
from core.database import DBManager


@pytest.fixture
def db(tmp_path):
    """БД на файловой системе (для тестов транзакций и WAL)."""
    path = str(tmp_path / "test.db")
    with DBManager(path) as _db:
        yield _db


@pytest.fixture
def db_mem():
    """БД в памяти (для быстрых модульных тестов)."""
    return DBManager(":memory:")


def make_msg(id_, user_id=1, date="2025-06-01T12:00:00", text="hello",
             media_path=None, file_type=None, topic_id=None,
             post_id=None, is_comment=0, merge_group_id=None, merge_part_index=None):
    """Фабрика сообщений для вставки в БД."""
    return {
        "chat_id": -100123,
        "message_id": id_,
        "topic_id": topic_id,
        "user_id": user_id,
        "username": f"user_{user_id}",
        "date": date,
        "text": text,
        "media_path": media_path,
        "file_type": file_type,
        "post_id": post_id,
        "is_comment": is_comment,
        "merge_group_id": merge_group_id,
        "merge_part_index": merge_part_index,
    }


def insert_sample_messages(db, count=10, chat_id=-100123, user_id=1):
    """Быстрая вставка N тестовых сообщений."""
    msgs = []
    for i in range(1, count + 1):
        msgs.append({
            "chat_id": chat_id,
            "message_id": i,
            "user_id": user_id,
            "username": "test_user",
            "date": f"2025-06-{1 + i // 24:02d}T{i % 24:02d}:00:00",
            "text": f"Message {i}",
        })
    db.insert_messages_batch(msgs)
    return msgs


# =============================================================================
# Telegram API Mock fixtures
# =============================================================================

@pytest.fixture
def telegram_mock():
    """Готовые JSON-ответы от Telegram API."""
    from tests.fixtures.loader import TelegramApiMock
    return TelegramApiMock()


@pytest.fixture
def telegram_mock_empty_dialogs():
    """Мок с пустым списком диалогов."""
    from tests.fixtures.loader import TelegramApiMock

    # Создаём мок с пустым списком
    mock = TelegramApiMock()

    # Переопределяем get_dialogs
    async def empty_dialogs(limit=100):
        return []

    mock._client.get_dialogs = AsyncMock(side_effect=empty_dialogs)
    return mock


@pytest.fixture
def telegram_mock_with_channels_only():
    """Мок с только каналами."""
    from tests.fixtures.loader import TelegramApiMock

    mock = TelegramApiMock()

    # Загружаем только каналы
    data = mock._load_json("dialogs/channels_only.json")
    async def channels_only_dialogs(limit=100):
        return mock._dict_to_dialogs(data, limit)

    mock._client.get_dialogs = AsyncMock(side_effect=channels_only_dialogs)
    return mock