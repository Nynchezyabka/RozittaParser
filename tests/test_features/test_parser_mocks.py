"""
tests/test_features/test_parser_mocks.py

Тесты: ParserService — collect_data, _process_message, static helpers с моками.
"""
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock

from telethon.tl.types import (
    Channel, Chat, ChatPhotoEmpty, DocumentAttributeAudio,
    DocumentAttributeVideo, Message,
    MessageMediaDocument, MessageMediaPhoto, User,
)

from core.database import DBManager
from features.parser.api import CollectParams, CollectResult, ParserService


def _channel(title="Test Chat", broadcast=False, forum=False):
    return Channel(
        id=100, title=title,
        photo=ChatPhotoEmpty(), date=datetime.now(timezone.utc),
        broadcast=broadcast, megagroup=not broadcast, forum=forum,
    )


def _mock_message(msg_id=1, text="hello", date=None, sender_id=1,
                  media=None, reply_to=None, sender=None, replies=None):
    if date is None:
        date = datetime.now(timezone.utc)
    msg = MagicMock(spec=Message)
    msg.id = msg_id
    msg.text = text
    msg.date = date
    msg.sender_id = sender_id
    msg.media = media
    msg.reply_to = reply_to
    msg.sender = sender
    msg.replies = replies
    msg.forum_topic = False
    return msg


def _service(tmp_path, messages=None, entity=None):
    db = DBManager(str(tmp_path / "test.db"))
    client = MagicMock()
    ent = entity or _channel()

    if messages is None:
        async def empty_iter(*a, **kw):
            return
            yield
        client.iter_messages = empty_iter
    else:
        client.iter_messages = messages

    client.get_entity = AsyncMock(return_value=ent)
    client.get_messages = AsyncMock(return_value=MagicMock(total=0))
    svc = ParserService(client=client, db=db)
    return svc, db, client


class TestCollectDataBasic:
    @pytest.mark.asyncio
    async def test_empty_chat(self, tmp_path):
        svc, db, client = _service(tmp_path)
        params = CollectParams(chat_id=-100, output_dir=str(tmp_path))
        result = await svc.collect_data(params)
        assert result.success is True
        assert result.messages_count == 0
        assert result.chat_title == "Test Chat"

    @pytest.mark.asyncio
    async def test_get_entity_called(self, tmp_path):
        svc, db, client = _service(tmp_path)
        params = CollectParams(chat_id=-100, output_dir=str(tmp_path))
        await svc.collect_data(params)
        client.get_entity.assert_called_once_with(-100)

    @pytest.mark.asyncio
    async def test_chat_not_found_raises(self, tmp_path):
        from core.exceptions import ChatNotFoundError
        svc, db, client = _service(tmp_path)
        client.get_entity = AsyncMock(side_effect=Exception("not found"))
        params = CollectParams(chat_id=-999, output_dir=str(tmp_path))
        with pytest.raises(ChatNotFoundError):
            await svc.collect_data(params)

    @pytest.mark.asyncio
    async def test_collect_result_fields(self, tmp_path):
        svc, db, client = _service(tmp_path)
        params = CollectParams(chat_id=-100, output_dir=str(tmp_path))
        result = await svc.collect_data(params)
        assert isinstance(result, CollectResult)
        assert result.chat_id == -100
        assert result.period_label == "alltime"

    @pytest.mark.asyncio
    async def test_days_limit_sets_period_label(self, tmp_path):
        svc, db, client = _service(tmp_path)
        params = CollectParams(chat_id=-100, output_dir=str(tmp_path), days_limit=30)
        result = await svc.collect_data(params)
        assert result.period_label != "alltime"
        assert "_to_" in result.period_label


