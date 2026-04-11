"""
tests/test_features/test_parser.py

Тесты: CollectParams (BUG-4 user_ids), фильтрация sender_id.
Не использует реальный Telegram — только датаклассы и логику.
"""
from features.parser.api import CollectParams


# ──────────────────────────────────────────────────────────────────────────────
# CollectParams — контракт полей (BUG-4)
# ──────────────────────────────────────────────────────────────────────────────

class TestCollectParamsUserIds:
    def test_user_ids_default_none(self):
        """По умолчанию user_ids=None — все пользователи."""
        p = CollectParams(chat_id=-1001)
        assert p.user_ids is None

    def test_user_ids_single(self):
        p = CollectParams(chat_id=-1001, user_ids=[111])
        assert p.user_ids == [111]

    def test_user_ids_multiple(self):
        p = CollectParams(chat_id=-1001, user_ids=[111, 222, 333])
        assert p.user_ids == [111, 222, 333]

    def test_no_user_id_field(self):
        """Старое поле user_id (int) не должно существовать."""
        p = CollectParams(chat_id=-1001)
        assert not hasattr(p, "user_id"), (
            "Поле user_id: int больше не должно существовать в CollectParams. "
            "Используй user_ids: List[int]."
        )

    def test_user_ids_is_list_type(self):
        p = CollectParams(chat_id=-1001, user_ids=[42])
        assert isinstance(p.user_ids, list)


# ──────────────────────────────────────────────────────────────────────────────
# Логика фильтрации — проверяем через симуляцию условия
# ──────────────────────────────────────────────────────────────────────────────

class TestUserIdFilterLogic:
    """
    Проверяет логику «sender_id not in params.user_ids».
    Имитирует условие из parser/api.py без реального Telegram.
    """

    @staticmethod
    def _should_skip(sender_id, user_ids):
        """Копия условия фильтра из collect_data()."""
        return bool(user_ids and sender_id not in user_ids)

    def test_no_filter_keeps_all(self):
        for uid in [111, 222, 333]:
            assert self._should_skip(uid, None) is False

    def test_filter_keeps_listed_users(self):
        user_ids = [111, 333]
        assert self._should_skip(111, user_ids) is False
        assert self._should_skip(333, user_ids) is False

    def test_filter_skips_unlisted_users(self):
        user_ids = [111]
        assert self._should_skip(222, user_ids) is True
        assert self._should_skip(999, user_ids) is True

    def test_empty_list_skips_nobody(self):
        """Пустой список user_ids = фильтр выключен (falsy)."""
        assert self._should_skip(111, []) is False

    def test_filter_multiple_users(self):
        user_ids = [10, 20, 30]
        assert self._should_skip(10, user_ids) is False
        assert self._should_skip(20, user_ids) is False
        assert self._should_skip(99, user_ids) is True


# ──────────────────────────────────────────────────────────────────────────────
# CollectParams — другие поля
# ──────────────────────────────────────────────────────────────────────────────

class TestCollectParamsDefaults:
    def test_required_field_chat_id(self):
        p = CollectParams(chat_id=-1001234567890)
        assert p.chat_id == -1001234567890

    def test_download_comments_default_false(self):
        p = CollectParams(chat_id=-1001)
        assert p.download_comments is False

    def test_re_download_default_false(self):
        p = CollectParams(chat_id=-1001)
        assert p.re_download is False

    def test_output_dir_default(self):
        p = CollectParams(chat_id=-1001)
        assert p.output_dir == "output"

    def test_all_fields_settable(self):
        from datetime import datetime, timezone
        p = CollectParams(
            chat_id          = -1001,
            topic_id         = 42,
            days_limit       = 7,
            date_from        = datetime(2024, 1, 1, tzinfo=timezone.utc),
            date_to          = datetime(2024, 1, 31, tzinfo=timezone.utc),
            media_filter     = ["photo", "video"],
            download_comments= True,
            user_ids         = [111, 222],
            output_dir       = "/tmp/output",
            re_download      = True,
            filter_expression= "has_media",
        )
        assert p.topic_id          == 42
        assert p.days_limit        == 7
        assert p.media_filter      == ["photo", "video"]
        assert p.download_comments is True
        assert p.user_ids          == [111, 222]
        assert p.re_download       is True
        assert p.filter_expression == "has_media"
