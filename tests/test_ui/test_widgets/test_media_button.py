"""
tests/test_ui/test_widgets/test_media_button.py

Тесты: MediaButton — media_type, active, toggled.
"""
import pytest
from core.ui_shared.widgets import MediaButton


class TestMediaButton:
    def test_media_type_stored(self, qapp):
        btn = MediaButton("📷", "Фото", media_type="photo")
        assert btn.media_type == "photo"

    def test_default_active(self, qapp):
        btn = MediaButton("📷", "Фото", active=True)
        assert btn.isActive()

    def test_default_inactive(self, qapp):
        btn = MediaButton("📷", "Фото", active=False)
        assert not btn.isActive()

    def test_set_active_toggle(self, qapp):
        btn = MediaButton("📷", "Фото", active=True)
        btn.setActive(False)
        assert not btn.isActive()
        btn.setActive(True)
        assert btn.isActive()

    def test_checkable(self, qapp):
        btn = MediaButton("📷", "Фото")
        assert btn.isCheckable()

    def test_icon_label(self, qapp):
        btn = MediaButton("📷", "Фото")
        assert btn._icon_lbl.text() == "📷"

    def test_text_label(self, qapp):
        btn = MediaButton("📷", "Фото")
        assert btn._text_lbl.text() == "Фото"

    def test_empty_media_type(self, qapp):
        btn = MediaButton("📄", "Файл")
        assert btn.media_type == ""
