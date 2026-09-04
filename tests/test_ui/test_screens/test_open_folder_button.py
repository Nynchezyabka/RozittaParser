"""
tests/test_ui/test_screens/test_open_folder_button.py

Кнопка «Открыть папку» после выгрузки и перестроение ряда кнопок.

Главное, что здесь охраняется, — не сам факт появления кнопки, а размеры.
Панель шириной 308px не вмещает две подписанные кнопки: запуску нужно 223px,
«📂 Открыть папку» — 232 при 274 доступных. Поэтому после выгрузки кнопки
меняются ролями. Любая правка подписей или полей может незаметно обрезать
текст, поэтому ширины проверяются числами, а не на глаз.
"""
import os

import pytest

from config import AppConfig
from core.database import DBManager
import ui.main_window as mw


@pytest.fixture
def window(qapp):
    """Окно с базой в памяти; после теста закрывается."""
    win = mw.MainWindow(AppConfig(), DBManager(":memory:"))
    win.resize(1400, 900)
    win.show()
    qapp.processEvents()
    yield win, qapp
    win.close()


@pytest.fixture
def exported(tmp_path):
    """Путь к «созданному» файлу выгрузки."""
    path = tmp_path / "Канал_alltime.md"
    path.write_text("текст", encoding="utf-8")
    return str(path)


# ──────────────────────────────────────────────────────────────────────────────
# Появление и исчезновение
# ──────────────────────────────────────────────────────────────────────────────

class TestVisibility:
    def test_hidden_before_any_export(self, window):
        win, _ = window
        assert win._open_folder_btn.isVisible() is False

    def test_shown_after_export(self, window, exported):
        win, app = window
        win._on_export_complete([exported])
        app.processEvents()
        assert win._open_folder_btn.isVisible() is True

    def test_folder_taken_from_produced_file(self, window, exported):
        """
        Папка берётся из пути созданного файла, а не собирается заново из
        названия чата: вторая сборка через sanitize_filename разошлась бы
        с первой, и кнопка повела бы в несуществующую папку.
        """
        win, app = window
        win._on_export_complete([exported])
        app.processEvents()
        assert win._output_folder == os.path.dirname(exported)

    def test_empty_result_shows_nothing(self, window):
        """Интерфейс не обещает того, чего нет (правило #27)."""
        win, app = window
        win._on_export_complete([])
        app.processEvents()
        assert win._open_folder_btn.isVisible() is False
        assert win._output_folder is None

    def test_missing_folder_shows_nothing(self, window, tmp_path):
        win, app = window
        win._on_export_complete([str(tmp_path / "нет-такой" / "x.md")])
        app.processEvents()
        assert win._open_folder_btn.isVisible() is False

    def test_new_run_hides_stale_folder(self, window, exported):
        """Кнопка не должна вести к результату прошлого прогона."""
        win, app = window
        win._on_export_complete([exported])
        app.processEvents()
        win._set_btn_row_normal()
        app.processEvents()
        assert win._open_folder_btn.isVisible() is False


# ──────────────────────────────────────────────────────────────────────────────
# Размеры — ради них тест и написан
# ──────────────────────────────────────────────────────────────────────────────

class TestNothingIsClipped:
    def test_start_fits_before_export(self, window):
        win, _ = window
        btn = win._start_btn
        assert btn.width() >= btn.sizeHint().width()

    def test_both_fit_after_export(self, window, exported):
        win, app = window
        win._on_export_complete([exported])
        app.processEvents()
        for btn in (win._start_btn, win._open_folder_btn):
            assert btn.width() >= btn.sizeHint().width(), \
                f"{btn.text()!r}: {btn.width()} < {btn.sizeHint().width()}"

    def test_start_fits_again_after_reset(self, window, exported):
        win, app = window
        win._on_export_complete([exported])
        win._set_btn_row_normal()
        app.processEvents()
        btn = win._start_btn
        assert btn.width() >= btn.sizeHint().width()

    def test_buttons_share_one_row(self, window, exported):
        """Просьба была именно про один ряд, а не про строку снизу."""
        win, app = window
        win._on_export_complete([exported])
        app.processEvents()
        start, folder = win._start_btn, win._open_folder_btn
        assert start.mapTo(win, start.rect().topLeft()).y() == \
               folder.mapTo(win, folder.rect().topLeft()).y()
        assert start.height() == folder.height()

    def test_repeated_exports_do_not_accumulate(self, window, exported):
        """Растяжка двигается на ходу — она не должна копиться от прогона."""
        win, app = window
        for _ in range(3):
            win._on_export_complete([exported])
            app.processEvents()
        for btn in (win._start_btn, win._open_folder_btn):
            assert btn.width() >= btn.sizeHint().width()


