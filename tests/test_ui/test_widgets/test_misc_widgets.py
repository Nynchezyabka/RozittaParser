"""
tests/test_ui/test_widgets/test_misc_widgets.py

Тесты: FilterButton, UserTag, StepperWidget, SplitModeButton.
"""
import pytest
from core.ui_shared.widgets import FilterButton, UserTag, StepperWidget, SplitModeButton


class TestFilterButton:
    def test_filter_key_stored(self, qapp):
        btn = FilterButton("Все", filter_key="all")
        assert btn.filter_key == "all"

    def test_custom_filter_key(self, qapp):
        btn = FilterButton("Ошибки", filter_key="error")
        assert btn.filter_key == "error"

    def test_checkable(self, qapp):
        btn = FilterButton("Все")
        assert btn.isCheckable()

    def test_text_matches_label(self, qapp):
        btn = FilterButton("Инфо", filter_key="info")
        assert btn.text() == "Инфо"


class TestUserTag:
    def test_user_id(self, qapp):
        tag = UserTag("@alice", user_id=42)
        assert tag.user_id == 42

    def test_is_all_flag(self, qapp):
        tag = UserTag("Все", is_all=True)
        assert tag.is_all

    def test_not_is_all_by_default(self, qapp):
        tag = UserTag("@bob")
        assert not tag.is_all

    def test_text_contains_username(self, qapp):
        tag = UserTag("@alice", user_id=1)
        assert "@alice" in tag.text()

    def test_all_tag_has_checkmark(self, qapp):
        tag = UserTag("Все", is_all=True)
        assert "✓" in tag.text()

    def test_user_tag_has_icon(self, qapp):
        tag = UserTag("@bob", user_id=2)
        assert "👤" in tag.text()

    def test_selected_init(self, qapp):
        tag = UserTag("@alice", selected=True)
        assert tag.isChecked()


class TestStepperWidget:
    def test_default_steps(self, qapp):
        sw = StepperWidget()
        assert len(sw._step_labels) == 4

    def test_default_active_zero(self, qapp):
        sw = StepperWidget()
        assert sw.current_step() == 0

    def test_set_active(self, qapp):
        sw = StepperWidget()
        sw.set_active(2)
        assert sw.current_step() == 2

    def test_custom_steps(self, qapp):
        sw = StepperWidget(steps=["Step A", "Step B", "Step C"])
        assert len(sw._step_labels) == 3

    def test_set_active_last_step(self, qapp):
        sw = StepperWidget()
        sw.set_active(3)
        assert sw.current_step() == 3


class TestSplitModeButton:
    def test_mode_property(self, qapp):
        btn = SplitModeButton("📄", "Единый", mode="none")
        assert btn.mode == "none"

    def test_day_mode(self, qapp):
        btn = SplitModeButton("📅", "Дни", mode="day")
        assert btn.mode == "day"

    def test_month_mode(self, qapp):
        btn = SplitModeButton("📆", "Месяцы", mode="month")
        assert btn.mode == "month"

    def test_post_mode(self, qapp):
        btn = SplitModeButton("📝", "Посты", mode="post")
        assert btn.mode == "post"

    def test_checkable(self, qapp):
        btn = SplitModeButton("📄", "Единый", mode="none")
        assert btn.isCheckable()

    def test_active_init(self, qapp):
        btn = SplitModeButton("📄", "Единый", mode="none", active=True)
        assert btn.isChecked()
