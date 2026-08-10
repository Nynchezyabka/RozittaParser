"""
tests/test_features/test_parser_static.py

Тесты: статические методы ParserService — _should_download, _detect_media_type,
_extract_topic_id, _get_sender_name, _classify_chat_type, _resolve_cutoff,
CollectParams, _extract_row_sync, _build_media_dir, _get_original_filename.
"""
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

from telethon.tl.types import (
    Channel,
    Chat,
    DocumentAttributeAudio,
    DocumentAttributeFilename,
    DocumentAttributeVideo,
    Message,
    MessageMediaDocument,
    MessageMediaPhoto,
    User,
)
from features.parser.api import ParserService, CollectParams, CollectResult


# ──────────────────────────────────────────────────────────────────────────────
# Вспомогательные фабрики
# ──────────────────────────────────────────────────────────────────────────────

def _make_msg(media_type=None):
    msg = MagicMock(spec=Message)
    if media_type is None:
        msg.media = None
        return msg
    if media_type == "photo":
        msg.media = MessageMediaPhoto(photo=MagicMock())
    elif media_type in ("video", "voice", "file", "videomessage"):
        doc = MagicMock()
        if media_type == "video":
            doc.attributes = [DocumentAttributeVideo(w=0, h=0, duration=0)]
        elif media_type == "videomessage":
            doc.attributes = [DocumentAttributeVideo(w=0, h=0, duration=0, round_message=True)]
        elif media_type == "voice":
            doc.attributes = [DocumentAttributeAudio(duration=0, voice=True)]
        else:
            doc.attributes = []
        msg.media = MessageMediaDocument(document=doc)
    return msg


def _make_topic_msg(reply_to_top_id=None, reply_to_msg_id=None, forum_topic=False, msg_id=1):
    msg = MagicMock()
    msg.id = msg_id
    msg.forum_topic = forum_topic
    if reply_to_top_id is None and reply_to_msg_id is None:
        msg.reply_to = None
    else:
        msg.reply_to = MagicMock()
        msg.reply_to.reply_to_top_id = reply_to_top_id
        msg.reply_to.reply_to_msg_id = reply_to_msg_id
    return msg


# ──────────────────────────────────────────────────────────────────────────────
# _should_download
# ──────────────────────────────────────────────────────────────────────────────

class TestShouldDownload:
    def test_no_media(self):
        assert ParserService._should_download(_make_msg(None), ["photo"]) is False

    def test_empty_filter_downloads_all(self):
        assert ParserService._should_download(_make_msg("photo"), []) is True

    def test_photo_in_filter(self):
        assert ParserService._should_download(_make_msg("photo"), ["photo"]) is True

    def test_photo_not_in_filter(self):
        assert ParserService._should_download(_make_msg("photo"), ["video"]) is False

    def test_video(self):
        assert ParserService._should_download(_make_msg("video"), ["video"]) is True

    def test_video_not_in_filter(self):
        assert ParserService._should_download(_make_msg("video"), ["photo"]) is False

    def test_videomessage(self):
        assert ParserService._should_download(_make_msg("videomessage"), ["videomessage"]) is True

    def test_videomessage_not_round(self):
        assert ParserService._should_download(_make_msg("videomessage"), ["video"]) is False

    def test_voice(self):
        assert ParserService._should_download(_make_msg("voice"), ["voice"]) is True

    def test_voice_not_in_filter(self):
        assert ParserService._should_download(_make_msg("voice"), ["photo"]) is False

    def test_file(self):
        assert ParserService._should_download(_make_msg("file"), ["file"]) is True

    def test_file_not_in_filter(self):
        assert ParserService._should_download(_make_msg("file"), ["photo"]) is False

    def test_multiple_filters_match(self):
        assert ParserService._should_download(_make_msg("photo"), ["video", "photo"]) is True


# ──────────────────────────────────────────────────────────────────────────────
# _detect_media_type
# ──────────────────────────────────────────────────────────────────────────────

class TestDetectMediaType:
    def test_no_media(self):
        assert ParserService._detect_media_type(_make_msg(None)) is None

    def test_photo(self):
        assert ParserService._detect_media_type(_make_msg("photo")) == "photo"

    def test_video(self):
        assert ParserService._detect_media_type(_make_msg("video")) == "video"

    def test_videomessage(self):
        assert ParserService._detect_media_type(_make_msg("videomessage")) == "videomessage"

    def test_voice(self):
        assert ParserService._detect_media_type(_make_msg("voice")) == "voice"

    def test_file(self):
        assert ParserService._detect_media_type(_make_msg("file")) == "file"


# ──────────────────────────────────────────────────────────────────────────────
# _extract_topic_id
# ──────────────────────────────────────────────────────────────────────────────

