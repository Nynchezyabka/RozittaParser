"""
tests/test_core/test_database.py

Тесты: DBManager — WAL, insert/batch, upsert, transcriptions, get_messages.
Используется in-memory БД для изоляции.
"""
import pytest
from core.database import DBManager


@pytest.fixture
def db():
    """In-memory DBManager. Автоматически закрывается после теста."""
    with DBManager(":memory:") as manager:
        yield manager


# ──────────────────────────────────────────────────────────────────────────────
# Вспомогательная фабрика строк
# ──────────────────────────────────────────────────────────────────────────────

def _msg(chat_id=-1001, message_id=1, date="2024-01-01 12:00:00", **kw):
    base = dict(
        chat_id=chat_id, message_id=message_id, date=date,
        topic_id=None, user_id=None, username=None, text=None,
        media_path=None, file_type=None, file_size=None,
        reply_to_msg_id=None, post_id=None, is_comment=0, from_linked_group=0,
    )
    base.update(kw)
    return base


# ──────────────────────────────────────────────────────────────────────────────
# Схема
# ──────────────────────────────────────────────────────────────────────────────

class TestSchema:
    def test_tables_created(self, db):
        """Все таблицы должны существовать после инициализации."""
        conn = db._get_connection()
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        tables = {row[0] for row in cur.fetchall()}
        assert "messages"       in tables
        assert "chats"          in tables
        assert "topics"         in tables
        assert "transcriptions" in tables


# ──────────────────────────────────────────────────────────────────────────────
# insert_message
# ──────────────────────────────────────────────────────────────────────────────

class TestInsertMessage:
    def test_basic_insert(self, db):
        result = db.insert_message(
            chat_id=100, message_id=1,
            date="2024-01-01 10:00:00", text="Привет"
        )
        assert result is True

    def test_upsert_replaces_on_conflict(self, db):
        """Повторная вставка с тем же (chat_id, message_id) обновляет текст."""
        db.insert_message(chat_id=100, message_id=1, date="2024-01-01 10:00:00", text="v1")
        db.insert_message(chat_id=100, message_id=1, date="2024-01-01 10:00:00", text="v2")
        rows = db.get_messages(100)
        assert len(rows) == 1
        assert rows[0]["text"] == "v2"

    def test_different_message_ids(self, db):
        db.insert_message(chat_id=100, message_id=1, date="2024-01-01 10:00:00")
        db.insert_message(chat_id=100, message_id=2, date="2024-01-01 11:00:00")
        assert len(db.get_messages(100)) == 2


# ──────────────────────────────────────────────────────────────────────────────
# insert_messages_batch
# ──────────────────────────────────────────────────────────────────────────────

class TestBatchInsert:
    def test_empty_batch_returns_zero(self, db):
        assert db.insert_messages_batch([]) == 0

    def test_batch_inserts_all(self, db):
        rows = [_msg(message_id=i) for i in range(1, 6)]
        n = db.insert_messages_batch(rows)
        assert n == 5
        assert len(db.get_messages(-1001)) == 5

    def test_batch_replace_on_conflict(self, db):
        """Batch INSERT OR REPLACE перезаписывает дубли."""
        db.insert_messages_batch([_msg(message_id=1, text="old")])
        db.insert_messages_batch([_msg(message_id=1, text="new")])
        rows = db.get_messages(-1001)
        assert len(rows) == 1
        assert rows[0]["text"] == "new"


# ──────────────────────────────────────────────────────────────────────────────
# upsert_messages_batch
# ──────────────────────────────────────────────────────────────────────────────

class TestUpsertBatch:
    def test_upsert_skips_duplicates(self, db):
        """INSERT OR IGNORE не перезаписывает существующие строки."""
        db.insert_messages_batch([_msg(message_id=1, text="original")])
        db.upsert_messages_batch([_msg(message_id=1, text="ignored")])
        rows = db.get_messages(-1001)
        assert len(rows) == 1
        assert rows[0]["text"] == "original"

    def test_upsert_inserts_new(self, db):
        db.upsert_messages_batch([_msg(message_id=1), _msg(message_id=2)])
        assert len(db.get_messages(-1001)) == 2


