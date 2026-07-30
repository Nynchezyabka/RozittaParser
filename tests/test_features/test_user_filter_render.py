"""
tests/test_features/test_user_filter_render.py

FEAT-6 — заглушки скрытых участников в готовых документах.
Проверяется главное: текст скрытого участника не попадает в файл.
"""

import json

import pytest

from core.database import DBManager
from features.export.filters import UserFilter
from features.export.generator import (
    HtmlGenerator,
    JsonGenerator,
    MarkdownGenerator,
)

HIDDEN_TEXT = "СЕКРЕТНЫЙ_ТЕКСТ_БОБА"
VISIBLE_A = "видимый текст алисы"
VISIBLE_C = "видимый текст кэрол"


@pytest.fixture
def db_three_senders():
    """Alice(111) → Bob(222, будет скрыт) → Carol(333, отвечает Бобу)."""
    with DBManager(":memory:") as db:
        db.insert_messages_batch([
            {
                "chat_id": -1001, "message_id": 1,
                "date": "2024-01-15 10:01:00",
                "topic_id": None, "user_id": 111, "username": "Alice",
                "text": VISIBLE_A,
                "media_path": None, "file_type": None, "file_size": None,
                "reply_to_msg_id": None, "post_id": None,
                "is_comment": 0, "from_linked_group": 0,
            },
            {
                "chat_id": -1001, "message_id": 2,
                "date": "2024-01-15 10:02:00",
                "topic_id": None, "user_id": 222, "username": "Bob",
                "text": HIDDEN_TEXT,
                "media_path": None, "file_type": None, "file_size": None,
                "reply_to_msg_id": None, "post_id": None,
                "is_comment": 0, "from_linked_group": 0,
            },
            {
                "chat_id": -1001, "message_id": 3,
                "date": "2024-01-15 10:03:00",
                "topic_id": None, "user_id": 333, "username": "Carol",
                "text": VISIBLE_C,
                "media_path": None, "file_type": None, "file_size": None,
                "reply_to_msg_id": 2, "post_id": None,
                "is_comment": 0, "from_linked_group": 0,
            },
        ])
        yield db


@pytest.fixture
def exclude_bob():
    return UserFilter.make("exclude", [222])


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


# ──────────────────────────────────────────────────────────────────────────────
# Markdown
# ──────────────────────────────────────────────────────────────────────────────

class TestMarkdownPlaceholder:
    def test_hidden_text_absent(self, db_three_senders, exclude_bob, tmp_path):
        gen = MarkdownGenerator(db_three_senders, output_dir=str(tmp_path),
                                user_filter=exclude_bob)
        out = _read(gen.generate(-1001, "Тест", period_label="all")[0])
        assert HIDDEN_TEXT not in out

    def test_placeholder_present(self, db_three_senders, exclude_bob, tmp_path):
        gen = MarkdownGenerator(db_three_senders, output_dir=str(tmp_path),
                                user_filter=exclude_bob)
        out = _read(gen.generate(-1001, "Тест", period_label="all")[0])
        assert "Сообщение скрыто" in out

    def test_other_users_untouched(self, db_three_senders, exclude_bob, tmp_path):
        gen = MarkdownGenerator(db_three_senders, output_dir=str(tmp_path),
                                user_filter=exclude_bob)
        out = _read(gen.generate(-1001, "Тест", period_label="all")[0])
        assert VISIBLE_A in out
        assert VISIBLE_C in out

    def test_author_name_kept(self, db_three_senders, exclude_bob, tmp_path):
        """PLACEHOLDER_SHOW_AUTHOR = True — имя в заглушке остаётся."""
        gen = MarkdownGenerator(db_three_senders, output_dir=str(tmp_path),
                                user_filter=exclude_bob)
        out = _read(gen.generate(-1001, "Тест", period_label="all")[0])
        assert "Bob" in out

    def test_reply_context_survives(self, db_three_senders, exclude_bob, tmp_path):
        """Ради этого и нужна заглушка: ответ Кэрол не повисает."""
        gen = MarkdownGenerator(db_three_senders, output_dir=str(tmp_path),
                                user_filter=exclude_bob)
        out = _read(gen.generate(-1001, "Тест", period_label="all")[0])
        assert "в ответ на: Bob" in out

    def test_without_filter_text_present(self, db_three_senders, tmp_path):
        """Контроль: без фильтра текст на месте."""
        gen = MarkdownGenerator(db_three_senders, output_dir=str(tmp_path))
        out = _read(gen.generate(-1001, "Тест", period_label="all")[0])
        assert HIDDEN_TEXT in out