class TestExtractTopicId:
    def test_reply_to_top_id(self):
        assert ParserService._extract_topic_id(_make_topic_msg(reply_to_top_id=42)) == 42

    def test_reply_to_msg_id_fallback(self):
        assert ParserService._extract_topic_id(_make_topic_msg(reply_to_msg_id=99)) == 99

    def test_top_id_priority_over_msg_id(self):
        msg = _make_topic_msg(reply_to_top_id=42, reply_to_msg_id=99)
        assert ParserService._extract_topic_id(msg) == 42

    def test_forum_topic_flag(self):
        assert ParserService._extract_topic_id(_make_topic_msg(forum_topic=True, msg_id=7)) == 7

    def test_no_topic(self):
        assert ParserService._extract_topic_id(_make_topic_msg()) is None

    def test_zero_top_id_skipped(self):
        msg = _make_topic_msg(reply_to_top_id=0, reply_to_msg_id=0)
        assert ParserService._extract_topic_id(msg) is None


# ──────────────────────────────────────────────────────────────────────────────
# _get_sender_name
# ──────────────────────────────────────────────────────────────────────────────

class TestGetSenderName:
    """
    _get_sender_name — instance-метод: трижды обращается к self._chat_title.
    Зовём через экземпляр, а не через класс.

    Контракт «неизвестный отправитель → название чата» задан UNKNOWN-1
    (Variant A-2): Telegram скрывает отправителя у постов и комментариев
    от имени канала, и автор там — сам канал, как это показывает клиент.
    """

    CHAT_TITLE = "Тестовый чат"

    def _service(self, chat_title=CHAT_TITLE):
        svc = ParserService(MagicMock(), MagicMock())
        svc._chat_title = chat_title
        return svc

    def _msg_with_sender(self, sender):
        msg = MagicMock()
        msg.sender = sender
        return msg

    def test_user_with_username(self):
        sender = User(id=1, username="john")
        assert self._service()._get_sender_name(
            self._msg_with_sender(sender)) == "john"

    def test_user_with_first_last_name(self):
        sender = User(id=1, first_name="John", last_name="Doe")
        assert self._service()._get_sender_name(
            self._msg_with_sender(sender)) == "John Doe"

    def test_user_first_only(self):
        sender = User(id=1, first_name="Alice")
        assert self._service()._get_sender_name(
            self._msg_with_sender(sender)) == "Alice"

    def test_user_no_names(self):
        """У User без имён fallback остался «Unknown» — чат тут ни при чём."""
        sender = User(id=1)
        assert self._service()._get_sender_name(
            self._msg_with_sender(sender)) == "Unknown"

    def test_channel_sender(self):
        sender = Channel(id=1, title="My Channel", photo=MagicMock(), date=None)
        assert self._service()._get_sender_name(
            self._msg_with_sender(sender)) == "My Channel"

    def test_chat_sender(self):
        sender = Chat(id=1, title="My Group", photo=MagicMock(),
                      participants_count=0, date=None, version=0)
        assert self._service()._get_sender_name(
            self._msg_with_sender(sender)) == "My Group"

    # ── UNKNOWN-1: отправитель скрыт → автор это сам чат ──────────────

    def test_no_sender_falls_back_to_chat_title(self):
        msg = MagicMock()
        msg.sender = None
        msg.from_id = None
        assert self._service()._get_sender_name(msg) == self.CHAT_TITLE

    def test_sender_without_title_falls_back_to_chat_title(self):
        sender = MagicMock()
        sender.title = None
        assert self._service()._get_sender_name(
            self._msg_with_sender(sender)) == self.CHAT_TITLE

    def test_from_id_channel_falls_back_to_chat_title(self):
        msg = MagicMock()
        msg.sender = None
        msg.from_id = MagicMock(spec=["channel_id"])
        msg.from_id.channel_id = 777
        assert self._service()._get_sender_name(msg) == self.CHAT_TITLE

    def test_from_id_user_gives_synthetic_name(self):
        """Удалённый аккаунт: имени нет, но id есть — им и представляемся."""
        msg = MagicMock()
        msg.sender = None
        msg.from_id = MagicMock(spec=["user_id"])
        msg.from_id.user_id = 42
        assert self._service()._get_sender_name(msg) == "User_42"

    def test_unknown_survives_when_chat_title_empty(self):
        """Ветка `or "Unknown"` жива: без названия чата подставить нечего."""
        msg = MagicMock()
        msg.sender = None
        msg.from_id = None
        assert self._service(chat_title="")._get_sender_name(msg) == "Unknown"


# ──────────────────────────────────────────────────────────────────────────────
# _classify_chat_type
# ──────────────────────────────────────────────────────────────────────────────

