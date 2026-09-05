"""
tests/test_features/test_export_md.py

Тесты: MarkdownGenerator — генерация Markdown-архива.
"""
import os
import pytest
from core.database import DBManager
from core.exceptions import EmptyDataError
from features.export.generator import MarkdownGenerator


def _msg(chat_id=-100, msg_id=1, user_id=1, username="user1",
         date="2025-01-01T10:00:00", text="hello", **kw):
    """Фабрика сообщения со всеми обязательными полями."""
    return {
        "chat_id": chat_id, "message_id": msg_id, "user_id": user_id,
        "username": username, "date": date, "text": text,
        "topic_id": None, "media_path": None, "file_type": None,
        "file_size": None, "reply_to_msg_id": None, "post_id": None,
        "is_comment": 0, "from_linked_group": 0,
        **kw,
    }


def _db_with_msgs(tmp_path, msgs):
    db = DBManager(str(tmp_path / "test.db"))
    db.insert_messages_batch(msgs)
    return db


class TestMarkdownBasic:
    def test_generates_md_file(self, tmp_path):
        db = _db_with_msgs(tmp_path, [_msg()])
        gen = MarkdownGenerator(db=db, output_dir=str(tmp_path))
        files = gen.generate(chat_id=-100, chat_title="Test", period_label="full")
        assert len(files) == 1
        assert files[0].endswith(".md")

    def test_header_present(self, tmp_path):
        db = _db_with_msgs(tmp_path, [_msg()])
        gen = MarkdownGenerator(db=db, output_dir=str(tmp_path))
        files = gen.generate(chat_id=-100, chat_title="MyChat", period_label="full")
        content = open(files[0], encoding="utf-8").read()
        assert "# MyChat" in content

    def test_message_format(self, tmp_path):
        db = _db_with_msgs(tmp_path, [_msg(
            msg_id=1, username="Alice", date="2025-01-15T14:30:00", text="Hello world",
        )])
        gen = MarkdownGenerator(db=db, output_dir=str(tmp_path))
        files = gen.generate(chat_id=-100, chat_title="Test", period_label="full")
        content = open(files[0], encoding="utf-8").read()
        assert "**[2025-01-15 14:30] Alice:**" in content
        assert "Hello world" in content

    def test_separator_between_messages(self, tmp_path):
        db = _db_with_msgs(tmp_path, [_msg(msg_id=1), _msg(msg_id=2)])
        gen = MarkdownGenerator(db=db, output_dir=str(tmp_path))
        files = gen.generate(chat_id=-100, chat_title="T", period_label="full")
        content = open(files[0], encoding="utf-8").read()
        assert "---" in content

    def test_empty_db_raises(self, tmp_path):
        db = DBManager(str(tmp_path / "empty.db"))
        gen = MarkdownGenerator(db=db, output_dir=str(tmp_path))
        with pytest.raises(EmptyDataError):
            gen.generate(chat_id=-100, chat_title="T", period_label="full")

    def test_multiple_messages(self, tmp_path):
        db = _db_with_msgs(tmp_path, [_msg(msg_id=i, text=f"msg{i}") for i in range(1, 6)])
        gen = MarkdownGenerator(db=db, output_dir=str(tmp_path))
        files = gen.generate(chat_id=-100, chat_title="T", period_label="full")
        content = open(files[0], encoding="utf-8").read()
        for i in range(1, 6):
            assert f"msg{i}" in content


class TestMarkdownStt:
    def test_stt_block_present(self, tmp_path):
        db = DBManager(str(tmp_path / "test.db"))
        db.insert_messages_batch([_msg(text="", file_type="voice")])
        db.insert_transcription(1, -100, "Голосовой текст", "base")
        gen = MarkdownGenerator(db=db, output_dir=str(tmp_path))
        files = gen.generate(chat_id=-100, chat_title="T", period_label="full")
        content = open(files[0], encoding="utf-8").read()
        assert "*(STT: Голосовой текст)*" in content

    def test_no_stt_no_block(self, tmp_path):
        db = _db_with_msgs(tmp_path, [_msg(text="just text")])
        gen = MarkdownGenerator(db=db, output_dir=str(tmp_path))
        files = gen.generate(chat_id=-100, chat_title="T", period_label="full")
        content = open(files[0], encoding="utf-8").read()
        assert "STT:" not in content