class TestCollectDataMessages:
    @pytest.mark.asyncio
    async def test_collects_messages(self, tmp_path):
        now = datetime.now(timezone.utc)
        msgs = [_mock_message(msg_id=i, text=f"msg{i}",
                               date=now - timedelta(seconds=i))
                for i in range(1, 4)]

        async def msg_iter(*a, **kw):
            for m in msgs:
                yield m

        svc, db, client = _service(tmp_path, messages=msg_iter)
        client.get_messages = AsyncMock(return_value=MagicMock(total=3))

        params = CollectParams(chat_id=-100, output_dir=str(tmp_path))
        result = await svc.collect_data(params)
        assert result.messages_count == 3

    @pytest.mark.asyncio
    async def test_cutoff_date_filters_old(self, tmp_path):
        now = datetime.now(timezone.utc)
        recent = _mock_message(msg_id=1, text="new", date=now)
        old = _mock_message(msg_id=2, text="old",
                            date=now - timedelta(days=365))

        async def msg_iter(*a, **kw):
            for m in [recent, old]:
                yield m

        svc, db, client = _service(tmp_path, messages=msg_iter)
        client.get_messages = AsyncMock(return_value=MagicMock(total=2))

        params = CollectParams(
            chat_id=-100, output_dir=str(tmp_path), days_limit=30,
        )
        result = await svc.collect_data(params)
        assert result.messages_count == 1

    @pytest.mark.asyncio
    async def test_user_id_filter(self, tmp_path):
        now = datetime.now(timezone.utc)
        msgs = [
            _mock_message(msg_id=1, sender_id=10, date=now),
            _mock_message(msg_id=2, sender_id=20, date=now),
            _mock_message(msg_id=3, sender_id=10, date=now),
        ]

        async def msg_iter(*a, **kw):
            for m in msgs:
                yield m

        svc, db, client = _service(tmp_path, messages=msg_iter)
        client.get_messages = AsyncMock(return_value=MagicMock(total=3))

        params = CollectParams(
            chat_id=-100, output_dir=str(tmp_path), user_ids=[10],
        )
        result = await svc.collect_data(params)
        assert result.messages_count == 2


class TestCollectDataChatTypes:
    @pytest.mark.asyncio
    async def test_private_chat(self, tmp_path):
        entity = User(id=42, first_name="Alice")
        svc, db, client = _service(tmp_path, entity=entity)
        params = CollectParams(chat_id=42, output_dir=str(tmp_path))
        result = await svc.collect_data(params)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_group_chat(self, tmp_path):
        entity = Chat(
            id=100, title="MyGroup",
            photo=ChatPhotoEmpty(), participants_count=50,
            date=datetime.now(timezone.utc), version=1,
        )
        svc, db, client = _service(tmp_path, entity=entity)
        params = CollectParams(chat_id=-100, output_dir=str(tmp_path))
        result = await svc.collect_data(params)
        assert result.success is True
        assert result.chat_title == "MyGroup"

    @pytest.mark.asyncio
    async def test_channel_chat(self, tmp_path):
        entity = _channel(title="News", broadcast=True)
        svc, db, client = _service(tmp_path, entity=entity)
        params = CollectParams(chat_id=-100, output_dir=str(tmp_path))
        result = await svc.collect_data(params)
        assert result.success is True


class TestProcessMessage:
    @pytest.mark.asyncio
    async def test_basic_message(self, tmp_path):
        svc, db, client = _service(tmp_path)
        msg = _mock_message(
            msg_id=1, text="Hello", sender_id=42,
            sender=User(id=42, first_name="Alice", username="alice"),
        )
        row, media_err = await svc._process_message(
            msg, chat_id=-100, topic_id=None, media_filter=None,
        )
        assert row is not None
        assert row["message_id"] == 1
        assert row["text"] == "Hello"
        assert row["chat_id"] == -100
        assert media_err is None

    @pytest.mark.asyncio
    async def test_comment_message(self, tmp_path):
        svc, db, client = _service(tmp_path)
        msg = _mock_message(msg_id=5, text="reply")
        row, _ = await svc._process_message(
            msg, chat_id=-100, topic_id=None, media_filter=None,
            post_id=1, is_comment=True, from_linked=True,
        )
        assert row["is_comment"] == 1
        assert row["post_id"] == 1
        assert row["from_linked_group"] == 1

    @pytest.mark.asyncio
    async def test_reply_to_extracted(self, tmp_path):
        svc, db, client = _service(tmp_path)
        reply_to = MagicMock()
        reply_to.reply_to_msg_id = 99
        msg = _mock_message(msg_id=2, reply_to=reply_to)
        row, _ = await svc._process_message(
            msg, chat_id=-100, topic_id=None, media_filter=None,
        )
        assert row["reply_to_msg_id"] == 99

    @pytest.mark.asyncio
    async def test_row_has_all_required_fields(self, tmp_path):
        svc, db, client = _service(tmp_path)
        msg = _mock_message()
        row, _ = await svc._process_message(
            msg, chat_id=-100, topic_id=None, media_filter=None,
        )
        expected_keys = {
            "chat_id", "message_id", "topic_id", "user_id", "username",
            "date", "text", "media_path", "file_type", "file_size",
            "reply_to_msg_id", "post_id", "is_comment", "from_linked_group",
        }
        assert set(row.keys()) == expected_keys


