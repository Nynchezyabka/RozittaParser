"""
tests/test_features/test_export_json.py

Тесты: JsonGenerator — генерация JSON-архива.
"""
import json
import os
import pytest
from core.database import DBManager
from core.exceptions import EmptyDataError
from features.export.generator import JsonGenerator


def _msg(chat_id=-100, msg_id=1, user_id=1, username="user1",
         date="2025-01-01T10:00:00", text="hello", **kw):
    """Фабрика сообщения со всеми обязательными полями для insert_messages_batch."""
    return {
        "chat_id": chat_id, "message_id": msg_id, "user_id": user_id,
        "username": username, "date": date, "text": text,
        "topic_id": None, "media_path": None, "file_type": None,
        "file_size": None, "reply_to_msg_id": None, "post_id": None,
        "is_comment": 0, "from_linked_group": 0,
        **kw,
    }


def _db_with_msgs(tmp_path, count=5, chat_id=-100):
    path = str(tmp_path / "test.db")
    db = DBManager(path)
    msgs = [_msg(chat_id=chat_id, msg_id=i, user_id=i % 3,
                 username=f"user_{i % 3}", date=f"2025-01-{i + 1:02d}T10:00:00",
                 text=f"Message {i}")
            for i in range(1, count + 1)]
    db.insert_messages_batch(msgs)
    return db


class TestJsonBasic:
    def test_generates_json_file(self, tmp_path):
        db = _db_with_msgs(tmp_path)
        gen = JsonGenerator(db=db, output_dir=str(tmp_path))
        files = gen.generate(chat_id=-100, chat_title="TestChat", period_label="full")
        assert len(files) == 1
        assert files[0].endswith(".json")

    def test_correct_record_count(self, tmp_path):
        db = _db_with_msgs(tmp_path, count=5)
        gen = JsonGenerator(db=db, output_dir=str(tmp_path))
        files = gen.generate(chat_id=-100, chat_title="T", period_label="full")
        with open(files[0], encoding="utf-8") as f:
            data = json.load(f)
        assert len(data) == 5

    def test_first_record_has_correct_id(self, tmp_path):
        db = _db_with_msgs(tmp_path, count=3)
        gen = JsonGenerator(db=db, output_dir=str(tmp_path))
        files = gen.generate(chat_id=-100, chat_title="T", period_label="full")
        with open(files[0], encoding="utf-8") as f:
            data = json.load(f)
        assert data[0]["message_id"] == 1

    def test_empty_db_raises(self, tmp_path):
        db = DBManager(str(tmp_path / "empty.db"))
        gen = JsonGenerator(db=db, output_dir=str(tmp_path))
        with pytest.raises(EmptyDataError):
            gen.generate(chat_id=-100, chat_title="T", period_label="full")


class TestJsonRecordStructure:
    def test_record_has_all_fields(self, tmp_path):
        db = _db_with_msgs(tmp_path, count=1)
        gen = JsonGenerator(db=db, output_dir=str(tmp_path))
        files = gen.generate(chat_id=-100, chat_title="T", period_label="full")
        with open(files[0], encoding="utf-8") as f:
            data = json.load(f)
        rec = data[0]
        for key in ("message_id", "date", "sender_id", "username", "text", "media_path", "stt_text"):
            assert key in rec

    def test_stt_text_included(self, tmp_path):
        db = DBManager(str(tmp_path / "test.db"))
        db.insert_messages_batch([_msg(text="", file_type="voice")])
        db.insert_transcription(1, -100, "Распознанный текст", "base")
        gen = JsonGenerator(db=db, output_dir=str(tmp_path))
        files = gen.generate(chat_id=-100, chat_title="T", period_label="full")
        with open(files[0], encoding="utf-8") as f:
            data = json.load(f)
        assert data[0]["stt_text"] == "Распознанный текст"

    def test_no_stt_gives_none(self, tmp_path):
        db = _db_with_msgs(tmp_path, count=1)
        gen = JsonGenerator(db=db, output_dir=str(tmp_path))
        files = gen.generate(chat_id=-100, chat_title="T", period_label="full")
        with open(files[0], encoding="utf-8") as f:
            data = json.load(f)
        assert data[0]["stt_text"] is None

    def test_null_fields_preserved(self, tmp_path):
        db = DBManager(str(tmp_path / "test.db"))
        db.insert_messages_batch([_msg(text=None, media_path=None, username=None)])
        gen = JsonGenerator(db=db, output_dir=str(tmp_path))
        files = gen.generate(chat_id=-100, chat_title="T", period_label="full")
        with open(files[0], encoding="utf-8") as f:
            data = json.load(f)
        assert data[0]["text"] is None
        assert data[0]["media_path"] is None


