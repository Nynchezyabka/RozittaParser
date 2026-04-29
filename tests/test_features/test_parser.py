"""
tests/test_features/test_parser.py

Тесты: CollectParams (BUG-4 user_ids), фильтрация sender_id.
Не использует реальный Telegram — только датаклассы и логику.
"""
import pytest
from features.parser.api import CollectParams


# ──────────────────────────────────────────────────────────────────────────────
# CollectParams — контракт полей (BUG-4)
# ──────────────────────────────────────────────────────────────────────────────

class TestCollectParamsUserIds:
    def test_user_ids_default_none(self):
        """По умолчанию user_ids=None — все пользователи."""
        p = CollectParams(chat_id=-1001)
        assert p.user_ids is None

    def test_user_ids_single(self):
        p = CollectParams(chat_id=-1001, user_ids=[111])
        assert p.user_ids == [111]

    def test_user_ids_multiple(self):
        p = CollectParams(chat_id=-1001, user_ids=[111, 222, 333])
        assert p.user_ids == [111, 222, 333]

    def test_no_user_id_field(self):
        """Старое поле user_id (int) не должно существовать."""
        p = CollectParams(chat_id=-1001)
        assert not hasattr(p, "user_id"), (
            "Поле user_id: int больше не должно существовать в CollectParams. "
            "Используй user_ids: List[int]."
        )

    def test_user_ids_is_list_type(self):
        p = CollectParams(chat_id=-1001, user_ids=[42])
        assert isinstance(p.user_ids, list)


# ──────────────────────────────────────────────────────────────────────────────
# Логика фильтрации — проверяем через симуляцию условия
# ──────────────────────────────────────────────────────────────────────────────

class TestUserIdFilterLogic:
    """
    Проверяет логику «sender_id not in params.user_ids».
    Имитирует условие из parser/api.py без реального Telegram.
    """

    @staticmethod
    def _should_skip(sender_id, user_ids):
        """Копия условия фильтра из collect_data()."""
        return bool(user_ids and sender_id not in user_ids)

    def test_no_filter_keeps_all(self):
        for uid in [111, 222, 333]:
            assert self._should_skip(uid, None) is False

    def test_filter_keeps_listed_users(self):
        user_ids = [111, 333]
        assert self._should_skip(111, user_ids) is False
        assert self._should_skip(333, user_ids) is False

    def test_filter_skips_unlisted_users(self):
        user_ids = [111]
        assert self._should_skip(222, user_ids) is True
        assert self._should_skip(999, user_ids) is True

    def test_empty_list_skips_nobody(self):
        """Пустой список user_ids = фильтр выключен (falsy)."""
        assert self._should_skip(111, []) is False

    def test_filter_multiple_users(self):
        user_ids = [10, 20, 30]
        assert self._should_skip(10, user_ids) is False
        assert self._should_skip(20, user_ids) is False
        assert self._should_skip(99, user_ids) is True


# ──────────────────────────────────────────────────────────────────────────────
# CollectParams — другие поля
# ──────────────────────────────────────────────────────────────────────────────

class TestCollectParamsDefaults:
    def test_required_field_chat_id(self):
        p = CollectParams(chat_id=-1001234567890)
        assert p.chat_id == -1001234567890

    def test_download_comments_default_false(self):
        p = CollectParams(chat_id=-1001)
        assert p.download_comments is False

    def test_re_download_default_false(self):
        p = CollectParams(chat_id=-1001)
        assert p.re_download is False

    def test_output_dir_default(self):
        p = CollectParams(chat_id=-1001)
        assert p.output_dir == "output"

    def test_all_fields_settable(self):
        from datetime import datetime, timezone
        p = CollectParams(
            chat_id          = -1001,
            topic_id         = 42,
            days_limit       = 7,
            date_from        = datetime(2024, 1, 1, tzinfo=timezone.utc),
            date_to          = datetime(2024, 1, 31, tzinfo=timezone.utc),
            media_filter     = ["photo", "video"],
            download_comments= True,
            user_ids         = [111, 222],
            output_dir       = "/tmp/output",
            re_download      = True,
            filter_expression= "has_media",
        )
        assert p.topic_id          == 42
        assert p.days_limit        == 7
        assert p.media_filter      == ["photo", "video"]
        assert p.download_comments is True
        assert p.user_ids          == [111, 222]
        assert p.re_download       is True
        assert p.filter_expression == "has_media"

# =============================================================================
# Тесты фильтрации по датам (date_from / date_to)
# =============================================================================

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock
from features.parser.api import ParserService, CollectParams
from core.database import DBManager