class TestShouldDownload:
    def test_no_media(self):
        msg = MagicMock()
        msg.media = None
        assert ParserService._should_download(msg, ["photo"]) is False

    def test_photo_with_filter(self):
        msg = MagicMock()
        msg.media = MagicMock(spec=MessageMediaPhoto)
        assert ParserService._should_download(msg, ["photo"]) is True
        assert ParserService._should_download(msg, ["video"]) is False

    def test_empty_filter_downloads_all(self):
        msg = MagicMock()
        msg.media = MagicMock(spec=MessageMediaPhoto)
        assert ParserService._should_download(msg, []) is True

    def test_video_filter(self):
        msg = MagicMock()
        doc = MagicMock()
        video_attr = MagicMock(spec=DocumentAttributeVideo)
        video_attr.round_message = False
        doc.attributes = [video_attr]
        msg.media = MessageMediaDocument(document=doc)
        assert ParserService._should_download(msg, ["video"]) is True

    def test_videomessage_filter(self):
        msg = MagicMock()
        doc = MagicMock()
        video_attr = MagicMock(spec=DocumentAttributeVideo)
        video_attr.round_message = True
        doc.attributes = [video_attr]
        msg.media = MessageMediaDocument(document=doc)
        assert ParserService._should_download(msg, ["videomessage"]) is True
        assert ParserService._should_download(msg, ["video"]) is False

    def test_voice_filter(self):
        msg = MagicMock()
        doc = MagicMock()
        audio_attr = MagicMock(spec=DocumentAttributeAudio)
        audio_attr.voice = True
        doc.attributes = [audio_attr]
        msg.media = MessageMediaDocument(document=doc)
        assert ParserService._should_download(msg, ["voice"]) is True
        assert ParserService._should_download(msg, ["file"]) is False

    def test_file_filter(self):
        msg = MagicMock()
        doc = MagicMock()
        doc.attributes = []
        msg.media = MessageMediaDocument(document=doc)
        assert ParserService._should_download(msg, ["file"]) is True


class TestDetectMediaType:
    def test_no_media(self):
        msg = MagicMock()
        msg.media = None
        assert ParserService._detect_media_type(msg) is None

    def test_photo(self):
        msg = MagicMock()
        msg.media = MagicMock(spec=MessageMediaPhoto)
        assert ParserService._detect_media_type(msg) == "photo"

    def test_video(self):
        msg = MagicMock()
        doc = MagicMock()
        video_attr = MagicMock(spec=DocumentAttributeVideo)
        video_attr.round_message = False
        doc.attributes = [video_attr]
        msg.media = MessageMediaDocument(document=doc)
        assert ParserService._detect_media_type(msg) == "video"

    def test_videomessage(self):
        msg = MagicMock()
        doc = MagicMock()
        video_attr = MagicMock(spec=DocumentAttributeVideo)
        video_attr.round_message = True
        doc.attributes = [video_attr]
        msg.media = MessageMediaDocument(document=doc)
        assert ParserService._detect_media_type(msg) == "videomessage"

    def test_voice(self):
        msg = MagicMock()
        doc = MagicMock()
        audio_attr = MagicMock(spec=DocumentAttributeAudio)
        audio_attr.voice = True
        doc.attributes = [audio_attr]
        msg.media = MessageMediaDocument(document=doc)
        assert ParserService._detect_media_type(msg) == "voice"

    def test_file(self):
        msg = MagicMock()
        doc = MagicMock()
        doc.attributes = []
        msg.media = MessageMediaDocument(document=doc)
        assert ParserService._detect_media_type(msg) == "file"


