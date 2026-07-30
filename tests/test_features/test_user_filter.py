"""
tests/test_features/test_user_filter.py

FEAT-6 — обратная фильтрация участников.
Нет Qt: UserFilter и DBManager — чистый Python.
"""

import pytest

from core.database import DBManager, telegram_user_id_variants
from features.export.filters import (
    MODE_EXCLUDE,
    MODE_INCLUDE,
    MODE_NONE,
    NO_FILTER,
    UserFilter,
)

# ID канала-отправителя в двух формах записи (B1/B3)
CHANNEL_BARE   = 3783247484
CHANNEL_MARKED = -1003783247484


# ──────────────────────────────────────────────────────────────────────────────
# Варианты ID
# ──────────────────────────────────────────────────────────────────────────────

class TestIdVariants:
    def test_bare_expands_to_marked(self):
        assert set(telegram_user_id_variants(CHANNEL_BARE)) == {
            CHANNEL_BARE, CHANNEL_MARKED,
        }

    def test_marked_expands_to_bare(self):
        assert set(telegram_user_id_variants(CHANNEL_MARKED)) == {
            CHANNEL_BARE, CHANNEL_MARKED,
        }

    def test_roundtrip_is_symmetric(self):
        assert set(telegram_user_id_variants(CHANNEL_BARE)) == set(
            telegram_user_id_variants(CHANNEL_MARKED)
        )


# ──────────────────────────────────────────────────────────────────────────────
# UserFilter — контракт
# ──────────────────────────────────────────────────────────────────────────────

class TestUserFilterContract:
    def test_default_is_inactive(self):
        assert NO_FILTER.is_active is False
        assert NO_FILTER.mode == MODE_NONE

    def test_empty_ids_collapse_to_no_filter(self):
        assert UserFilter.make(MODE_EXCLUDE, []) is NO_FILTER
        assert UserFilter.make(MODE_INCLUDE, None) is NO_FILTER

    def test_unknown_mode_raises(self):
        with pytest.raises(ValueError):
            UserFilter(mode="bogus", ids=frozenset({1}))

    def test_is_frozen(self):
        uf = UserFilter.make(MODE_EXCLUDE, [111])
        with pytest.raises(Exception):
            uf.mode = MODE_INCLUDE


class TestUserFilterExclude:
    def test_hides_selected_user(self):
        uf = UserFilter.make(MODE_EXCLUDE, [111])
        assert uf.is_hidden(111) is True

    def test_keeps_other_users(self):
        uf = UserFilter.make(MODE_EXCLUDE, [111])
        assert uf.is_hidden(222) is False

    def test_never_hides_service_messages(self):
        """user_id IS NULL — служебные сообщения, они не скрываются."""
        uf = UserFilter.make(MODE_EXCLUDE, [111])
        assert uf.is_hidden(None) is False

    def test_channel_hidden_in_both_id_forms(self):
        """B1/B3: выбран bare ID — скрывается и marked-строка."""
        uf = UserFilter.make(MODE_EXCLUDE, [CHANNEL_BARE])
        assert uf.is_hidden(CHANNEL_BARE) is True
        assert uf.is_hidden(CHANNEL_MARKED) is True

    def test_channel_hidden_when_selected_as_marked(self):
        uf = UserFilter.make(MODE_EXCLUDE, [CHANNEL_MARKED])
        assert uf.is_hidden(CHANNEL_BARE) is True
        assert uf.is_hidden(CHANNEL_MARKED) is True

    def test_exclude_does_not_filter_sql(self):
        """Асимметрия: в exclude строки обязаны дойти до рендера."""
        uf = UserFilter.make(MODE_EXCLUDE, [111])
        assert uf.sql_ids() is None


class TestUserFilterInclude:
    def test_sql_ids_returns_selected(self):
        uf = UserFilter.make(MODE_INCLUDE, [222, 111])
        assert uf.sql_ids() == [111, 222]

    def test_include_never_hides(self):
        """Асимметрия: в include заглушек нет вообще."""
        uf = UserFilter.make(MODE_INCLUDE, [111])
        assert uf.is_hidden(111) is False
        assert uf.is_hidden(999) is False


