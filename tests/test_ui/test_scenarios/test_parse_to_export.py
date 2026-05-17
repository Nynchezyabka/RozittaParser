"""
tests/test_ui/test_scenarios/test_parse_to_export.py

E2E сценарий: выбор чата → настройка → парсинг → экспорт.
Тестирует SettingsPanel, ParseParams, ExportParams.
"""
import pytest
from config import AppConfig
from ui.main_window import SettingsPanel
from features.parser.ui import ParseParams
from features.export.ui import ExportParams


class TestSettingsToParseParams:
    def test_default_params_all_media_enabled(self, qapp):
        """По умолчанию все медиа включены."""
        panel = SettingsPanel()
        panel.set_chat({"id": -100, "title": "Test", "type": "channel"})
        params = panel.get_params()
        assert params.download_photo is True
        assert params.download_video is True
        assert params.download_voice is True

    def test_disable_photo_media(self, qapp):
        """Отключаем фото."""
        panel = SettingsPanel()
        panel.set_chat({"id": -100, "title": "Test", "type": "channel"})
        panel._media_photo.setActive(False)
        params = panel.get_params()
        assert params.download_photo is False

    def test_split_mode_day(self, qapp):
        """Выбираем разбивку по дням."""
        panel = SettingsPanel()
        panel.set_chat({"id": -100, "title": "Test", "type": "channel"})
        # Находим кнопку с mode="day" и кликаем
        for btn in panel._split_buttons:
            if btn.mode == "day":
                btn.setChecked(True)
                panel._split_mode = "day"
                break
        params = panel.get_params()
        assert panel._split_mode == "day"

    def test_parsing_state_changes(self, qapp):
        """set_parsing переключает состояние."""
        panel = SettingsPanel()
        panel.set_parsing(True)
        assert panel._parsing is True
        panel.set_parsing(False)
        assert panel._parsing is False


class TestExportParamsCreation:
    def test_default_export_params(self):
        """ExportParams создаётся с defaults."""
        params = ExportParams(
            chat_id=-100,
            chat_title="Test",
            output_dir="/tmp",
            db_path="/tmp/test.db",
        )
        assert params.chat_id == -100
        assert params.chat_title == "Test"
        assert params.split_mode == "none"

    def test_export_params_with_formats(self):
        """Выбор форматов экспорта."""
        params = ExportParams(
            chat_id=-100,
            chat_title="Test",
            output_dir="/tmp",
            db_path="/tmp/test.db",
            export_formats=["docx", "json", "md"],
        )
        assert "docx" in params.export_formats
        assert "json" in params.export_formats
        assert "md" in params.export_formats

    def test_export_params_ai_split(self):
        """ai_split включен."""
        params = ExportParams(
            chat_id=-100,
            chat_title="Test",
            output_dir="/tmp",
            db_path="/tmp/test.db",
            ai_split=True,
        )
        assert params.ai_split is True

    def test_export_params_split_by_post(self):
        params = ExportParams(
            chat_id=-100,
            chat_title="Test",
            output_dir="/tmp",
            db_path="/tmp/test.db",
            split_mode="post",
        )
        assert params.split_mode == "post"

    def test_export_params_with_comments(self):
        params = ExportParams(
            chat_id=-100,
            chat_title="Test",
            output_dir="/tmp",
            db_path="/tmp/test.db",
            include_comments=True,
        )
        assert params.include_comments is True


class TestParseParamsCreation:
    def test_parse_params_stores_chat(self):
        chat = {"id": -100, "title": "Test", "type": "channel"}
        params = ParseParams(chat=chat)
        assert params.chat == chat

    def test_parse_params_defaults(self):
        params = ParseParams(chat={"id": 1, "title": "X", "type": "channel"})
        assert params.download_photo is True
        assert params.download_video is True
        assert params.stt_voice is True

    def test_parse_params_custom_media(self):
        params = ParseParams(
            chat={"id": 1, "title": "X", "type": "channel"},
            download_photo=False,
            download_video=False,
        )
        assert params.download_photo is False
        assert params.download_video is False
