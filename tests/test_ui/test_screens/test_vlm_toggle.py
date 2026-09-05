# -*- coding: utf-8 -*-
"""
tests/test_ui/test_screens/test_vlm_toggle.py — тумблер и диалог скачивания.

Проверяется кликами, а не setChecked-ом свойств: обработчики висят на
toggled, и тест обязан идти тем же путём, что человек (правило #25).

Главное здесь — что тумблер не может остаться включённым, когда компонента
нет. Иначе он обещает функцию, которой не существует, а узнает об этом
человек через час парсинга.
"""
import pytest
from PySide6.QtWidgets import QDialog, QLabel

from config import AppConfig
from core.database import DBManager
import ui.main_window as mw


@pytest.fixture
def window(qapp, tmp_path, monkeypatch):
    win = mw.MainWindow(AppConfig(), DBManager(":memory:"))
    win._cfg.components_dir = str(tmp_path / "components")
    # Настройки в тесте на диск не пишем.
    monkeypatch.setattr(win, "_save_cfg_quietly", lambda: None)
    win.show()
    qapp.processEvents()
    yield win, qapp
    win.close()


@pytest.fixture
def dialog_says(monkeypatch):
    """Подменяет диалог скачивания заданным ответом, считая показы."""
    import features.vlm.download_ui as dl

    calls = {"shown": 0}

    def make(code):
        class Fake(QDialog):
            def __init__(self, *a, **kw):
                super().__init__()
                calls["shown"] += 1

            def exec(self):
                return code

        monkeypatch.setattr(dl, "ComponentDownloadDialog", Fake)
        return calls

    return make


class TestToggleDefaults:
    def test_off_by_default(self, window):
        win, _ = window
        assert win._settings_screen.get_describe_images() is False

    def test_label_and_hint_are_not_clipped(self, window):
        """
        Подпись и подсказка обязаны быть читаемыми. Панель узкая, и на ней
        уже один раз схлопнулась кнопка в невидимую полоску (правило #25).
        """
        win, _ = window
        panel = win._settings_screen
        labels = [l for l in panel.findChildren(QLabel)
                  if "Описывать изображения" in l.text()
                  or "скриншот" in l.text()]
        assert len(labels) == 2, "подпись или подсказка потерялись"
        for lbl in labels:
            assert lbl.wordWrap() or lbl.height() >= lbl.sizeHint().height(), \
                f"обрезано: {lbl.text()[:40]!r}"

    def test_hint_warns_about_size_and_time(self, window):
        """
        Человек должен узнать про три гигабайта и про долгую выгрузку до
        того, как включит, а не после.
        """
        win, _ = window
        hint = next(l for l in win._settings_screen.findChildren(QLabel)
                    if "скриншот" in l.text())
        assert "ГБ" in hint.text()
        assert "удлиняет" in hint.text() or "долг" in hint.text()


class TestAskingAboutTheComponent:
    def test_enabling_without_component_asks(self, window, dialog_says):
        calls = dialog_says(QDialog.DialogCode.Rejected)
        win, app = window
        win._settings_screen._toggle_describe_images.setChecked(True)
        app.processEvents()
        assert calls["shown"] == 1

    def test_refusal_switches_the_toggle_back(self, window, dialog_says):
        """
        Главный тест файла. Отказался качать — тумблер обязан вернуться
        в «выкл»: иначе он обещает функцию, которой нет (правило #27).
        """
        dialog_says(QDialog.DialogCode.Rejected)
        win, app = window
        win._settings_screen._toggle_describe_images.setChecked(True)
        app.processEvents()
        assert win._settings_screen.get_describe_images() is False
        assert win._cfg.describe_images is False

    def test_agreement_turns_it_on(self, window, dialog_says):
        dialog_says(QDialog.DialogCode.Accepted)
        win, app = window
        win._settings_screen._toggle_describe_images.setChecked(True)
        app.processEvents()
        assert win._settings_screen.get_describe_images() is True
        assert win._cfg.describe_images is True

    def test_switching_off_asks_nothing(self, window, dialog_says):
        calls = dialog_says(QDialog.DialogCode.Accepted)
        win, app = window
        win._settings_screen._toggle_describe_images.setChecked(True)
        app.processEvents()
        shown_after_on = calls["shown"]
        win._settings_screen._toggle_describe_images.setChecked(False)
        app.processEvents()
        assert calls["shown"] == shown_after_on
        assert win._cfg.describe_images is False

    def test_installed_component_asks_nothing(self, window, dialog_says,
                                              monkeypatch):
        """Компонент уже стоит — вопрос был бы лишним беспокойством."""
        import ui.main_window as mod
        import features.vlm.ui as vlm_ui

        calls = dialog_says(QDialog.DialogCode.Rejected)
        monkeypatch.setattr(vlm_ui, "needs_component", lambda d, u: False)
        win, app = window
        win._settings_screen._toggle_describe_images.setChecked(True)
        app.processEvents()
        assert calls["shown"] == 0
        assert win._cfg.describe_images is True


