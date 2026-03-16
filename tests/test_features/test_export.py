"""
tests/test_features/test_export.py

Тесты: ExportParams (BUG-2), DocxGenerator с реальной БД.
Нет Qt — ExportParams это обычный dataclass, DocxGenerator чистый Python.
"""
import os
import pytest
from core.database import DBManager
from features.export.ui import ExportParams
from features.export.generator import DocxGenerator


# ──────────────────────────────────────────────────────────────────────────────
# ExportParams — контракт (BUG-2)
# ──────────────────────────────────────────────────────────────────────────────

class TestExportParams:
    def test_include_comments_default_false(self):
        p = ExportParams(chat_id=-1001, chat_title="Test")
        assert p.include_comments is False

    def test_include_comments_true(self):
        p = ExportParams(chat_id=-1001, chat_title="Test", include_comments=True)
        assert p.include_comments is True

    def test_split_mode_default_none(self):
        p = ExportParams(chat_id=-1001, chat_title="Test")
        assert p.split_mode == "none"

    def test_required_fields(self):
        p = ExportParams(chat_id=-1001, chat_title="MyChan")
        assert p.chat_id    == -1001
        assert p.chat_title == "MyChan"

    def test_all_fields(self):
        p = ExportParams(
            chat_id          = -1001,
            chat_title       = "Chan",
            period_label     = "2024-01",
            split_mode       = "post",
            topic_id         = 10,
            user_id          = 42,
            include_comments = True,
            output_dir       = "/tmp",
            db_path          = "/tmp/db.sqlite",
        )
        assert p.split_mode       == "post"
        assert p.include_comments is True
        assert p.topic_id         == 10


# ──────────────────────────────────────────────────────────────────────────────
# DocxGenerator — интеграционные тесты (реальный DOCX)
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def db_with_messages(tmp_path):
    """In-memory БД с тестовыми сообщениями."""
    with DBManager(":memory:") as db:
        rows = [
            {
                "chat_id": -1001, "message_id": 1,
                "date": "2024-01-15 10:00:00",
                "topic_id": None, "user_id": 111, "username": "Alice",
                "text": "Первое сообщение",
                "media_path": None, "file_type": None, "file_size": None,
                "reply_to_msg_id": None, "post_id": None,
                "is_comment": 0, "from_linked_group": 0,
            },
            {
                "chat_id": -1001, "message_id": 2,
                "date": "2024-01-15 10:05:00",
                "topic_id": None, "user_id": 222, "username": "Bob",
                "text": "Второе сообщение",
                "media_path": None, "file_type": None, "file_size": None,
                "reply_to_msg_id": None, "post_id": None,
                "is_comment": 0, "from_linked_group": 0,
            },
        ]
        db.insert_messages_batch(rows)
        yield db, tmp_path


@pytest.fixture
def db_with_posts_and_comments(tmp_path):
    """БД с постами и комментариями для split_mode=post."""
    with DBManager(":memory:") as db:
        rows = [
            # Пост 1
            {
                "chat_id": -1001, "message_id": 10,
                "date": "2024-02-01 09:00:00",
                "topic_id": None, "user_id": 111, "username": "Author",
                "text": "Пост номер один",
                "media_path": None, "file_type": None, "file_size": None,
                "reply_to_msg_id": None, "post_id": None,
                "is_comment": 0, "from_linked_group": 0,
            },
            # Комментарий к посту 1
            {
                "chat_id": -1001, "message_id": 11,
                "date": "2024-02-01 09:10:00",
                "topic_id": None, "user_id": 222, "username": "Reader",
                "text": "Комментарий к посту",
                "media_path": None, "file_type": None, "file_size": None,
                "reply_to_msg_id": 10, "post_id": 10,
                "is_comment": 1, "from_linked_group": 0,
            },
            # Пост 2
            {
                "chat_id": -1001, "message_id": 20,
                "date": "2024-02-02 10:00:00",
                "topic_id": None, "user_id": 111, "username": "Author",
                "text": "Пост номер два",
                "media_path": None, "file_type": None, "file_size": None,
                "reply_to_msg_id": None, "post_id": None,
                "is_comment": 0, "from_linked_group": 0,
            },
        ]
        db.insert_messages_batch(rows)
        yield db, tmp_path


class TestDocxGeneratorNone:
    def test_generates_docx_file(self, db_with_messages):
        db, tmp_path = db_with_messages
        gen = DocxGenerator(db, output_dir=str(tmp_path))
        files = gen.generate(
            chat_id    = -1001,
            chat_title = "TestChat",
            split_mode = "none",
        )
        assert len(files) == 1
        assert files[0].endswith(".docx")
        assert os.path.exists(files[0])

    def test_empty_chat_raises_or_returns_empty(self, tmp_path):
        """Пустая БД → EmptyDataError или пустой список (не падает)."""
        from core.exceptions import EmptyDataError
        with DBManager(":memory:") as db:
            gen = DocxGenerator(db, output_dir=str(tmp_path))
            try:
                files = gen.generate(chat_id=-9999, chat_title="Empty", split_mode="none")
                assert files == []
            except EmptyDataError:
                pass  # тоже приемлемо


class TestDocxGeneratorDay:
    def test_split_by_day_one_file(self, db_with_messages):
        """Оба сообщения в один день → один файл."""
        db, tmp_path = db_with_messages
        gen = DocxGenerator(db, output_dir=str(tmp_path))
        files = gen.generate(
            chat_id    = -1001,
            chat_title = "TestChat",
            split_mode = "day",
        )
        assert len(files) == 1


class TestDocxGeneratorPost:
    def test_split_by_post_creates_file_per_post(self, db_with_posts_and_comments):
        """split_mode=post → по одному файлу на каждый пост."""
        db, tmp_path = db_with_posts_and_comments
        gen = DocxGenerator(db, output_dir=str(tmp_path))
        files = gen.generate(
            chat_id          = -1001,
            chat_title       = "TestChan",
            split_mode       = "post",
            include_comments = False,
        )
        assert len(files) == 2
        for f in files:
            assert os.path.exists(f)

    def test_include_comments_true_docx_bigger(self, db_with_posts_and_comments):
        """DOCX с комментариями должен быть не меньше DOCX без."""
        db, tmp_path = db_with_posts_and_comments

        gen_no = DocxGenerator(db, output_dir=str(tmp_path / "no"))
        files_no = gen_no.generate(
            chat_id=-1001, chat_title="Chan", split_mode="post",
            include_comments=False,
        )

        gen_yes = DocxGenerator(db, output_dir=str(tmp_path / "yes"))
        files_yes = gen_yes.generate(
            chat_id=-1001, chat_title="Chan", split_mode="post",
            include_comments=True,
        )

        # С комментариями — суммарный размер файлов не меньше
        size_no  = sum(os.path.getsize(f) for f in files_no)
        size_yes = sum(os.path.getsize(f) for f in files_yes)
        assert size_yes >= size_no


class TestDocxGeneratorInvalidSplitMode:
    def test_invalid_split_mode_raises(self, db_with_messages):
        from core.exceptions import DocxGenerationError
        db, tmp_path = db_with_messages
        gen = DocxGenerator(db, output_dir=str(tmp_path))
        with pytest.raises(DocxGenerationError):
            gen.generate(chat_id=-1001, chat_title="Test", split_mode="invalid")
