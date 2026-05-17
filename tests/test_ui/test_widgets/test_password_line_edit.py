"""
tests/test_ui/test_widgets/test_password_line_edit.py

Тесты: PasswordLineEdit — text, setText, echo mode, placeholder.
"""
import pytest
from PySide6.QtWidgets import QLineEdit
from core.ui_shared.widgets import PasswordLineEdit


class TestPasswordLineEdit:
    def test_default_empty(self, qapp):
        w = PasswordLineEdit()
        assert w.text() == ""

    def test_placeholder_set(self, qapp):
        w = PasswordLineEdit(placeholder="введите hash")
        assert w._edit.placeholderText() == "введите hash"

    def test_set_text(self, qapp):
        w = PasswordLineEdit()
        w.setText("secret123")
        assert w.text() == "secret123"

    def test_echo_mode_default_password(self, qapp):
        w = PasswordLineEdit()
        assert w._edit.echoMode() == QLineEdit.EchoMode.Password

    def test_toggle_shows_text(self, qapp):
        w = PasswordLineEdit()
        w._toggle_btn.setChecked(True)
        assert w._edit.echoMode() == QLineEdit.EchoMode.Normal

    def test_toggle_hides_text(self, qapp):
        w = PasswordLineEdit()
        w._toggle_btn.setChecked(True)
        w._toggle_btn.setChecked(False)
        assert w._edit.echoMode() == QLineEdit.EchoMode.Password

    def test_text_changed_signal(self, qapp):
        w = PasswordLineEdit()
        received = []
        w.textChanged.connect(lambda t: received.append(t))
        w.setText("abc")
        assert "abc" in received

    def test_set_read_only(self, qapp):
        w = PasswordLineEdit()
        w.setReadOnly(True)
        assert w._edit.isReadOnly()