# ──────────────────────────────────────────────────────────────────────────────
# Перестроение ряда
# ──────────────────────────────────────────────────────────────────────────────

class TestRowSwapsRoles:
    def test_start_shrinks_to_icon(self, window, exported):
        win, app = window
        assert win._start_btn.width() > 200
        win._on_export_complete([exported])
        app.processEvents()
        assert win._start_btn.text() == "▶"
        assert win._start_btn.width() == 40

    def test_shrunk_start_explains_itself(self, window, exported):
        """Значок без подписи обязан иметь подсказку, иначе он загадка."""
        win, app = window
        win._on_export_complete([exported])
        app.processEvents()
        assert win._start_btn.toolTip()

    def test_tooltip_gone_when_label_returns(self, window, exported):
        win, app = window
        win._on_export_complete([exported])
        win._set_btn_row_normal()
        app.processEvents()
        assert win._start_btn.toolTip() == ""
        assert "ЭКСПОРТ" in win._start_btn.text()

    def test_folder_button_is_the_wide_one(self, window, exported):
        win, app = window
        win._on_export_complete([exported])
        app.processEvents()
        assert win._open_folder_btn.width() > win._start_btn.width()

    def test_folder_button_fills_the_row(self, window, exported):
        """
        Растяжка обязана переехать на папку, а не остаться на запуске.

        Без этого кнопка встаёт по своей sizeHint, справа зияет пустота, и
        поймать это «больше ли папка запуска» нельзя — она больше и так.
        Поэтому проверяется правый край: он должен дойти до поля панели.
        """
        win, app = window
        win._on_export_complete([exported])
        app.processEvents()
        folder = win._open_folder_btn
        wrap = folder.parentWidget()
        right_margin = wrap.layout().contentsMargins().right()
        folder_right = folder.mapTo(wrap, folder.rect().topRight()).x()
        assert folder_right >= wrap.width() - right_margin - 1, \
            f"справа осталось {wrap.width() - right_margin - folder_right}px пустоты"


# ──────────────────────────────────────────────────────────────────────────────
# Клик
# ──────────────────────────────────────────────────────────────────────────────

class TestClick:
    def test_click_opens_the_folder(self, window, exported, monkeypatch):
        """
        Проверяем кликом, а не вызовом метода: обработчик подключён к
        clicked, и тест обязан идти тем же путём, что человек.
        """
        win, app = window
        opened = []
        monkeypatch.setattr(
            mw.QDesktopServices, "openUrl",
            staticmethod(lambda url: opened.append(url.toLocalFile()) or True),
        )
        win._on_export_complete([exported])
        app.processEvents()
        win._open_folder_btn.click()
        app.processEvents()
        assert opened == [os.path.dirname(exported).replace("\\", "/")]

    def test_click_on_vanished_folder_hides_button(self, window, exported,
                                                   monkeypatch, tmp_path):
        """Папку удалили между выгрузкой и кликом — кнопка не врёт дальше."""
        win, app = window
        monkeypatch.setattr(
            mw.QDesktopServices, "openUrl", staticmethod(lambda url: True))
        win._on_export_complete([exported])
        app.processEvents()
        win._output_folder = str(tmp_path / "исчезла")
        win._open_folder_btn.click()
        app.processEvents()
        assert win._open_folder_btn.isVisible() is False