# ──────────────────────────────────────────────────────────────────────────────
# get_messages — фильтрация
# ──────────────────────────────────────────────────────────────────────────────

class TestGetMessages:
    def test_include_comments_false(self, db):
        """is_comment=1 исключаются по умолчанию."""
        db.insert_messages_batch([
            _msg(message_id=1, is_comment=0),
            _msg(message_id=2, is_comment=1),
        ])
        rows = db.get_messages(-1001, include_comments=False)
        assert len(rows) == 1
        assert rows[0]["message_id"] == 1

    def test_include_comments_true(self, db):
        db.insert_messages_batch([
            _msg(message_id=1, is_comment=0),
            _msg(message_id=2, is_comment=1),
        ])
        rows = db.get_messages(-1001, include_comments=True)
        assert len(rows) == 2

    def test_topic_filter(self, db):
        db.insert_messages_batch([
            _msg(message_id=1, topic_id=10),
            _msg(message_id=2, topic_id=20),
        ])
        rows = db.get_messages(-1001, topic_id=10)
        assert len(rows) == 1
        assert rows[0]["topic_id"] == 10

    def test_sorted_by_date_asc(self, db):
        db.insert_messages_batch([
            _msg(message_id=2, date="2024-01-01 12:00:00"),
            _msg(message_id=1, date="2024-01-01 10:00:00"),
        ])
        rows = db.get_messages(-1001)
        assert rows[0]["message_id"] == 1
        assert rows[1]["message_id"] == 2


# ──────────────────────────────────────────────────────────────────────────────
# transcriptions
# ──────────────────────────────────────────────────────────────────────────────

class TestTranscriptions:
    def test_insert_and_get(self, db):
        db.insert_transcription(
            message_id=42, peer_id=-1001,
            text="Привет мир", model_type="base",
        )
        text = db.get_transcription(message_id=42, peer_id=-1001)
        assert text == "Привет мир"

    def test_get_missing_returns_none(self, db):
        assert db.get_transcription(9999, -1001) is None

    def test_replace_on_duplicate(self, db):
        """INSERT OR REPLACE обновляет существующую транскрипцию."""
        db.insert_transcription(42, -1001, "v1")
        db.insert_transcription(42, -1001, "v2")
        assert db.get_transcription(42, -1001) == "v2"

    def test_stt_candidates_excludes_transcribed(self, db):
        """get_stt_candidates не возвращает уже транскрибированные сообщения."""
        db.insert_messages_batch([
            _msg(message_id=1, file_type="voice", media_path="/a.ogg"),
            _msg(message_id=2, file_type="voice", media_path="/b.ogg"),
        ])
        db.insert_transcription(1, -1001, "уже распознано")
        candidates = db.get_stt_candidates(-1001, file_types=["voice"])
        msg_ids = [r["message_id"] for r in candidates]
        assert 1 not in msg_ids
        assert 2 in msg_ids


# ──────────────────────────────────────────────────────────────────────────────
# get_post_with_comments
# ──────────────────────────────────────────────────────────────────────────────

class TestGetPostWithComments:
    def test_returns_post_and_comments(self, db):
        db.insert_messages_batch([
            _msg(message_id=10, post_id=None,  is_comment=0),     # пост
            _msg(message_id=11, post_id=10,    is_comment=1),     # комментарий
            _msg(message_id=12, post_id=10,    is_comment=1),     # комментарий
            _msg(message_id=20, post_id=None,  is_comment=0),     # другой пост
        ])
        rows = db.get_post_with_comments(-1001, post_id=10)
        msg_ids = {r["message_id"] for r in rows}
        assert 10 in msg_ids
        assert 11 in msg_ids
        assert 12 in msg_ids
        assert 20 not in msg_ids
