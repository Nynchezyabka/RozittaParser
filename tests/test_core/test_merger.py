"""
tests/test_core/test_merger.py

Тесты: MergerService — группировка, временное окно, смена автора, edge cases.
"""
import pytest
from core.database import DBManager
from core.merger import MergerService, DEFAULT_MERGE_TIME_DELTA


@pytest.fixture
def db():
    with DBManager(":memory:") as manager:
        yield manager


def _insert(db, msgs):
    """Вспомогательная вставка: список (message_id, user_id, date_str)."""
    rows = [
        {
            "chat_id": -1001, "message_id": mid,
            "date": date, "topic_id": None,
            "user_id": uid, "username": None, "text": None,
            "media_path": None, "file_type": None, "file_size": None,
            "reply_to_msg_id": None, "post_id": None,
            "is_comment": 0, "from_linked_group": 0,
        }
        for mid, uid, date in msgs
    ]
    db.insert_messages_batch(rows)


# ──────────────────────────────────────────────────────────────────────────────
# Основная логика
# ──────────────────────────────────────────────────────────────────────────────

class TestMergerBasic:
    def test_empty_chat_returns_zeros(self, db):
        svc = MergerService()
        stats = svc.run_merge(db, chat_id=-1001)
        assert stats.total_msgs    == 0
        assert stats.groups_count  == 0
        assert stats.singles_count == 0

    def test_single_message(self, db):
        _insert(db, [(1, 111, "2024-01-01 10:00:00")])
        svc = MergerService()
        stats = svc.run_merge(db, chat_id=-1001)
        assert stats.total_msgs    == 1
        assert stats.singles_count == 1
        assert stats.groups_count  == 0

    def test_two_messages_same_author_within_window(self, db):
        """Два сообщения одного автора в пределах 60 сек → 1 группа."""
        _insert(db, [
            (1, 111, "2024-01-01 10:00:00"),
            (2, 111, "2024-01-01 10:00:30"),   # Δt = 30s
        ])
        svc = MergerService(time_delta=60)
        stats = svc.run_merge(db, chat_id=-1001)
        assert stats.groups_count == 1
        assert stats.merged_msgs  == 2
        assert stats.singles_count == 0

    def test_two_messages_same_author_outside_window(self, db):
        """Δt > time_delta → разные группы (оба одиночных)."""
        _insert(db, [
            (1, 111, "2024-01-01 10:00:00"),
            (2, 111, "2024-01-01 10:02:00"),   # Δt = 120s > 60
        ])
        svc = MergerService(time_delta=60)
        stats = svc.run_merge(db, chat_id=-1001)
        assert stats.groups_count  == 0
        assert stats.singles_count == 2

    def test_different_authors_not_merged(self, db):
        """Разные авторы → не склеиваются, даже при малом Δt."""
        _insert(db, [
            (1, 111, "2024-01-01 10:00:00"),
            (2, 222, "2024-01-01 10:00:05"),   # другой автор
        ])
        svc = MergerService(time_delta=60)
        stats = svc.run_merge(db, chat_id=-1001)
        assert stats.groups_count  == 0
        assert stats.singles_count == 2

    def test_interleaved_authors_breaks_group(self, db):
        """A-B-A: вмешательство B разрывает группу A."""
        _insert(db, [
            (1, 111, "2024-01-01 10:00:00"),
            (2, 222, "2024-01-01 10:00:10"),   # B вмешался
            (3, 111, "2024-01-01 10:00:20"),   # A снова, но группа уже сброшена
        ])
        svc = MergerService(time_delta=60)
        stats = svc.run_merge(db, chat_id=-1001)
        assert stats.groups_count  == 0
        assert stats.singles_count == 3

    def test_three_messages_same_author_one_group(self, db):
        _insert(db, [
            (1, 111, "2024-01-01 10:00:00"),
            (2, 111, "2024-01-01 10:00:20"),
            (3, 111, "2024-01-01 10:00:40"),
        ])
        svc = MergerService(time_delta=60)
        stats = svc.run_merge(db, chat_id=-1001)
        assert stats.groups_count == 1
        assert stats.merged_msgs  == 3

    def test_multiple_independent_groups(self, db):
        _insert(db, [
            (1, 111, "2024-01-01 10:00:00"),
            (2, 111, "2024-01-01 10:00:30"),   # группа A
            (3, 222, "2024-01-01 10:05:00"),
            (4, 222, "2024-01-01 10:05:20"),   # группа B
        ])
        svc = MergerService(time_delta=60)
        stats = svc.run_merge(db, chat_id=-1001)
        assert stats.groups_count == 2
        assert stats.merged_msgs  == 4

    def test_custom_time_delta(self, db):
        """Маленький time_delta = 5s → Δt=30s не склеивает."""
        _insert(db, [
            (1, 111, "2024-01-01 10:00:00"),
            (2, 111, "2024-01-01 10:00:30"),
        ])
        svc = MergerService(time_delta=5)
        stats = svc.run_merge(db, chat_id=-1001)
        assert stats.groups_count  == 0
        assert stats.singles_count == 2


# ──────────────────────────────────────────────────────────────────────────────
# Идемпотентность
# ──────────────────────────────────────────────────────────────────────────────

class TestMergerIdempotent:
    def test_double_run_same_result(self, db):
        _insert(db, [
            (1, 111, "2024-01-01 10:00:00"),
            (2, 111, "2024-01-01 10:00:10"),
        ])
        svc = MergerService()
        stats1 = svc.run_merge(db, chat_id=-1001)
        stats2 = svc.run_merge(db, chat_id=-1001)
        assert stats1.groups_count == stats2.groups_count
        assert stats1.merged_msgs  == stats2.merged_msgs


# ──────────────────────────────────────────────────────────────────────────────
# MergeStats поля
# ──────────────────────────────────────────────────────────────────────────────

class TestMergeStats:
    def test_total_msgs_correct(self, db):
        _insert(db, [
            (1, 111, "2024-01-01 10:00:00"),
            (2, 222, "2024-01-01 10:00:00"),
            (3, 333, "2024-01-01 10:00:00"),
        ])
        stats = MergerService().run_merge(db, chat_id=-1001)
        assert stats.total_msgs == 3

    def test_merged_plus_singles_equals_total(self, db):
        _insert(db, [
            (1, 111, "2024-01-01 10:00:00"),
            (2, 111, "2024-01-01 10:00:10"),   # в группе
            (3, 222, "2024-01-01 10:05:00"),   # одиночка
        ])
        stats = MergerService().run_merge(db, chat_id=-1001)
        assert stats.merged_msgs + stats.singles_count == stats.total_msgs