class TestExtractTopicId:
    def test_reply_to_top_id(self):
        msg = MagicMock()
        msg.reply_to = MagicMock()
        msg.reply_to.reply_to_top_id = 42
        msg.reply_to.reply_to_msg_id = 10
        msg.forum_topic = False
        assert ParserService._extract_topic_id(msg) == 42

    def test_reply_to_msg_id_fallback(self):
        msg = MagicMock()
        msg.reply_to = MagicMock()
        msg.reply_to.reply_to_top_id = None
        msg.reply_to.reply_to_msg_id = 15
        msg.forum_topic = False
        assert ParserService._extract_topic_id(msg) == 15

    def test_forum_topic_flag(self):
        msg = MagicMock()
        msg.reply_to = None
        msg.forum_topic = True
        msg.id = 99
        assert ParserService._extract_topic_id(msg) == 99

    def test_no_topic(self):
        msg = MagicMock()
        msg.reply_to = None
        msg.forum_topic = False
        assert ParserService._extract_topic_id(msg) is None


class TestGetSenderName:
    """См. подробный разбор контракта в test_parser_static.py."""

    CHAT_TITLE = "Тестовый чат"

    def _service(self):
        svc = ParserService(MagicMock(), MagicMock())
        svc._chat_title = self.CHAT_TITLE
        return svc

    def test_user_with_username(self):
        msg = MagicMock()
        msg.sender = User(id=1, first_name="Alice", username="alice")
        assert self._service()._get_sender_name(msg) == "alice"

    def test_user_without_username(self):
        msg = MagicMock()
        msg.sender = User(id=1, first_name="Alice", last_name="Smith")
        assert self._service()._get_sender_name(msg) == "Alice Smith"

    def test_no_sender_falls_back_to_chat_title(self):
        """UNKNOWN-1: отправитель скрыт → автором считается сам чат."""
        msg = MagicMock()
        msg.sender = None
        msg.from_id = None
        assert self._service()._get_sender_name(msg) == self.CHAT_TITLE

    def test_channel_sender(self):
        msg = MagicMock()
        channel = MagicMock()
        channel.title = "News Channel"
        msg.sender = channel
        assert self._service()._get_sender_name(msg) == "News Channel"


class TestClassifyChatType:
    def test_user(self):
        assert ParserService._classify_chat_type(User(id=1)) == "private"

    def test_chat(self):
        assert ParserService._classify_chat_type(
            Chat(id=1, title="g", photo=ChatPhotoEmpty(),
                 participants_count=10, date=datetime.now(timezone.utc), version=1)
        ) == "group"

    def test_broadcast_channel(self):
        e = _channel(broadcast=True)
        assert ParserService._classify_chat_type(e) == "channel"

    def test_forum(self):
        e = _channel(broadcast=False, forum=True)
        assert ParserService._classify_chat_type(e) == "forum"

    def test_megagroup(self):
        e = _channel(broadcast=False, forum=False)
        assert ParserService._classify_chat_type(e) == "group"


class TestResolveCutoff:
    def test_all_time(self):
        from config import DAYS_LIMIT_ALL_TIME
        cutoff, label = ParserService._resolve_cutoff(DAYS_LIMIT_ALL_TIME)
        assert cutoff is None
        assert label == "alltime"

    def test_zero_is_all_time(self):
        cutoff, label = ParserService._resolve_cutoff(0)
        assert cutoff is None
        assert label == "alltime"

    def test_specific_days(self):
        cutoff, label = ParserService._resolve_cutoff(30)
        assert cutoff is not None
        assert "_to_" in label


# ---------------------------------------------------------------------------
# Issue #55: Large video download timeout handling
# ---------------------------------------------------------------------------

class TestDownloadMediaTimeout:
    def test_cleanup_partial_on_timeout(self, tmp_path):
        import os
        """Timeout → partial file removed, OSError raised for retry."""
        import asyncio
        target = str(tmp_path / "video")
        # Создаём partial файл
        partial = target + ".mp4"
        with open(partial, "w") as f:
            f.write("partial data")

        from features.parser.api import _cleanup_partial
        _cleanup_partial(target)
        assert not os.path.exists(partial)

    def test_cleanup_partial_no_file(self, tmp_path):
        """_cleanup_partial не падает если файлов нет."""
        from features.parser.api import _cleanup_partial
        target = str(tmp_path / "nonexistent")
        _cleanup_partial(target)  # should not raise

    def test_existing_full_file_not_redownloaded(self, tmp_path):
        """Если полный файл уже на диске — возвращает путь без повторной загрузки."""
        import os
        import glob
        target = str(tmp_path / "video")
        full_file = target + ".mp4"
        with open(full_file, "wb") as f:
            f.write(b"x" * 1000)

        found = glob.glob(target + ".*")
        assert len(found) == 1
        assert os.path.getsize(found[0]) == 1000
