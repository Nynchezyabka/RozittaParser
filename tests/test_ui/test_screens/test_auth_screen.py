"""
tests/test_ui/test_screens/test_auth_screen.py

Тесты: AuthScreen — UI элементы, сигналы, ввод данных, прокси.
"""
import pytest
from unittest.mock import patch, MagicMock
from config import AppConfig
from features.auth.ui import AuthScreen, AuthWorker


class TestAuthScreenUI:
    def test_creates_with_config(self, qapp):
        cfg = AppConfig(api_id="123", api_hash="abc", phone="+7999")
        screen = AuthScreen(cfg)
        assert screen._api_id.text() == "123"
        assert screen._api_hash.text() == "abc"
        assert screen._phone.text() == "+7999"

    def test_api_id_empty_by_default(self, qapp):
        screen = AuthScreen(AppConfig())
        assert screen._api_id.text() == ""

    def test_phone_placeholder(self, qapp):
        screen = AuthScreen(AppConfig())
        assert screen._phone.placeholderText() == "+79001234567"

    def test_api_hash_is_password_field(self, qapp):
        screen = AuthScreen(AppConfig())
        assert screen._api_hash._edit.echoMode() != 0  # not Normal

    def test_proxy_toggle_exists(self, qapp):
        screen = AuthScreen(AppConfig())
        assert hasattr(screen, "_proxy_toggle")

    def test_proxy_toggle_default_off(self, qapp):
        screen = AuthScreen(AppConfig())
        assert not screen._proxy_toggle.isChecked()

    def test_proxy_toggle_enabled_in_config(self, qapp):
        cfg = AppConfig(proxy_enabled=True)
        screen = AuthScreen(cfg)
        assert screen._proxy_toggle.isChecked()

    def test_proxy_host_default(self, qapp):
        screen = AuthScreen(AppConfig())
        assert screen._proxy_host_auth.text() == "127.0.0.1"

    def test_proxy_port_default(self, qapp):
        screen = AuthScreen(AppConfig())
        assert screen._proxy_port_auth.value() == 9050

    def test_proxy_port_custom(self, qapp):
        cfg = AppConfig(proxy_port=1080)
        screen = AuthScreen(cfg)
        assert screen._proxy_port_auth.value() == 1080

    def test_has_signals(self, qapp):
        screen = AuthScreen(AppConfig())
        assert hasattr(screen, "auth_complete")
        assert hasattr(screen, "log_message")
        assert hasattr(screen, "character_state")
        assert hasattr(screen, "character_tip")

    def test_set_api_id_updates_field(self, qapp):
        screen = AuthScreen(AppConfig())
        screen._api_id.setText("99999")
        assert screen._api_id.text() == "99999"

    def test_set_phone_updates_field(self, qapp):
        screen = AuthScreen(AppConfig())
        screen._phone.setText("+15551234567")
        assert screen._phone.text() == "+15551234567"


class TestAuthWorkerSignals:
    def test_has_required_signals(self):
        assert hasattr(AuthWorker, "log_message")
        assert hasattr(AuthWorker, "auth_complete")
        assert hasattr(AuthWorker, "error")
        assert hasattr(AuthWorker, "request_input")
        assert hasattr(AuthWorker, "character_state")

    def test_worker_init_with_config(self):
        cfg = AppConfig(api_id="123", api_hash="abc")
        worker = AuthWorker(cfg)
        assert worker._cfg is cfg

    def test_provide_input(self):
        worker = AuthWorker(AppConfig())
        worker.provide_input("test_code")
        assert worker._input_value == "test_code"
        assert worker._input_ready is True
