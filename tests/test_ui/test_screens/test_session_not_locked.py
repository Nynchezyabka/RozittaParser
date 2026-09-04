"""
tests/test_ui/test_screens/test_session_not_locked.py

«database is locked»: захват session-файла переживает неудачный вход.

Telethon держит сессию в SQLite-файле, и `client.disconnect()` закрывает
это соединение (telegrambaseclient.py — `session.close()` в конце
`_disconnect_coro`). Значит блокировка остаётся ровно там, где до
`disconnect()` не доходит выполнение.

В `AuthWorker._auth()` отключение стояло строкой ПОСЛЕ `sign_in`, а не в
`finally`. При мёртвом прокси, неверном коде или FloodWait исключение
улетало в `run()`, минуя отключение, и файл оставался захваченным — следующий
вход или выход падали с «database is locked». Тестировщик поймал это
3 сентября 2026, переключая прокси и VPN.

Здесь закреплено, что клиент отключается на любом исходе.
"""
import asyncio
import os

import pytest

from config import AppConfig
import ui.main_window as mw


class FakeClient:
    def __init__(self):
        self.disconnected = False

    async def disconnect(self):
        self.disconnected = True


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.fixture
def worker(monkeypatch, qapp):
    """AuthWorker с подставными build_client и sign_in."""
    from features.auth import ui as auth_ui
    from features.auth import api as auth_api

    client = FakeClient()
    monkeypatch.setattr(
        auth_api.AuthService, "build_client", staticmethod(lambda cfg: client))

    w = auth_ui.AuthWorker(AppConfig())
    return w, client, auth_api


# ──────────────────────────────────────────────────────────────────────────────
# Клиент отключается на любом исходе входа
# ──────────────────────────────────────────────────────────────────────────────

class TestClientAlwaysDisconnected:
    def test_disconnected_after_successful_sign_in(self, worker, monkeypatch):
        w, client, auth_api = worker

        async def ok(*a, **kw):
            return object()

        monkeypatch.setattr(auth_api.AuthService, "sign_in", staticmethod(ok))
        _run(w._auth())
        assert client.disconnected is True

    def test_disconnected_when_sign_in_raises(self, worker, monkeypatch):
        """
        Главный тест файла. Именно этот путь оставлял захват файла:
        мёртвый прокси → sign_in бросает → disconnect пропущен.
        """
        w, client, auth_api = worker

        async def boom(*a, **kw):
            raise ConnectionError("прокси недоступен")

        monkeypatch.setattr(auth_api.AuthService, "sign_in", staticmethod(boom))
        with pytest.raises(ConnectionError):
            _run(w._auth())
        assert client.disconnected is True, \
            "session-файл остался захваченным — следующий вход упадёт с locked"

    def test_disconnected_when_sign_in_returns_none(self, worker, monkeypatch):
        """Отказ без исключения (пользователь закрыл ввод кода) — тоже путь."""
        w, client, auth_api = worker

        async def nothing(*a, **kw):
            return None

        monkeypatch.setattr(
            auth_api.AuthService, "sign_in", staticmethod(nothing))
        _run(w._auth())
        assert client.disconnected is True

    def test_error_still_reaches_the_user(self, worker, monkeypatch):
        """Отключение не должно проглотить причину отказа."""
        w, client, auth_api = worker

        async def boom(*a, **kw):
            raise RuntimeError("FloodWait 300")

        monkeypatch.setattr(auth_api.AuthService, "sign_in", staticmethod(boom))
        with pytest.raises(RuntimeError, match="FloodWait 300"):
            _run(w._auth())

    def test_hanging_disconnect_does_not_block(self, worker, monkeypatch):
        """
        При мёртвом прокси disconnect() ждёт фоновых задач и может не
        вернуться. Таймаут обязателен: иначе воркер повиснет, так и не
        отпустив файл, и «locked» останется до перезапуска.
        """
        w, client, auth_api = worker

        async def never(*a, **kw):
            await asyncio.sleep(3600)

        async def ok(*a, **kw):
            return object()

        monkeypatch.setattr(auth_api.AuthService, "sign_in", staticmethod(ok))
        monkeypatch.setattr(client, "disconnect", never)
        monkeypatch.setattr(mw, "_UNUSED", None, raising=False)

        async def guarded():
            await asyncio.wait_for(w._auth(), timeout=10.0)

        _run(guarded())  # не должно повиснуть


# ──────────────────────────────────────────────────────────────────────────────
# Удаление session-файла переживает задержавшийся дескриптор
# ──────────────────────────────────────────────────────────────────────────────

class TestSessionFileRemoval:
    def test_removes_existing_file(self, tmp_path, qapp):
        w = mw.LogoutWorker(AppConfig())
        f = tmp_path / "s.session"
        f.write_text("x", encoding="utf-8")
        assert w._remove_session_file(str(f)) is True
        assert not f.exists()

    def test_missing_file_is_success(self, tmp_path, qapp):
        """Файла нет — цель достигнута, это не ошибка."""
        w = mw.LogoutWorker(AppConfig())
        assert w._remove_session_file(str(tmp_path / "нет.session")) is True

    def test_retries_while_handle_lingers(self, tmp_path, qapp, monkeypatch):
        """
        Windows не отдаёт файл, пока его держат. Раньше первая же
        PermissionError роняла весь выход.
        """
        w = mw.LogoutWorker(AppConfig())
        f = tmp_path / "s.session"
        f.write_text("x", encoding="utf-8")

        calls = {"n": 0}
        real_remove = os.remove

        def flaky(path):
            calls["n"] += 1
            if calls["n"] < 3:
                raise PermissionError("файл занят другим процессом")
            real_remove(path)

        monkeypatch.setattr(mw.os, "remove", flaky)
        monkeypatch.setattr(mw.time, "sleep", lambda s: None)

        assert w._remove_session_file(str(f)) is True
        assert calls["n"] == 3
        assert not f.exists()

    def test_gives_up_with_actionable_message(self, tmp_path, qapp,
                                              monkeypatch):
        """Сдаться можно, но человек должен узнать, что делать дальше."""
        w = mw.LogoutWorker(AppConfig())
        f = tmp_path / "s.session"
        f.write_text("x", encoding="utf-8")

        monkeypatch.setattr(
            mw.os, "remove",
            lambda p: (_ for _ in ()).throw(PermissionError("занят")))
        monkeypatch.setattr(mw.time, "sleep", lambda s: None)

        errors = []
        w.error.connect(errors.append)
        assert w._remove_session_file(str(f)) is False
        assert len(errors) == 1
        assert str(f) in errors[0], "в сообщении нет пути к файлу"
