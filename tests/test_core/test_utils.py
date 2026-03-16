"""
tests/test_core/test_utils.py

Тесты: finalize_telegram_id, sanitize_filename, is_image_path, DownloadTracker.
"""
import os
import pytest
from core.utils import (
    finalize_telegram_id,
    sanitize_filename,
    is_image_path,
    DownloadTracker,
    TelegramEntityType,
)


# ──────────────────────────────────────────────────────────────────────────────
# finalize_telegram_id
# ──────────────────────────────────────────────────────────────────────────────

class TestFinalizeTelegramId:
    def test_channel_positive(self):
        """Положительный ID канала → добавляется -100 префикс."""
        assert finalize_telegram_id(2882674903, TelegramEntityType.CHANNEL) == -1002882674903

    def test_channel_already_normalized(self):
        """Уже нормализованный ID канала не меняется."""
        assert finalize_telegram_id(-1002882674903, TelegramEntityType.CHANNEL) == -1002882674903

    def test_user_positive(self):
        """ID пользователя всегда положительный."""
        assert finalize_telegram_id(123456, TelegramEntityType.USER) == 123456

    def test_user_negative_input(self):
        """Отрицательный ID пользователя → abs()."""
        assert finalize_telegram_id(-123456, TelegramEntityType.USER) == 123456

    def test_chat_returns_negative(self):
        """Обычная группа → ID с одиночным минусом."""
        assert finalize_telegram_id(456789, TelegramEntityType.CHAT) == -456789

    def test_chat_already_negative(self):
        """Уже отрицательный ID группы остаётся отрицательным."""
        assert finalize_telegram_id(-456789, TelegramEntityType.CHAT) == -456789

    def test_channel_string_input(self):
        """Принимает строку-число."""
        assert finalize_telegram_id("2882674903", TelegramEntityType.CHANNEL) == -1002882674903

    def test_zero_raises(self):
        with pytest.raises(ValueError):
            finalize_telegram_id(0)

    def test_non_numeric_raises(self):
        with pytest.raises(TypeError):
            finalize_telegram_id("не число")

    def test_default_entity_type_is_channel(self):
        """По умолчанию используется CHANNEL."""
        assert finalize_telegram_id(2882674903) == -1002882674903


# ──────────────────────────────────────────────────────────────────────────────
# sanitize_filename
# ──────────────────────────────────────────────────────────────────────────────

class TestSanitizeFilename:
    def test_removes_forbidden_chars(self):
        result = sanitize_filename('file/name:test*?"<>|ok')
        assert "/" not in result
        assert ":" not in result
        assert "*" not in result

    def test_none_returns_chat(self):
        assert sanitize_filename(None) == "chat"

    def test_empty_returns_chat(self):
        assert sanitize_filename("") == "chat"

    def test_truncates_to_max_length(self):
        long = "a" * 200
        result = sanitize_filename(long, max_length=120)
        assert len(result) <= 120

    def test_normal_name_unchanged(self):
        assert sanitize_filename("Мой чат 2024") == "Мой чат 2024"


# ──────────────────────────────────────────────────────────────────────────────
# is_image_path
# ──────────────────────────────────────────────────────────────────────────────

class TestIsImagePath:
    @pytest.mark.parametrize("path", [
        "photo.jpg", "pic.JPEG", "img.png", "anim.gif", "snap.webp", "bmp.bmp",
    ])
    def test_image_extensions(self, path):
        assert is_image_path(path) is True

    @pytest.mark.parametrize("path", [
        "video.mp4", "audio.ogg", "doc.docx", "file.txt",
    ])
    def test_non_image_extensions(self, path):
        assert is_image_path(path) is False


# ──────────────────────────────────────────────────────────────────────────────
# DownloadTracker
# ──────────────────────────────────────────────────────────────────────────────

class TestDownloadTracker:
    def test_not_downloaded_initially(self, tmp_path):
        tracker = DownloadTracker(str(tmp_path), "TestChat", -1001234567890)
        assert tracker.is_downloaded(42) is False

    def test_mark_and_check(self, tmp_path):
        tracker = DownloadTracker(str(tmp_path), "TestChat", -1001234567890)
        tracker.mark_downloaded(100)
        assert tracker.is_downloaded(100) is True
        assert tracker.is_downloaded(101) is False

    def test_save_and_reload(self, tmp_path):
        chat_id = -1001234567890
        tracker = DownloadTracker(str(tmp_path), "TestChat", chat_id)
        tracker.mark_downloaded(10)
        tracker.mark_downloaded(20)
        tracker.save()

        tracker2 = DownloadTracker(str(tmp_path), "TestChat", chat_id)
        assert tracker2.is_downloaded(10) is True
        assert tracker2.is_downloaded(20) is True
        assert tracker2.is_downloaded(99) is False

    def test_clear_removes_ids(self, tmp_path):
        tracker = DownloadTracker(str(tmp_path), "TestChat", -1001234567890)
        tracker.mark_downloaded(5)
        tracker.save()
        tracker.clear()
        assert tracker.is_downloaded(5) is False

    def test_count_property(self, tmp_path):
        tracker = DownloadTracker(str(tmp_path), "TestChat", -1001234567890)
        assert tracker.count == 0
        tracker.mark_downloaded(1)
        tracker.mark_downloaded(2)
        assert tracker.count == 2
