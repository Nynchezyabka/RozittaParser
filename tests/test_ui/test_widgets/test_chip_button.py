"""
tests/test_ui/test_widgets/test_chip_button.py

Тесты: ChipButton — media_type, active, toggled, click.
"""
import pytest
from core.ui_shared.widgets import ChipButton


class TestChipButton:
    def test_media_type_stored(self, qapp):
        chip = ChipButton("🎥", "Видео", media_type="video")
        assert chip.media_type == "video"

    def test_default_active(self, qapp):
        chip = ChipButton("🎥", "Видео", active=True)
        assert chip.isActive()

    def test_default_inactive(self, qapp):
        chip = ChipButton("🎥", "Видео", active=False)
        assert not chip.isActive()

    def test_set_active_toggles(self, qapp):
        chip = ChipButton("🎥", "Видео", active=True)
        chip.setActive(False)
        assert not chip.isActive()

    def test_set_active_emits_signal(self, qapp):
        chip = ChipButton("🎥", "Видео", active=False)
        received = []
        chip.toggled.connect(lambda v: received.append(v))
        chip.setActive(True)
        assert received == [True]

    def test_click_toggles(self, qapp):
        chip = ChipButton("🎥", "Видео", active=True)
        chip.mousePressEvent(None)
        assert not chip.isActive()
        chip.mousePressEvent(None)
        assert chip.isActive()

    def test_check_mark_visible_when_active(self, qapp):
        chip = ChipButton("🎥", "Видео", active=True)
        chip.show()
        assert chip._check_lbl.isVisible()

    def test_check_mark_hidden_when_inactive(self, qapp):
        chip = ChipButton("🎥", "Видео", active=False)
        chip.show()
        assert not chip._check_lbl.isVisible()