class TestJsonAiSplit:
    def test_ai_split_creates_multiple_files(self, tmp_path):
        db = _db_with_msgs(tmp_path, count=100)
        gen = JsonGenerator(db=db, output_dir=str(tmp_path))
        files = gen.generate(
            chat_id=-100, chat_title="T", period_label="full",
            ai_split=True, ai_split_chunk_words=30,
        )
        assert len(files) >= 2

    def test_ai_split_all_files_are_json(self, tmp_path):
        db = _db_with_msgs(tmp_path, count=50)
        gen = JsonGenerator(db=db, output_dir=str(tmp_path))
        files = gen.generate(
            chat_id=-100, chat_title="T", period_label="full",
            ai_split=True, ai_split_chunk_words=20,
        )
        for f in files:
            assert f.endswith(".json")

    def test_ai_split_each_file_valid_json(self, tmp_path):
        db = _db_with_msgs(tmp_path, count=50)
        gen = JsonGenerator(db=db, output_dir=str(tmp_path))
        files = gen.generate(
            chat_id=-100, chat_title="T", period_label="full",
            ai_split=True, ai_split_chunk_words=20,
        )
        for f in files:
            with open(f, encoding="utf-8") as fh:
                data = json.load(fh)
            assert isinstance(data, list)
            assert len(data) > 0

    def test_ai_split_total_records_preserved(self, tmp_path):
        db = _db_with_msgs(tmp_path, count=20)
        gen = JsonGenerator(db=db, output_dir=str(tmp_path))
        files = gen.generate(
            chat_id=-100, chat_title="T", period_label="full",
            ai_split=True, ai_split_chunk_words=30,
        )
        total = 0
        for f in files:
            with open(f, encoding="utf-8") as fh:
                data = json.load(fh)
            total += len(data)
        assert total == 20

    def test_no_ai_split_single_file(self, tmp_path):
        db = _db_with_msgs(tmp_path, count=20)
        gen = JsonGenerator(db=db, output_dir=str(tmp_path))
        files = gen.generate(
            chat_id=-100, chat_title="T", period_label="full",
            ai_split=False,
        )
        assert len(files) == 1


class TestJsonUnicode:
    def test_unicode_content(self, tmp_path):
        db = DBManager(str(tmp_path / "test.db"))
        db.insert_messages_batch([_msg(text="Привет мир 𝕳𝖊𝖑𝖑𝖔", username="пользователь")])
        gen = JsonGenerator(db=db, output_dir=str(tmp_path))
        files = gen.generate(chat_id=-100, chat_title="Тест", period_label="full")
        with open(files[0], encoding="utf-8") as f:
            data = json.load(f)
        assert "𝕳𝖊𝖑𝖑𝖔" in data[0]["text"]

    def test_emoji_in_text(self, tmp_path):
        db = DBManager(str(tmp_path / "test.db"))
        db.insert_messages_batch([_msg(text="Hello World")])
        gen = JsonGenerator(db=db, output_dir=str(tmp_path))
        files = gen.generate(chat_id=-100, chat_title="Тест", period_label="full")
        with open(files[0], encoding="utf-8") as f:
            data = json.load(f)
        assert "World" in data[0]["text"]


class TestJsonTopicSuffix:
    def test_filename_without_topic(self, tmp_path):
        db = _db_with_msgs(tmp_path, count=1)
        gen = JsonGenerator(db=db, output_dir=str(tmp_path))
        files = gen.generate(chat_id=-100, chat_title="T", period_label="full")
        assert "_topic" not in os.path.basename(files[0])

    def test_filename_with_topic(self, tmp_path):
        db = DBManager(str(tmp_path / "test.db"))
        db.insert_messages_batch([_msg(text="hi", topic_id=7)])
        gen = JsonGenerator(db=db, output_dir=str(tmp_path))
        files = gen.generate(chat_id=-100, chat_title="T", period_label="full", topic_id=7)
        assert "_topic7" in files[0]


class TestMakeRecord:
    """
    Вызовы через экземпляр, а не через класс.

    `_make_record` перестал быть @staticmethod: теперь он берёт описание
    картинки через self._db. Места вызова в самом генераторе и так шли
    через self, поэтому менять пришлось только тесты — ровно та картина,
    что описана в BUG-20: приложение работает, падают тесты, зовущие
    через класс.
    """

    @pytest.fixture
    def gen(self, tmp_path):
        with DBManager(":memory:") as db:
            yield JsonGenerator(db=db, output_dir=str(tmp_path))

    def test_static_make_record(self, gen):
        row = (
            0, -100, 42, None, 1, "alice",
            "2025-01-01T10:00:00", "hello", None, None, None,
            None, None, 0, None, None, None,
        )
        rec = gen._make_record(row, None)
        assert rec["message_id"] == 42
        assert rec["username"] == "alice"
        assert rec["text"] == "hello"
        assert rec["stt_text"] is None

    def test_static_make_record_with_stt(self, gen):
        row = (
            0, -100, 42, None, 1, "alice",
            "2025-01-01T10:00:00", "hello", None, None, None,
            None, None, 0, None, None, None,
        )
        rec = gen._make_record(row, "transcribed text")
        assert rec["stt_text"] == "transcribed text"

    def test_static_make_record_none_fields(self, gen):
        row = (
            0, -100, 1, None, 1, None,
            None, None, None, None, None,
            None, None, 0, None, None, None,
        )
        rec = gen._make_record(row, None)
        assert rec["date"] is None
        assert rec["username"] is None
        assert rec["text"] is None
        assert rec["media_path"] is None
