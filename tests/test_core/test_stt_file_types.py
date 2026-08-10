# -*- coding: utf-8 -*-
"""
Стык «парсер пишет file_type» ↔ «STT ищет file_type».

Класс ошибки: два модуля договорились о разных именах для одного и того
же. По отдельности каждый корректен, тесты каждого зелёные, а вместе они
не работают — и молча: выборка пуста, в журнале «нет голосовых
сообщений», исключения нет.

Поэтому тест не на воркер и не на парсер, а на согласие между ними.
"""
import inspect

import pytest

from core.database import DBManager
from core.stt.worker import STTWorker
from features.parser.api import ParserService

CHAT_ID = -1001111111111

# Что парсер реально может записать в file_type (_detect_media_type).
PARSER_MEDIA_TYPES = {"photo", "video", "videomessage", "voice", "file"}

# Что из этого подлежит распознаванию речи.
# "video" исключён намеренно: для длинных роликов есть RozittaTranscriber.
SPEECH_TYPES = {"voice", "videomessage"}


def test_parser_media_types_have_not_drifted():
    """
    Если парсер начнёт писать новое значение, тест упадёт и заставит
    решить, подлежит ли оно распознаванию, — вместо тихого пропуска.
    """
    src = inspect.getsource(ParserService._detect_media_type)
    written = {
        literal
        for literal in PARSER_MEDIA_TYPES
        if f'"{literal}"' in src
    }
    assert written == PARSER_MEDIA_TYPES, (
        "изменился набор значений file_type в _detect_media_type — "
        "проверьте STTWorker.STT_FILE_TYPES"
    )


def test_stt_covers_every_speech_type_the_parser_writes():
    """Главная проверка: то, что пишет парсер, STT обязан искать."""
    missing = SPEECH_TYPES - set(STTWorker.STT_FILE_TYPES)
    assert not missing, (
        f"STT не ищет типы, которые пишет парсер: {sorted(missing)}. "
        "Кружочки/голосовые не попадут в распознавание, и это будет "
        "выглядеть как «нет голосовых сообщений»."
    )


def test_stt_does_not_ask_for_plain_video():
    """Длинные видео — задача RozittaTranscriber, не парсера."""
    assert "video" not in STTWorker.STT_FILE_TYPES


def test_stt_types_are_known_to_the_parser_or_historical():
    """
    В списке допустимы только значения парсера плюс исторические
    написания из старых баз — опечатка не должна пройти незамеченной.
    """
    historical = {"video_note"}
    unknown = set(STTWorker.STT_FILE_TYPES) - PARSER_MEDIA_TYPES - historical
    assert not unknown, f"неизвестные типы в STT_FILE_TYPES: {sorted(unknown)}"


# ── сквозная проверка на реальной выборке ─────────────────────────────


@pytest.fixture
def db(tmp_path):
    with DBManager(str(tmp_path / "p.db")) as conn:
        conn.insert_chat(chat_id=CHAT_ID, title="Канал", chat_type="channel")
        rows = [
            (1, "videomessage", "media/21_video.mp4"),
            (2, "videomessage", "media/22_video.mp4"),
            (3, "voice",        "media/3.ogg"),
            (4, "video",        "media/4.mp4"),
            (5, "photo",        "media/5.jpg"),
            (6, "file",         "media/6.pdf"),
        ]
        for mid, ftype, path in rows:
            conn.insert_message(
                chat_id=CHAT_ID, message_id=mid,
                date=f"2026-08-{mid:02d} 10:00:00", user_id=1,
                file_type=ftype, media_path=path, is_comment=0,
            )
        yield conn


def test_round_messages_are_picked_up(db):
    """
    Регрессия: до исправления STTWorker искал «video_note», парсер писал
    «videomessage», и кружочки в выборку не попадали ни разу.
    """
    rows = db.get_stt_candidates(CHAT_ID, file_types=STTWorker.STT_FILE_TYPES)
    picked = {r["message_id"] for r in rows}
    assert {1, 2} <= picked, "кружочки не попали в выборку STT"


def test_voice_is_picked_up(db):
    rows = db.get_stt_candidates(CHAT_ID, file_types=STTWorker.STT_FILE_TYPES)
    assert 3 in {r["message_id"] for r in rows}


def test_photos_video_and_files_are_left_alone(db):
    rows = db.get_stt_candidates(CHAT_ID, file_types=STTWorker.STT_FILE_TYPES)
    picked = {r["message_id"] for r in rows}
    assert picked.isdisjoint({4, 5, 6})


def test_already_transcribed_are_not_offered_again(db):
    """Перераспознавание вручную не нужно — выборка сама пропускает готовое."""
    db.insert_transcription(peer_id=CHAT_ID, message_id=1, text="привет")
    rows = db.get_stt_candidates(CHAT_ID, file_types=STTWorker.STT_FILE_TYPES)
    picked = {r["message_id"] for r in rows}
    assert 1 not in picked
    assert 2 in picked


def test_default_argument_matches_the_worker():
    """
    У get_stt_candidates правильный список по умолчанию уже был, но воркер
    всегда передавал свой — и дефолт не срабатывал ни разу. Пусть они
    больше не расходятся молча.
    """
    default = inspect.signature(DBManager.get_stt_candidates)
    assert default.parameters["file_types"].default is None
    src = inspect.getsource(DBManager.get_stt_candidates)
    for ftype in SPEECH_TYPES:
        assert f'"{ftype}"' in src, f"{ftype} отсутствует в дефолте выборки"
