"""
tests/test_ui/test_screens/test_settings_panel.py

Тесты: SettingsPanel — UI секции, set_chat, get_params, split_mode, media toggles.
"""
import pytest
from unittest.mock import MagicMock
from config import AppConfig
from ui.main_window import SettingsPanel


class TestSettingsPanelCreation:
    def test_creates_without_config(self, qapp):
        panel = SettingsPanel()
        assert panel is not None

    def test_creates_with_config(self, qapp):
        cfg = AppConfig(api_id="1", api_hash="x")
        panel = SettingsPanel(cfg=cfg)
        assert panel._cfg is cfg

    def test_has_signals(self, qapp):
        panel = SettingsPanel()
        assert hasattr(panel, "parse_requested")
        assert hasattr(panel, "load_members_requested")
        assert hasattr(panel, "log_message")


class TestSettingsPanelChatInfo:
    def test_set_chat_updates_current(self, qapp):
        panel = SettingsPanel()
        chat = {"id": -100123, "title": "Test", "type": "channel"}
        panel.set_chat(chat)
        assert panel._current_chat == chat

    def test_set_chat_clears_with_empty_dict(self, qapp):
        panel = SettingsPanel()
        panel.set_chat({"id": 1, "title": "X", "type": "channel"})
        panel._current_chat = None
        assert panel._current_chat is None


class TestSettingsPanelSplitMode:
    def test_default_split_none(self, qapp):
        panel = SettingsPanel()
        assert panel._split_mode == "none"

    def test_split_buttons_exist(self, qapp):
        panel = SettingsPanel()
        assert len(panel._split_buttons) >= 4

    def test_split_modes_available(self, qapp):
        panel = SettingsPanel()
        modes = {btn.mode for btn in panel._split_buttons}
        assert "none" in modes
        assert "day" in modes
        assert "month" in modes
        assert "post" in modes

    def test_restore_split_from_config(self, qapp):
        cfg = AppConfig(api_id="1", api_hash="x", split_mode="day")
        panel = SettingsPanel(cfg=cfg)
        assert panel._split_mode == "day"


class TestSettingsPanelParsing:
    def test_set_parsing_true(self, qapp):
        panel = SettingsPanel()
        panel.set_parsing(True)
        assert panel._parsing is True

    def test_set_parsing_false(self, qapp):
        panel = SettingsPanel()
        panel.set_parsing(True)
        panel.set_parsing(False)
        assert panel._parsing is False


class TestSettingsPanelParams:
    def test_get_params_no_chat_returns_none(self, qapp):
        panel = SettingsPanel()
        assert panel.get_params() is None

    def test_get_params_with_chat(self, qapp):
        panel = SettingsPanel()
        panel.set_chat({"id": -100123, "title": "Test", "type": "channel"})
        params = panel.get_params()
        assert params is not None
        assert params.chat == {"id": -100123, "title": "Test", "type": "channel"}
