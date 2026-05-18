"""
tests/test_features/test_auth_mocks.py

Тесты: AuthService — sign_in, get_me, logout, check_session с моками Telethon.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from features.auth.api import AuthService
from core.exceptions import AuthError, PhoneCodeInvalidError, FloodWaitError


def _mock_client(authorized=False):
    """Фабрика мок-клиента Telethon."""
    client = MagicMock()
    client.is_connected.return_value = True
    client.is_user_authorized = AsyncMock(return_value=authorized)
    client.connect = AsyncMock()
    client.disconnect = AsyncMock()
    client.send_code_request = AsyncMock()
    client.sign_in = AsyncMock()
    client.get_me = AsyncMock(return_value=MagicMock(
        id=1, first_name="Test", last_name="User", username="test_user",
    ))
    client.log_out = AsyncMock()
    return client


class TestSignIn:
    @pytest.mark.asyncio
    async def test_already_authorized(self):
        client = _mock_client(authorized=True)
        logs = []
        user = await AuthService.sign_in(
            client,
            phone_provider=AsyncMock(),
            code_provider=AsyncMock(),
            password_provider=AsyncMock(),
            log=logs.append,
        )
        assert user is not None
        assert user.first_name == "Test"
        assert any("Сессия уже активна" in l for l in logs)

    @pytest.mark.asyncio
    async def test_connects_if_not_connected(self):
        client = _mock_client()
        client.is_connected.return_value = False
        await AuthService.sign_in(
            client,
            phone_provider=AsyncMock(return_value=""),
            code_provider=AsyncMock(),
            password_provider=AsyncMock(),
        )
        client.connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_empty_phone_returns_none(self):
        client = _mock_client()
        user = await AuthService.sign_in(
            client,
            phone_provider=AsyncMock(return_value=""),
            code_provider=AsyncMock(),
            password_provider=AsyncMock(),
        )
        assert user is None

    @pytest.mark.asyncio
    async def test_whitespace_phone_returns_none(self):
        client = _mock_client()
        user = await AuthService.sign_in(
            client,
            phone_provider=AsyncMock(return_value="   "),
            code_provider=AsyncMock(),
            password_provider=AsyncMock(),
        )
        assert user is None

    @pytest.mark.asyncio
    async def test_phone_cleaned_and_plus_added(self):
        client = _mock_client()
        logs = []
        await AuthService.sign_in(
            client,
            phone_provider=AsyncMock(return_value="7999 123 45 67"),
            code_provider=AsyncMock(return_value=""),
            password_provider=AsyncMock(),
            log=logs.append,
        )
        client.send_code_request.assert_called_once_with("+79991234567")

    @pytest.mark.asyncio
    async def test_flood_wait_on_send_code(self):
        from telethon.errors import FloodWaitError as TelethonFloodWait
        client = _mock_client()
        client.send_code_request = AsyncMock(
            side_effect=TelethonFloodWait(MagicMock(), capture=60)
        )
        with pytest.raises(FloodWaitError):
            await AuthService.sign_in(
                client,
                phone_provider=AsyncMock(return_value="+79991234567"),
                code_provider=AsyncMock(),
                password_provider=AsyncMock(),
            )

    @pytest.mark.asyncio
    async def test_rpc_error_on_send_code(self):
        from telethon.errors import RPCError
        client = _mock_client()
        client.send_code_request = AsyncMock(
            side_effect=RPCError(0, "api error", "TEST")
        )
        with pytest.raises(AuthError, match="запроса кода"):
            await AuthService.sign_in(
                client,
                phone_provider=AsyncMock(return_value="+79991234567"),
                code_provider=AsyncMock(),
                password_provider=AsyncMock(),
            )

    @pytest.mark.asyncio
    async def test_empty_code_returns_none(self):
        client = _mock_client()
        user = await AuthService.sign_in(
            client,
            phone_provider=AsyncMock(return_value="+79991234567"),
            code_provider=AsyncMock(return_value=""),
            password_provider=AsyncMock(),
        )
        assert user is None

    @pytest.mark.asyncio
    async def test_invalid_code(self):
        from telethon.errors import PhoneCodeInvalidError as TelethonPCI
        client = _mock_client()
        client.sign_in = AsyncMock(
            side_effect=TelethonPCI(MagicMock())
        )
        with pytest.raises(PhoneCodeInvalidError):
            await AuthService.sign_in(
                client,
                phone_provider=AsyncMock(return_value="+79991234567"),
                code_provider=AsyncMock(return_value="00000"),
                password_provider=AsyncMock(),
            )

    @pytest.mark.asyncio
    async def test_expired_code(self):
        from telethon.errors import PhoneCodeExpiredError
        client = _mock_client()
        client.sign_in = AsyncMock(
            side_effect=PhoneCodeExpiredError(MagicMock())
        )
        with pytest.raises(PhoneCodeInvalidError):
            await AuthService.sign_in(
                client,
                phone_provider=AsyncMock(return_value="+79991234567"),
                code_provider=AsyncMock(return_value="12345"),
                password_provider=AsyncMock(),
            )

    @pytest.mark.asyncio
    async def test_2fa_successful(self):
        from telethon.errors import SessionPasswordNeededError
        client = _mock_client()
        call_count = 0

        def sign_in_side_effect(*a, **kw):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise SessionPasswordNeededError(MagicMock())
            # second call (password) succeeds (default AsyncMock)

        client.sign_in = AsyncMock(side_effect=sign_in_side_effect)
        user = await AuthService.sign_in(
            client,
            phone_provider=AsyncMock(return_value="+79991234567"),
            code_provider=AsyncMock(return_value="12345"),
            password_provider=AsyncMock(return_value="mypassword"),
        )
        assert user is not None

    @pytest.mark.asyncio
    async def test_2fa_empty_password_returns_none(self):
        from telethon.errors import SessionPasswordNeededError
        client = _mock_client()
        client.sign_in = AsyncMock(
            side_effect=SessionPasswordNeededError(MagicMock())
        )
        user = await AuthService.sign_in(
            client,
            phone_provider=AsyncMock(return_value="+79991234567"),
            code_provider=AsyncMock(return_value="12345"),
            password_provider=AsyncMock(return_value=""),
        )
        assert user is None

    @pytest.mark.asyncio
    async def test_2fa_wrong_password(self):
        from telethon.errors import SessionPasswordNeededError, PasswordHashInvalidError
        client = _mock_client()
        call_count = 0

        def sign_in_side_effect(*a, **kw):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise SessionPasswordNeededError(MagicMock())
            raise PasswordHashInvalidError(MagicMock())

        client.sign_in = AsyncMock(side_effect=sign_in_side_effect)
        with pytest.raises(AuthError, match="Неверный пароль 2FA"):
            await AuthService.sign_in(
                client,
                phone_provider=AsyncMock(return_value="+79991234567"),
                code_provider=AsyncMock(return_value="12345"),
                password_provider=AsyncMock(return_value="wrong"),
            )

    @pytest.mark.asyncio
    async def test_successful_sign_in(self):
        client = _mock_client()
        user = await AuthService.sign_in(
            client,
            phone_provider=AsyncMock(return_value="+79991234567"),
            code_provider=AsyncMock(return_value="12345"),
            password_provider=AsyncMock(),
        )
        assert user is not None
        client.sign_in.assert_called_once()


class TestGetMe:
    @pytest.mark.asyncio
    async def test_returns_user(self):
        client = _mock_client()
        logs = []
        user = await AuthService.get_me(client, log=logs.append)
        assert user is not None
        assert user.first_name == "Test"

    @pytest.mark.asyncio
    async def test_error_returns_none(self):
        client = MagicMock()
        client.get_me = AsyncMock(side_effect=Exception("fail"))
        user = await AuthService.get_me(client, log=lambda _: None)
        assert user is None


class TestLogout:
    @pytest.mark.asyncio
    async def test_successful_logout(self):
        client = _mock_client()
        logs = []
        await AuthService.logout(client, log=logs.append)
        client.log_out.assert_called_once()
        client.disconnect.assert_called_once()
        assert any("Выход выполнен" in l for l in logs)

    @pytest.mark.asyncio
    async def test_logout_error_raises(self):
        from core.exceptions import SessionExpiredError
        client = MagicMock()
        client.log_out = AsyncMock(side_effect=Exception("session gone"))
        client.disconnect = AsyncMock()
        with pytest.raises(SessionExpiredError):
            await AuthService.logout(client, log=lambda _: None)

    @pytest.mark.asyncio
    async def test_logout_disconnects_even_on_error(self):
        from core.exceptions import SessionExpiredError
        client = MagicMock()
        client.log_out = AsyncMock(side_effect=Exception("err"))
        client.disconnect = AsyncMock()
        with pytest.raises(SessionExpiredError):
            await AuthService.logout(client, log=lambda _: None)
        client.disconnect.assert_called_once()


class TestCheckSession:
    @pytest.mark.asyncio
    async def test_active_session(self):
        cfg = MagicMock()
        client = _mock_client(authorized=True)
        with patch.object(AuthService, "build_client", return_value=client):
            result = await AuthService.check_session(cfg)
        assert result is True

    @pytest.mark.asyncio
    async def test_no_session(self):
        cfg = MagicMock()
        client = _mock_client(authorized=False)
        with patch.object(AuthService, "build_client", return_value=client):
            result = await AuthService.check_session(cfg)
        assert result is False

    @pytest.mark.asyncio
    async def test_error_returns_false(self):
        cfg = MagicMock()
        with patch.object(AuthService, "build_client", side_effect=Exception("fail")):
            result = await AuthService.check_session(cfg)
        assert result is False

    @pytest.mark.asyncio
    async def test_disconnects_on_success(self):
        cfg = MagicMock()
        client = _mock_client(authorized=True)
        with patch.object(AuthService, "build_client", return_value=client):
            await AuthService.check_session(cfg)
        client.disconnect.assert_called_once()


class TestParseProxyLink:
    def test_valid_mtproto_link(self):
        link = "https://t.me/proxy?server=1.2.3.4&port=443&secret=ee000000"
        result = AuthService.parse_proxy_link(link)
        assert result is not None
        assert result["type"] == "mtproto"
        assert result["host"] == "1.2.3.4"
        assert result["port"] == 443
        assert result["secret"] == "ee000000"

    def test_missing_server_returns_none(self):
        link = "https://t.me/proxy?port=443&secret=abc"
        result = AuthService.parse_proxy_link(link)
        assert result is None

    def test_missing_secret_returns_none(self):
        link = "https://t.me/proxy?server=1.2.3.4&port=443"
        result = AuthService.parse_proxy_link(link)
        assert result is None

    def test_non_proxy_link(self):
        link = "https://t.me/channel_name"
        result = AuthService.parse_proxy_link(link)
        assert result is None

    def test_garbage_returns_none(self):
        result = AuthService.parse_proxy_link("not a url at all")
        assert result is None

    def test_custom_port(self):
        link = "https://t.me/proxy?server=5.6.7.8&port=8080&secret=abc123"
        result = AuthService.parse_proxy_link(link)
        assert result["port"] == 8080


# ---------------------------------------------------------------------------
# Issue #11: EXE + opentele import handling
# ---------------------------------------------------------------------------

class TestDetectTdataPath:
    def test_returns_none_when_no_tdata(self, tmp_path, monkeypatch):
        """Если tdata папки не существует — возвращает None."""
        monkeypatch.setenv("APPDATA", str(tmp_path))
        result = AuthService.detect_tdata_path()
        assert result is None

    def test_finds_tdata_on_windows(self, tmp_path, monkeypatch):
        """Находит tdata в %APPDATA%/Telegram Desktop/tdata."""
        tdata = tmp_path / "Telegram Desktop" / "tdata"
        tdata.mkdir(parents=True)
        monkeypatch.setenv("APPDATA", str(tmp_path))
        result = AuthService.detect_tdata_path()
        assert result is not None
        assert "tdata" in result

    def test_finds_uwp_variant(self, tmp_path, monkeypatch):
        """Находит tdata в %APPDATA%/Telegram Desktop UWP/tdata."""
        tdata = tmp_path / "Telegram Desktop UWP" / "tdata"
        tdata.mkdir(parents=True)
        monkeypatch.setenv("APPDATA", str(tmp_path))
        result = AuthService.detect_tdata_path()
        assert result is not None


class TestImportFromTdata:
    @pytest.mark.asyncio
    async def test_opentele_not_installed_raises(self, tmp_path):
        """Если opentele2 не установлен — AuthError."""
        import importlib
        with patch.dict("sys.modules", {"opentele2": None, "opentele2.td": None, "opentele2.api": None}):
            with pytest.raises(AuthError, match="opentele2"):
                await AuthService.import_from_tdata(
                    str(tmp_path),
                    str(tmp_path / "test_session"),
                )

    @pytest.mark.asyncio
    async def test_tdata_path_not_exists(self, tmp_path):
        """Несуществующий путь — AuthError (opentele2 не установлен)."""
        with pytest.raises(AuthError):
            await AuthService.import_from_tdata(
                str(tmp_path / "nonexistent_tdata"),
                str(tmp_path / "session"),
                log=lambda _: None,
            )