# ──────────────────────────────────────────────────────────────────────────────
# JSON
# ──────────────────────────────────────────────────────────────────────────────

class TestJsonPlaceholder:
    def test_hidden_text_absent(self, db_three_senders, exclude_bob, tmp_path):
        gen = JsonGenerator(db_three_senders, output_dir=str(tmp_path),
                            user_filter=exclude_bob)
        out = _read(gen.generate(-1001, "Тест", period_label="all")[0])
        assert HIDDEN_TEXT not in out

    def test_message_count_unchanged(self, db_three_senders, exclude_bob, tmp_path):
        """Скрытое сообщение остаётся в выгрузке — не удаляется."""
        gen = JsonGenerator(db_three_senders, output_dir=str(tmp_path),
                            user_filter=exclude_bob)
        raw = json.loads(_read(gen.generate(-1001, "Тест", period_label="all")[0]))
        records = raw if isinstance(raw, list) else raw.get("messages", raw)
        assert len(records) == 3

    def test_without_filter_text_present(self, db_three_senders, tmp_path):
        gen = JsonGenerator(db_three_senders, output_dir=str(tmp_path))
        out = _read(gen.generate(-1001, "Тест", period_label="all")[0])
        assert HIDDEN_TEXT in out


# ──────────────────────────────────────────────────────────────────────────────
# HTML
# ──────────────────────────────────────────────────────────────────────────────

class TestHtmlPlaceholder:
    def test_hidden_text_absent(self, db_three_senders, exclude_bob, tmp_path):
        gen = HtmlGenerator(db_three_senders, output_dir=str(tmp_path),
                            user_filter=exclude_bob)
        out = _read(gen.generate(-1001, "Тест", period_label="all")[0])
        assert HIDDEN_TEXT not in out

    def test_placeholder_present(self, db_three_senders, exclude_bob, tmp_path):
        gen = HtmlGenerator(db_three_senders, output_dir=str(tmp_path),
                            user_filter=exclude_bob)
        out = _read(gen.generate(-1001, "Тест", period_label="all")[0])
        assert "Сообщение скрыто" in out

    def test_without_filter_text_present(self, db_three_senders, tmp_path):
        gen = HtmlGenerator(db_three_senders, output_dir=str(tmp_path))
        out = _read(gen.generate(-1001, "Тест", period_label="all")[0])
        assert HIDDEN_TEXT in out


# ──────────────────────────────────────────────────────────────────────────────
# Медиа и расшифровки
# ──────────────────────────────────────────────────────────────────────────────

class TestHiddenMediaAndStt:
    def test_media_not_embedded(self, tmp_path):
        """Медиа скрытого участника не встраивается, файл на диске цел."""
        media = tmp_path / "secret_photo.jpg"
        media.write_bytes(b"\xff\xd8\xff")

        with DBManager(":memory:") as db:
            db.insert_messages_batch([{
                "chat_id": -1001, "message_id": 1,
                "date": "2024-01-15 10:01:00",
                "topic_id": None, "user_id": 222, "username": "Bob",
                "text": HIDDEN_TEXT,
                "media_path": str(media), "file_type": "photo",
                "file_size": 3,
                "reply_to_msg_id": None, "post_id": None,
                "is_comment": 0, "from_linked_group": 0,
            }])
            gen = MarkdownGenerator(db, output_dir=str(tmp_path),
                                    user_filter=UserFilter.make("exclude", [222]))
            out = _read(gen.generate(-1001, "Тест", period_label="all")[0])

        assert HIDDEN_TEXT not in out
        assert "secret_photo.jpg" not in out
        assert media.exists(), "файл медиа удалять нельзя"

    def test_transcription_not_leaked(self, tmp_path):
        """
        Расшифровка голосового скрытого участника не должна уехать
        в документ мимо заглушки (stt_map чистится в _apply_user_filter).
        """
        with DBManager(":memory:") as db:
            db.insert_messages_batch([{
                "chat_id": -1001, "message_id": 1,
                "date": "2024-01-15 10:01:00",
                "topic_id": None, "user_id": 222, "username": "Bob",
                "text": "",
                "media_path": None, "file_type": "voice", "file_size": None,
                "reply_to_msg_id": None, "post_id": None,
                "is_comment": 0, "from_linked_group": 0,
            }])
            db.insert_transcription(message_id=1, peer_id=-1001, text=HIDDEN_TEXT)

            gen = MarkdownGenerator(db, output_dir=str(tmp_path),
                                    user_filter=UserFilter.make("exclude", [222]))
            out = _read(gen.generate(-1001, "Тест", period_label="all")[0])

        assert HIDDEN_TEXT not in out
