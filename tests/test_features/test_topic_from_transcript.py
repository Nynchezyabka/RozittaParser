# -*- coding: utf-8 -*-
"""
Тема поста из машинной расшифровки голоса (колонка «О чём»).

Тексты в наборе — живые расшифровки канала, не выдуманные.
"""
import pytest

from core.database import DBManager
from features.export.knowledge_base import (
    KnowledgeBaseBuilder,
    _STT_MARK,
    _topic_from_transcript,
    extract_post_topic,
)

CHAT_ID = -1002058687771

# Первая фраза — приветствие, тему автор называет во второй.
REAL_ANNOUNCE = (
    "Привет, на связи Маша. И в этом аудио я расскажу вам про пятый поток "
    "гастрономии. Кому подходит курс, какие фишки у нас есть в новом потоке?"
)

# Открывается обрывками в два-три слова — они не должны попасть в тему.
REAL_SHORT_OPENING = (
    "Так. Поэтому разве что? Получается что ли? Бургер с тамленой говядиной. "
    "Дань, подписчики говорят, это не свежая еда."
)


# ── разбор расшифровки ────────────────────────────────────────────────


def test_greeting_is_skipped():
    assert _topic_from_transcript(REAL_ANNOUNCE).startswith("И в этом аудио")


def test_short_sentences_are_skipped():
    assert _topic_from_transcript(REAL_SHORT_OPENING) == (
        "Бургер с тамленой говядиной."
    )


@pytest.mark.parametrize("value", [None, "", "   ", "Так. Ага. Ну вот."])
def test_nothing_usable_gives_none(value):
    assert _topic_from_transcript(value) is None


def test_greeting_only_gives_none():
    assert _topic_from_transcript("Привет, мои хорошие, я сегодня с вами!") is None


def test_line_breaks_do_not_matter():
    """Расшифровка приходит одним абзацем, но рвать её могло и переносами."""
    assert _topic_from_transcript(
        "Привет.\nСегодня разбираем хранение овощей в маленьком холодильнике."
    ) == "Сегодня разбираем хранение овощей в маленьком холодильнике."


def test_long_sentence_is_truncated():
    long_one = "Сегодня " + "очень " * 60 + "длинно."
    result = _topic_from_transcript(long_one)
    assert len(result) == 121 and result.endswith("…")


# ── подстановка в тему поста ──────────────────────────────────────────


def test_transcript_replaces_media_placeholder():
    topic = extract_post_topic(None, "videomessage", transcript=REAL_ANNOUNCE)
    assert topic.startswith(_STT_MARK)
    assert "И в этом аудио" in topic


def test_own_text_wins_over_transcript():
    """Авторское слово главнее того, что услышала модель."""
    topic = extract_post_topic(
        "Разбираем дренаж участка от и до", "videomessage",
        transcript=REAL_ANNOUNCE,
    )
    assert topic == "Разбираем дренаж участка от и до"
    assert _STT_MARK not in topic


def test_useless_transcript_falls_back_to_placeholder():
    topic = extract_post_topic(None, "videomessage", transcript="Так. Ага.")
    assert topic == "[кружочек]"


def test_call_without_transcript_still_works():
    """Старые вызовы с двумя аргументами не должны сломаться."""
    assert extract_post_topic(None, "photo") == "[фото]"


# ── таблица целиком ───────────────────────────────────────────────────


@pytest.fixture
def channel_with_voice(tmp_path):
    with DBManager(str(tmp_path / "p.db")) as db:
        db.insert_chat(chat_id=CHAT_ID, title="Канал", chat_type="channel")
        db.insert_message(chat_id=CHAT_ID, message_id=1,
                          date="2026-07-03 10:00:00", user_id=999,
                          username="Канал", text=None,
                          file_type="videomessage", is_comment=0)
        db.insert_transcription(message_id=1, peer_id=CHAT_ID,
                                text=REAL_ANNOUNCE)
        yield db, tmp_path


def _index(db, out):
    KnowledgeBaseBuilder(db=db, output_dir=str(out)).build(
        chat_id=CHAT_ID, chat_title="Канал", period_label="alltime",
        exported_files=[])
    return (out / "00_Оглавление.md").read_text(encoding="utf-8")


def test_table_shows_transcript_instead_of_placeholder(channel_with_voice):
    content = _index(*channel_with_voice)
    assert "[кружочек]" not in content
    assert f"{_STT_MARK} И в этом аудио" in content


def test_legend_explains_the_mark(channel_with_voice):
    content = _index(*channel_with_voice)
    assert f"{_STT_MARK} — фраза из машинной расшифровки голоса" in content


def test_legend_is_absent_without_marks(tmp_path):
    """Объяснять значки, которых в таблице нет, — только мешать."""
    with DBManager(str(tmp_path / "p.db")) as db:
        db.insert_chat(chat_id=CHAT_ID, title="Канал", chat_type="channel")
        db.insert_message(chat_id=CHAT_ID, message_id=1,
                          date="2026-07-03 10:00:00", user_id=999,
                          username="Канал", text="Обычный текстовый пост",
                          is_comment=0)
        content = _index(db, tmp_path)
    assert _STT_MARK not in content