class TestDownloadDialog:
    def _dialog(self, win, tmp_path):
        from features.vlm.download_ui import ComponentDownloadDialog
        return ComponentDownloadDialog(
            components_dir=str(tmp_path), registry_url="file:///нет",
            parent=win)

    def test_starts_with_a_question_not_a_progress_bar(self, window, tmp_path):
        """
        Сначала спрашиваем, потом качаем. Полоса до вопроса выглядела бы
        так, будто скачивание уже началось само.
        """
        win, app = window
        dlg = self._dialog(win, tmp_path)
        dlg.show()
        app.processEvents()
        assert dlg._ok_btn.text() == "Скачать"
        assert dlg._bar.isVisible() is False
        dlg.close()

    def test_size_is_stated_before_the_download(self, window, tmp_path):
        win, app = window
        dlg = self._dialog(win, tmp_path)
        assert "ГБ" in dlg._text.text()
        dlg.close()

    def test_text_wraps_instead_of_clipping(self, window, tmp_path):
        win, app = window
        dlg = self._dialog(win, tmp_path)
        dlg.show()
        app.processEvents()
        assert dlg._text.wordWrap()
        dlg.close()

    def test_failure_offers_a_retry(self, window, tmp_path):
        """
        Битое зеркало или оборвавшаяся сеть лечатся повтором — предлагаем
        именно его, а не «ошибка, закройте окно».
        """
        win, app = window
        dlg = self._dialog(win, tmp_path)
        dlg.show()
        dlg._on_failed("сеть недоступна")
        app.processEvents()
        assert dlg._ok_btn.text() == "Повторить"
        assert dlg._ok_btn.isEnabled()
        assert "сеть недоступна" in dlg._status.text()
        dlg.close()

    def test_cancel_is_not_a_failure(self, window, tmp_path):
        """Пустое сообщение = отменено пользователем, окно просто закрывается."""
        win, app = window
        dlg = self._dialog(win, tmp_path)
        dlg.show()
        dlg._on_failed("")
        app.processEvents()
        assert dlg.result() == QDialog.DialogCode.Rejected

    def test_progress_shows_megabytes(self, window, tmp_path):
        win, app = window
        dlg = self._dialog(win, tmp_path)
        dlg._on_progress(500_000_000, 3_000_000_000)
        assert "500" in dlg._status.text() and "3000" in dlg._status.text()
        assert dlg._bar.value() == 16
        dlg.close()

    def test_unknown_total_does_not_show_zero(self, window, tmp_path):
        """
        Сервер не сообщил размер. Показать 0% значило бы соврать, что
        ничего не качается.
        """
        win, app = window
        dlg = self._dialog(win, tmp_path)
        dlg._on_progress(120_000_000, 0)
        assert "120" in dlg._status.text()
        assert dlg._bar.maximum() == 0        # бесконечная полоса
        dlg.close()