class TestClassifyChatType:
    def test_user(self):
        assert ParserService._classify_chat_type(User(id=1)) == "private"

    def test_chat(self):
        assert ParserService._classify_chat_type(
            Chat(id=1, title="g", photo=MagicMock(), participants_count=0, date=None, version=0)
        ) == "group"

    def test_broadcast_channel(self):
        ch = Channel(id=1, title="test", photo=MagicMock(), date=None)
        ch.broadcast = True
        assert ParserService._classify_chat_type(ch) == "channel"

    def test_forum(self):
        ch = Channel(id=1, title="test", photo=MagicMock(), date=None)
        ch.broadcast = False
        ch.forum = True
        assert ParserService._classify_chat_type(ch) == "forum"

    def test_megagroup_no_forum(self):
        ch = Channel(id=1, title="test", photo=MagicMock(), date=None)
        ch.broadcast = False
        ch.forum = False
        assert ParserService._classify_chat_type(ch) == "group"

    def test_unknown_object(self):
        assert ParserService._classify_chat_type("string") == "group"


# ──────────────────────────────────────────────────────────────────────────────
# _resolve_cutoff
# ──────────────────────────────────────────────────────────────────────────────

class TestResolveCutoff:
    def test_zero_is_alltime(self):
        cutoff, label = ParserService._resolve_cutoff(0)
        assert cutoff is None
        assert label == "alltime"

    def test_365_is_alltime(self):
        cutoff, label = ParserService._resolve_cutoff(365)
        assert cutoff is None
        assert label == "alltime"

    def test_500_is_alltime(self):
        cutoff, label = ParserService._resolve_cutoff(500)
        assert cutoff is None
        assert label == "alltime"

    def test_specific_days(self):
        cutoff, label = ParserService._resolve_cutoff(30)
        assert cutoff is not None
        assert label.startswith("20")
        expected = datetime.now(timezone.utc) - timedelta(days=30)
        assert abs((cutoff - expected).total_seconds()) < 5

    def test_1_day(self):
        cutoff, label = ParserService._resolve_cutoff(1)
        assert cutoff is not None
        expected = datetime.now(timezone.utc) - timedelta(days=1)
        assert abs((cutoff - expected).total_seconds()) < 5


# ──────────────────────────────────────────────────────────────────────────────
# CollectParams
# ──────────────────────────────────────────────────────────────────────────────

class TestCollectParams:
    def test_defaults(self):
        p = CollectParams(chat_id=-100)
        assert p.topic_id is None
        assert p.days_limit == 0
        assert p.media_filter is None
        assert p.download_comments is False
        assert p.user_ids is None
        assert p.re_download is False

    def test_custom(self):
        p = CollectParams(
            chat_id=-100, topic_id=5, days_limit=7,
            media_filter=["photo", "video"],
            download_comments=True,
            user_ids=[1, 2, 3],
        )
        assert p.topic_id == 5
        assert len(p.media_filter) == 2


# ──────────────────────────────────────────────────────────────────────────────
# CollectResult
# ──────────────────────────────────────────────────────────────────────────────

class TestCollectResult:
    def test_defaults(self):
        r = CollectResult(success=True, chat_id=-100)
        assert r.messages_count == 0
        assert r.comments_count == 0
        assert r.media_count == 0
        assert r.period_label == "alltime"
        assert r.errors == []
        assert r.db_path == ""

    def test_custom(self):
        r = CollectResult(
            success=True, chat_id=-100, chat_title="Test",
            messages_count=50, comments_count=5, media_count=10,
            period_label="2025-01-01_to_2025-06-01",
            errors=["err1"], db_path="/tmp/test.db",
        )
        assert r.messages_count == 50
        assert r.period_label.startswith("2025")


# ──────────────────────────────────────────────────────────────────────────────
# _get_original_filename
# ──────────────────────────────────────────────────────────────────────────────

class TestGetOriginalFilename:
    def test_no_document_media(self):
        msg = MagicMock()
        msg.media = MessageMediaPhoto(photo=MagicMock())
        assert ParserService._get_original_filename(msg) is None

    def test_document_with_filename(self):
        msg = MagicMock()
        doc = MagicMock()
        doc.attributes = [DocumentAttributeFilename("video.mp4")]
        msg.media = MessageMediaDocument(document=doc)
        result = ParserService._get_original_filename(msg)
        assert result == "video.mp4"

    def test_document_without_filename_attr(self):
        msg = MagicMock()
        doc = MagicMock()
        doc.attributes = []
        msg.media = MessageMediaDocument(document=doc)
        assert ParserService._get_original_filename(msg) is None
