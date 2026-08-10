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

    def test_active_label_is_orange(self, qapp):
        """Активное состояние передаётся цветом — как у MediaButton."""
        from core.ui_shared.styles import ACCENT_ORANGE

        chip = ChipButton("🎥", "Видео", active=True)
        chip.show()
        assert ACCENT_ORANGE in chip._text_lbl.styleSheet()

    def test_inactive_label_is_not_orange(self, qapp):
        from core.ui_shared.styles import ACCENT_ORANGE

        chip = ChipButton("🎥", "Видео", active=False)
        chip.show()
        assert ACCENT_ORANGE not in chip._text_lbl.styleSheet()

    def test_no_check_mark_widget(self, qapp):
        """Галочка убрана: два способа сказать «выбрано» на одном экране."""
        chip = ChipButton("🎥", "Видео", active=True)
        assert not hasattr(chip, "_check_lbl")