@pytest.fixture
def mock_client_with_dates():
    """Мок TelegramClient, возвращающий сообщения с разными датами и корректную сущность."""
    client = AsyncMock()
    
    # 1. Настраиваем get_entity, чтобы возвращал сущность с title
    fake_entity = MagicMock()
    fake_entity.id = 123
    fake_entity.title = "Test Chat"
    fake_entity.megagroup = False
    fake_entity.broadcast = False
    fake_entity.forum = False
    client.get_entity = AsyncMock(return_value=fake_entity)
    
    # 2. Создаём сообщения
    base = datetime(2025, 1, 1, tzinfo=timezone.utc)
    messages = []
    for i in range(20):
        msg = MagicMock()
        msg.id = i + 1
        msg.date = base + timedelta(days=i)
        msg.sender_id = 123
        msg.text = f"Message {i+1}"
        msg.replies = None
        msg.media = None
        messages.append(msg)

    async def iter_messages(*args, **kwargs):
        # Возвращаем от новых к старым
        for msg in sorted(messages, key=lambda m: m.date, reverse=True):
            yield msg

    client.iter_messages = iter_messages
    return client


@pytest.mark.asyncio
async def test_date_filter_both_dates(mock_client_with_dates, tmp_path):
    """Фильтрация: date_from = 2025-01-05, date_to = 2025-01-10"""
    db_path = tmp_path / "test.db"
    db = DBManager(str(db_path))

    params = CollectParams(
        chat_id=123,
        date_from=datetime(2025, 1, 5, tzinfo=timezone.utc),
        date_to=datetime(2025, 1, 10, tzinfo=timezone.utc),
        media_filter=None,
        user_ids=None,
        filter_expression=None,
        download_comments=False,
        re_download=False,
        output_dir=str(tmp_path),
    )

    service = ParserService(mock_client_with_dates, db, progress=lambda x: None)
    await service.collect_data(params)

    conn = db._get_connection()
    cur = conn.cursor()
    cur.execute("SELECT date FROM messages WHERE chat_id = ?", (123,))
    rows = cur.fetchall()
    dates = [datetime.fromisoformat(row[0]) for row in rows]

    for d in dates:
        assert params.date_from <= d <= params.date_to
    assert len(dates) == 6


@pytest.mark.asyncio
async def test_date_filter_only_from(mock_client_with_dates, tmp_path):
    """Только date_from, date_to = None"""
    db_path = tmp_path / "test.db"
    db = DBManager(str(db_path))

    params = CollectParams(
        chat_id=123,
        date_from=datetime(2025, 1, 15, tzinfo=timezone.utc),
        date_to=None,
        media_filter=None,
        user_ids=None,
        filter_expression=None,
        download_comments=False,
        re_download=False,
        output_dir=str(tmp_path),
    )

    service = ParserService(mock_client_with_dates, db, progress=lambda x: None)
    await service.collect_data(params)

    conn = db._get_connection()
    cur = conn.cursor()
    cur.execute("SELECT date FROM messages WHERE chat_id = ?", (123,))
    rows = cur.fetchall()
    dates = [datetime.fromisoformat(row[0]) for row in rows]

    for d in dates:
        assert d >= params.date_from
    assert len(dates) == 6


@pytest.mark.asyncio
async def test_date_filter_only_to(mock_client_with_dates, tmp_path):
    """Только date_to, date_from = None"""
    db_path = tmp_path / "test.db"
    db = DBManager(str(db_path))

    params = CollectParams(
        chat_id=123,
        date_from=None,
        date_to=datetime(2025, 1, 5, tzinfo=timezone.utc),
        media_filter=None,
        user_ids=None,
        filter_expression=None,
        download_comments=False,
        re_download=False,
        output_dir=str(tmp_path),
    )

    service = ParserService(mock_client_with_dates, db, progress=lambda x: None)
    await service.collect_data(params)

    conn = db._get_connection()
    cur = conn.cursor()
    cur.execute("SELECT date FROM messages WHERE chat_id = ?", (123,))
    rows = cur.fetchall()
    dates = [datetime.fromisoformat(row[0]) for row in rows]

    for d in dates:
        assert d <= params.date_to
    assert len(dates) == 5


@pytest.mark.asyncio
async def test_date_filter_no_dates(mock_client_with_dates, tmp_path):
    """Без date_from и date_to — все сообщения"""
    db_path = tmp_path / "test.db"
    db = DBManager(str(db_path))

    params = CollectParams(
        chat_id=123,
        date_from=None,
        date_to=None,
        media_filter=None,
        user_ids=None,
        filter_expression=None,
        download_comments=False,
        re_download=False,
        output_dir=str(tmp_path),
    )

    service = ParserService(mock_client_with_dates, db, progress=lambda x: None)
    await service.collect_data(params)

    conn = db._get_connection()
    cur = conn.cursor()
    cur.execute("SELECT date FROM messages WHERE chat_id = ?", (123,))
    rows = cur.fetchall()
    dates = [datetime.fromisoformat(row[0]) for row in rows]

    assert len(dates) == 20