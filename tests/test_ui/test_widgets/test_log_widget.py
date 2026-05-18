"""
tests/test_ui/test_widgets/test_log_widget.py

Тесты: LogWidget — append, levels, clear, filter.
"""
import pytest
from core.ui_shared.widgets import LogWidget


class TestLogWidget:
    def test_append_stores_entry(self, qapp):
        w = LogWidget()
        w.append("test message", "info")
        assert len(w._all_entries) == 1

    def test_append_info(self, qapp):
        w = LogWidget()
        w.append_info("info msg")
        assert w._all_entries[0][1] == "info msg"
        assert w._all_entries[0][2] == "info"

    def test_append_error(self, qapp):
        w = LogWidget()
        w.append_error("error msg")
        assert w._all_entries[0][2] == "error"

    def test_append_success(self, qapp):
        w = LogWidget()
        w.append_success("ok")
        assert w._all_entries[0][2] == "success"

    def test_append_warning(self, qapp):
        w = LogWidget()
        w.append_warning("warn")
        assert w._all_entries[0][2] == "warning"

    def test_clear_removes_all(self, qapp):
        w = LogWidget()
        w.append_info("a")
        w.append_error("b")
        w.clear()
        assert len(w._all_entries) == 0

    def test_multiple_entries(self, qapp):
        w = LogWidget()
        for i in range(10):
            w.append_info(f"msg {i}")
        assert len(w._all_entries) == 10

    def test_default_filter_all(self, qapp):
        w = LogWidget()
        assert w._current_filter == "all"
