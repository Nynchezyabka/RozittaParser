"""
tests/test_ui/test_screens/test_logout_is_local.py

Выход не должен убивать авторизацию Telegram.

`client.log_out()` завершает авторизацию на серверах Telegram, а не сеанс
приложения. При импорте из tdata приложение работает на том же ключе, что и
Telegram Desktop, — авторизация одна на двоих, и её завершение выкидывает
человека из десктопа. У кого одно устройство, тому и код входа получить
некуда.

Тестировщик словил это 3 сентября 2026, нажав кнопку с подписью «Выйти».
Здесь закреплено, что обычный выход локальный.
"""
import os

import pytest

from config import AppConfig
import ui.main_window as mw


class FakeSession:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class FakeClient:
    """Клиент, который запоминает, что с ним сделали."""

    def __init__(self):
        self.connected = False
        self.logged_out = False
        self.disconnected = False
        self.session = FakeSession()

    async def connect(self):
        self.connected = True

    async def log_out(self):
        self.logged_out = True

    def disconnect(self):
        self.disconnected = True
        return None


@pytest.fixture
def fake_client(monkeypatch):
    """Подменяет AuthService.build_client на подставной клиент."""
    from features.auth import api as auth_api
    client = FakeClient()
    monkeypatch.setattr(
        auth_api.AuthService, "build_client", staticmethod(lambda cfg: client))
    return client


@pytest.fixture
def cfg(tmp_path):
    """
    Конфиг с настоящим session-файлом, который не жалко удалить.

    Подставляется session_name, а не session_path: последний — свойство
    только на чтение, оно и достраивает абсолютный путь.
    """
    conf = AppConfig()
    conf.session_name = str(tmp_path / "rozitta_session")
    session = tmp_path / "rozitta_session.session"
    session.write_text("не настоящая сессия", encoding="utf-8")
    assert conf.session_path == str(tmp_path / "rozitta_session")
    return conf, str(session)


def _run(worker):
    """Прогоняет корутину воркера без запуска QThread."""
    import asyncio
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(worker._do_logout())
    finally:
        loop.close()


class TestDefaultLogoutIsLocal:
    def test_log_out_is_not_called(self, cfg, fake_client, qapp):
        """Главный тест файла: авторизация Telegram не трогается."""
        conf, _ = cfg
        _run(mw.LogoutWorker(conf))
        assert fake_client.logged_out is False

    def test_client_is_disconnected(self, cfg, fake_client, qapp):
        """Соединение всё равно надо закрыть — иначе session остаётся занят."""
        conf, _ = cfg
        _run(mw.LogoutWorker(conf))
        assert fake_client.disconnected is True

    def test_session_file_is_removed(self, cfg, fake_client, qapp):
        """Локальный выход означает, что при следующем старте формa пустая."""
        conf, session_file = cfg
        assert os.path.exists(session_file)
        _run(mw.LogoutWorker(conf))
        assert not os.path.exists(session_file)

    def test_done_signal_emitted(self, cfg, fake_client, qapp):
        conf, _ = cfg
        worker = mw.LogoutWorker(conf)
        seen = []
        worker.logout_done.connect(lambda: seen.append(True))
        _run(worker)
        assert seen == [True]


class TestExplicitTerminationStillPossible:
    """
    Возможность завершить авторизацию не потеряна — она перестала быть
    поведением по умолчанию. Интерфейс её пока не включает.
    """

    def test_flag_calls_log_out(self, cfg, fake_client, qapp):
        conf, _ = cfg
        _run(mw.LogoutWorker(conf, terminate_session=True))
        assert fake_client.logged_out is True

    def test_flag_defaults_to_false(self, cfg, qapp):
        conf, _ = cfg
        assert mw.LogoutWorker(conf)._terminate_session is False


class TestButtonExplainsItself:
    def test_tooltip_mentions_what_survives(self, qapp):
        """
        Подпись «Выйти» неоднозначна, поэтому границу проговаривает
        подсказка — иначе человек снова гадает, что именно он выключает.
        """
        from core.database import DBManager
        win = mw.MainWindow(AppConfig(), DBManager(":memory:"))
        try:
            tip = win._logout_btn.toolTip()
            assert tip
            assert "Авторизация Telegram" in tip
        finally:
            win.close()
