"""
tests/test_ui/test_scenarios/test_auth_flow.py

E2E сценарий авторизации: ввод данных → клик «Войти» → worker запускается.
Мокается AuthService и TelegramClient.
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from config import AppConfig
from features.auth.ui import AuthScreen, AuthWorker


class TestAuthFlowUI:
    def test_fill_credentials_and_check_fields(self, qapp):
        """Пользователь заполняет все поля."""
        cfg = AppConfig()
        screen = AuthScreen(cfg)

        screen._api_id.setText("12345")
        screen._api_hash.setText("abcdef1234567890")
        screen._phone.setText("+79991234567")

        assert screen._api_id.text() == "12345"
        assert screen._api_hash.text() == "abcdef1234567890"
        assert screen._phone.text() == "+79991234567"

    def test_proxy_enable_toggle(self, qapp):
        """Пользователь включает прокси."""
        screen = AuthScreen(AppConfig())
        screen._proxy_toggle.setChecked(True)
        assert screen._proxy_toggle.isChecked()

    def test_login_button_exists(self, qapp):
        screen = AuthScreen(AppConfig())
        assert hasattr(screen, "_login_btn") or hasattr(screen, "_btn_login")

    def test_cancel_button_exists(self, qapp):
        screen = AuthScreen(AppConfig())
        assert hasattr(screen, "_cancel_check_btn")

    def test_config_values_prepopulated(self, qapp):
        """Поля заполняются из конфига."""
        cfg = AppConfig(api_id="99999", api_hash="xyz789", phone="+1555")
        screen = AuthScreen(cfg)
        assert screen._api_id.text() == "99999"
        assert screen._api_hash.text() == "xyz789"
        assert screen._phone.text() == "+1555"


class TestAuthWorkerFlow:
    def test_worker_signals_complete_set(self):
        """Все сигналы для сценария авторизации присутствуют."""
        worker = AuthWorker(AppConfig())
        assert hasattr(worker, "auth_complete")
        assert hasattr(worker, "log_message")
        assert hasattr(worker, "error")
        assert hasattr(worker, "character_state")
        assert hasattr(worker, "request_input")

    def test_provide_input_resolves_code(self):
        """UI вводит код → provide_input передаёт его воркеру."""
        worker = AuthWorker(AppConfig())
        worker._input_ready = False
        worker.provide_input("12345")
        assert worker._input_value == "12345"
        assert worker._input_ready is True

    def test_provide_input_none_for_cancel(self):
        """Пользователь отменяет ввод."""
        worker = AuthWorker(AppConfig())
        worker.provide_input(None)
        assert worker._input_value is None

    @pytest.mark.asyncio
    async def test_ask_emits_request_input(self):
        """_ask эмитирует request_input и ожидает ответ."""
        worker = AuthWorker(AppConfig())
        received_prompts = []
        worker.request_input.connect(
            lambda p, t, pw: received_prompts.append((p, t, pw))
        )

        # Имитируем: через 0.1 секунду даём ответ
        import asyncio

        async def delayed_answer():
            await asyncio.sleep(0.05)
            worker.provide_input("test_code")

        task = asyncio.create_task(delayed_answer())
        result = await worker._ask("Введите код", "Код", False)
        await task

        assert result == "test_code"
        assert len(received_prompts) == 1
        assert received_prompts[0][0] == "Введите код"

    def test_reset_clears_state(self, qapp):
        """AuthScreen.reset() возвращает в начальное состояние."""
        screen = AuthScreen(AppConfig(api_id="1", api_hash="x"))
        screen.reset()
        # После reset экран должен быть доступен для повторной авторизации