# ──────────────────────────────────────────────────────────────────────────────
# DBManager.get_messages — мультивыбор
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def db_multi_sender():
    """In-memory БД: Alice, Bob, Carol и канал (marked ID)."""
    with DBManager(":memory:") as db:
        rows = [
            {
                "chat_id": -1001, "message_id": 1,
                "date": "2024-01-15 10:00:00",
                "topic_id": None, "user_id": 111, "username": "Alice",
                "text": "от Алисы",
                "media_path": None, "file_type": None, "file_size": None,
                "reply_to_msg_id": None, "post_id": None,
                "is_comment": 0, "from_linked_group": 0,
            },
            {
                "chat_id": -1001, "message_id": 2,
                "date": "2024-01-15 10:05:00",
                "topic_id": None, "user_id": 222, "username": "Bob",
                "text": "от Боба",
                "media_path": None, "file_type": None, "file_size": None,
                "reply_to_msg_id": None, "post_id": None,
                "is_comment": 0, "from_linked_group": 0,
            },
            {
                "chat_id": -1001, "message_id": 3,
                "date": "2024-01-15 10:10:00",
                "topic_id": None, "user_id": 333, "username": "Carol",
                "text": "от Кэрол",
                "media_path": None, "file_type": None, "file_size": None,
                "reply_to_msg_id": None, "post_id": None,
                "is_comment": 0, "from_linked_group": 0,
            },
            {
                # Канал-отправитель: в БД лежит в marked-форме
                "chat_id": -1001, "message_id": 4,
                "date": "2024-01-15 10:15:00",
                "topic_id": None, "user_id": CHANNEL_MARKED, "username": "Канал",
                "text": "от канала",
                "media_path": None, "file_type": None, "file_size": None,
                "reply_to_msg_id": None, "post_id": None,
                "is_comment": 0, "from_linked_group": 0,
            },
        ]
        db.insert_messages_batch(rows)
        yield db


class TestGetMessagesMultiUser:
    def test_no_filter_returns_all(self, db_multi_sender):
        rows = db_multi_sender.get_messages(-1001)
        assert len(rows) == 4

    def test_single_user_id_still_works(self, db_multi_sender):
        """Обратная совместимость: старый параметр не сломан."""
        rows = db_multi_sender.get_messages(-1001, user_id=111)
        assert [r["message_id"] for r in rows] == [1]

    def test_user_ids_multi_select(self, db_multi_sender):
        rows = db_multi_sender.get_messages(-1001, user_ids=[111, 333])
        assert [r["message_id"] for r in rows] == [1, 3]

    def test_user_ids_preserves_date_order(self, db_multi_sender):
        rows = db_multi_sender.get_messages(-1001, user_ids=[333, 111])
        assert [r["message_id"] for r in rows] == [1, 3]

    def test_channel_found_by_bare_id(self, db_multi_sender):
        """B1/B3: в БД marked, спрашиваем bare — строка находится."""
        rows = db_multi_sender.get_messages(-1001, user_ids=[CHANNEL_BARE])
        assert [r["message_id"] for r in rows] == [4]

    def test_channel_found_by_marked_id(self, db_multi_sender):
        rows = db_multi_sender.get_messages(-1001, user_ids=[CHANNEL_MARKED])
        assert [r["message_id"] for r in rows] == [4]

    def test_user_id_and_user_ids_combine(self, db_multi_sender):
        rows = db_multi_sender.get_messages(-1001, user_id=111, user_ids=[222])
        assert [r["message_id"] for r in rows] == [1, 2]

    def test_empty_user_ids_is_no_filter(self, db_multi_sender):
        rows = db_multi_sender.get_messages(-1001, user_ids=[])
        assert len(rows) == 4

    def test_unknown_user_returns_nothing(self, db_multi_sender):
        rows = db_multi_sender.get_messages(-1001, user_ids=[999999])
        assert rows == []


class TestFilterToDbIntegration:
    def test_include_filter_feeds_get_messages(self, db_multi_sender):
        uf = UserFilter.make(MODE_INCLUDE, [111, 222])
        rows = db_multi_sender.get_messages(-1001, user_ids=uf.sql_ids())
        assert [r["message_id"] for r in rows] == [1, 2]

    def test_exclude_filter_reads_everything(self, db_multi_sender):
        """В exclude SQL не режет: все 4 строки доходят до рендера."""
        uf = UserFilter.make(MODE_EXCLUDE, [111])
        rows = db_multi_sender.get_messages(-1001, user_ids=uf.sql_ids())
        assert len(rows) == 4
        hidden = [r["message_id"] for r in rows if uf.is_hidden(r["user_id"])]
        assert hidden == [1]
