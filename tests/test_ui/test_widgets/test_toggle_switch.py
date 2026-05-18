"""
tests/test_ui/test_widgets/test_toggle_switch.py

Тесты: ToggleSwitch — checked state, toggled signal, setChecked.
"""
import pytest
from PySide6.QtCore import Qt
from core.ui_shared.widgets import ToggleSwitch


class TestToggleSwitch:
    def test_default_unchecked(self, qapp):
        sw = ToggleSwitch()
        assert not sw.isChecked()

    def test_init_checked(self, qapp):
        sw = ToggleSwitch(checked=True)
        assert sw.isChecked()

    def test_set_checked_emits_signal(self, qapp):
        sw = ToggleSwitch()
        received = []
        sw.toggled.connect(lambda v: received.append(v))
        sw.setChecked(True)
        assert received == [True]

    def test_set_checked_no_double_emit(self, qapp):
        sw = ToggleSwitch(checked=True)
        received = []
        sw.toggled.connect(lambda v: received.append(v))
        sw.setChecked(True)
        assert received == []

    def test_toggle_back_and_forth(self, qapp):
        sw = ToggleSwitch()
        sw.setChecked(True)
        sw.setChecked(False)
        assert not sw.isChecked()

    def test_fixed_size(self, qapp):
        sw = ToggleSwitch()
        assert sw.width() == 40
        assert sw.height() == 20

    def test_mouse_click_toggles(self, qapp):
        sw = ToggleSwitch()
        sw.mousePressEvent(None)
        assert sw.isChecked()
        sw.mousePressEvent(None)
        assert not sw.isChecked()