class TestMarkdownAiSplit:
    def test_ai_split_creates_multiple_files(self, tmp_path):
        msgs = [_msg(msg_id=i, text=f"{'word ' * 20}", date=f"2025-01-01T10:{i:02d}:00")
                for i in range(50)]
        db = _db_with_msgs(tmp_path, msgs)
        gen = MarkdownGenerator(db=db, output_dir=str(tmp_path))
        files = gen.generate(
            chat_id=-100, chat_title="T", period_label="full",
            ai_split=True, ai_split_chunk_words=30,
        )
        assert len(files) >= 2

    def test_ai_split_each_file_has_header(self, tmp_path):
        msgs = [_msg(msg_id=i, text=f"{'word ' * 20}", date=f"2025-01-01T10:{i:02d}:00")
                for i in range(50)]
        db = _db_with_msgs(tmp_path, msgs)
        gen = MarkdownGenerator(db=db, output_dir=str(tmp_path))
        files = gen.generate(
            chat_id=-100, chat_title="MyChat", period_label="full",
            ai_split=True, ai_split_chunk_words=30,
        )
        for f in files:
            content = open(f, encoding="utf-8").read()
            assert "# MyChat" in content

    def test_no_ai_split_single_file(self, tmp_path):
        db = _db_with_msgs(tmp_path, [_msg(msg_id=i) for i in range(1, 10)])
        gen = MarkdownGenerator(db=db, output_dir=str(tmp_path))
        files = gen.generate(
            chat_id=-100, chat_title="T", period_label="full",
            ai_split=False,
        )
        assert len(files) == 1


class TestMarkdownTopicSuffix:
    def test_filename_with_topic(self, tmp_path):
        db = DBManager(str(tmp_path / "test.db"))
        db.insert_messages_batch([_msg(text="hi", topic_id=3)])
        gen = MarkdownGenerator(db=db, output_dir=str(tmp_path))
        files = gen.generate(chat_id=-100, chat_title="T", period_label="full", topic_id=3)
        assert "_topic3" in files[0]

    def test_filename_without_topic(self, tmp_path):
        db = _db_with_msgs(tmp_path, [_msg()])
        gen = MarkdownGenerator(db=db, output_dir=str(tmp_path))
        files = gen.generate(chat_id=-100, chat_title="T", period_label="full")
        assert "_topic" not in os.path.basename(files[0])


class TestFormatMessageStatic:
    """
    Вызовы через экземпляр, а не через класс.

    `_format_message` перестал быть @staticmethod: он берёт описание
    картинки через self._db. Название класса оставлено прежним, чтобы не
    рвать историю — но «Static» здесь теперь только память о прошлом.
    """

    @pytest.fixture
    def gen(self, tmp_path):
        with DBManager(":memory:") as db:
            yield MarkdownGenerator(db=db, output_dir=str(tmp_path))

    def test_format_message_basic(self, gen):
        row = (
            0, -100, 1, None, 1, "Bob",
            "2025-06-15T09:30:00", "Hello!", None, None, None,
            None, None, 0, None, None, None,
        )
        result = gen._format_message(row, None)
        assert "**[2025-06-15 09:30] Bob:**" in result
        assert "Hello!" in result
        assert "---" in result

    def test_format_message_with_stt(self, gen):
        row = (
            0, -100, 1, None, 1, "Alice",
            "2025-06-15T09:30:00", "", None, None, None,
            None, None, 0, None, None, None,
        )
        result = gen._format_message(row, "voice text here")
        assert "*(STT: voice text here)*" in result

    def test_format_message_no_username_uses_id(self, gen):
        row = (
            0, -100, 1, None, 42, None,
            "2025-06-15T09:30:00", "text", None, None, None,
            None, None, 0, None, None, None,
        )
        result = gen._format_message(row, None)
        assert "id:42" in result

    def test_format_message_empty_date(self, gen):
        row = (
            0, -100, 1, None, 1, "A",
            None, "text", None, None, None,
            None, None, 0, None, None, None,
        )
        result = gen._format_message(row, None)
        assert "—" in result
