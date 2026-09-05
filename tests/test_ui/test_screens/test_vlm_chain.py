# -*- coding: utf-8 -*-
"""
tests/test_ui/test_screens/test_vlm_chain.py — место описаний в цепочке.

Порядок парсинг → STT → описания → экспорт выглядит мелочью, но если
описания лягут в БД после сборки документа, выгрузка выйдет без них и
человеку придётся гонять всё заново. На большом архиве это часы.

Здесь проверяется именно очерёдность и то, что необязательная функция не
может утащить за собой обязательную.
"""
import pytest

from config import AppConfig
from core.database import DBManager
import ui.main_window as mw


class Result:
    """CollectResult в объёме, который нужен цепочке."""
    chat_id = -1001
    chat_title = "Канал"
    db_path = ""


@pytest.fixture
def window(qapp, tmp_path):
    win = mw.MainWindow(AppConfig(), DBManager(":memory:"))
    win._cfg.output_dir = str(tmp_path)
    yield win
    win.close()


@pytest.fixture
def calls(window, monkeypatch):
    """Записывает порядок вызовов вместо настоящей работы."""
    order = []
    monkeypatch.setattr(window, "_run_export",
                        lambda r: order.append("export"))
    monkeypatch.setattr(window, "_start_worker",
                        lambda w: order.append("vlm-worker"))
    return order


class TestOrder:
    def test_disabled_goes_straight_to_export(self, window, calls):
        """Выключенная функция не должна ничего добавлять в цепочку."""
        window._cfg.describe_images = False
        window._on_stt_finished(Result())
        assert calls == ["export"]

    def test_enabled_describes_before_export(self, window, calls):
        """
        Главный тест файла: описания идут ПЕРЕД экспортом.

        Экспорт запускается по сигналу finished воркера, поэтому в момент
        _on_stt_finished его в списке ещё нет — и это правильно.
        """
        window._cfg.describe_images = True
        window._on_stt_finished(Result())
        assert calls == ["vlm-worker"]
        assert "export" not in calls

    def test_export_runs_after_the_worker_finishes(self, window, calls):
        window._cfg.describe_images = True
        window._last_collect_result = Result()
        window._on_vlm_finished_slot()
        assert calls == ["export"]

    def test_missing_chat_id_does_not_stall_the_chain(self, window, calls):
        """
        Без chat_id описывать нечего, но выгрузку это отменять не должно:
        застрявшая навсегда цепочка хуже документа без описаний.
        """
        window._cfg.describe_images = True

        class NoId:
            chat_id = None

        window._on_stt_finished(NoId())
        assert calls == ["export"]


class TestFailureDoesNotCancelExport:
    def test_error_is_logged_not_fatal(self, window, monkeypatch):
        """
        Документ без описаний — всё ещё документ, а потерять час парсинга
        из-за необязательной функции человек не простит. Так же ведёт себя
        ошибка STT.
        """
        logged = []
        monkeypatch.setattr(window._log, "append_error", logged.append)
        window._on_vlm_error("движок недоступен")
        assert logged and "экспорт продолжается" in logged[0]

    def test_export_still_happens_after_an_error(self, window, calls):
        window._cfg.describe_images = True
        window._last_collect_result = Result()
        window._on_vlm_error("что-то пошло не так")
        window._on_vlm_finished_slot()
        assert calls == ["export"]


class TestConfig:
    def test_off_by_default(self):
        """
        Выключено по умолчанию: работу делает компонент, которого ещё нет.
        Включённый тумблер обещал бы то, чего приложение не сделает
        (правило #27).
        """
        assert AppConfig().describe_images is False

    def test_components_live_next_to_the_exe(self):
        """Портативность — философия проекта: всё рядом, как session и config."""
        cfg = AppConfig()
        assert cfg.components_path.endswith("components")

    def test_components_dir_can_be_moved(self, tmp_path):
        """На случай маленького системного диска (COMPONENTS.md §2)."""
        cfg = AppConfig()
        cfg.components_dir = str(tmp_path / "куда-нибудь")
        assert cfg.components_path == str(tmp_path / "куда-нибудь")

    def test_setting_survives_save_and_load(self, tmp_path, monkeypatch):
        import config as cfgmod

        path = tmp_path / "config.json"
        monkeypatch.setattr(cfgmod, "CONFIG_FILE", str(path))
        cfg = AppConfig()
        cfg.describe_images = True
        cfgmod.save_config(cfg)
        assert cfgmod.load_config().describe_images is True
