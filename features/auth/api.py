"""
features/auth/api.py — Бизнес-логика авторизации в Telegram

Исправленная версия: усилена идентификация клиента для обхода фильтров Telegram.
"""

from __future__ import annotations

import logging
import os
import asyncio
from typing import Awaitable, Callable, Optional

from telethon import TelegramClient
from telethon.errors import (
    PhoneCodeInvalidError as TelethonPhoneCodeInvalidError,
    PhoneCodeExpiredError,
    SessionPasswordNeededError,
    PasswordHashInvalidError,
    FloodWaitError as TelethonFloodWaitError,
    RPCError,
)
from telethon.tl.types import User

from config import AppConfig
from core.exceptions import (
    AuthError,
    SessionExpiredError,
    PhoneCodeInvalidError,
    FloodWaitError,
    ConfigError,
)

logger = logging.getLogger(__name__)

# Тип для async-поставщика строки (телефон / код / пароль)
_StringProvider = Callable[[], Awaitable[str]]
# Тип для лог-колбэка (может быть Qt-сигнал или просто print)
_LogCallback = Callable[[str], None]


class AuthService:
    """
    Сервис авторизации в Telegram через Telethon.
    Методы статические, чтобы не плодить лишние состояния.
    """

    @staticmethod
    def build_client(cfg: AppConfig) -> TelegramClient:
        """
        Создаёт TelegramClient с параметрами реального устройства.
        
        Это критически важно в 2026 году: без device_model Telegram часто 
        не высылает код подтверждения.
        """
        cfg.validate()   

        logger.debug("auth: build_client api_id=%s session=%s", cfg.api_id, cfg.session_name)
        
        # Мы представляемся как официальное десктопное приложение
        return TelegramClient(
            session=cfg.session_path,
            api_id=cfg.api_id_int,
            api_hash=cfg.api_hash,
            device_model="Rozitta Parser Desktop",
            system_version="Windows 11",
            app_version="3.3.0",
            lang_code="ru",
            system_lang_code="ru-RU"
        )

    @staticmethod
    async def sign_in(
        client:            TelegramClient,
        phone_provider:    _StringProvider,
        code_provider:     _StringProvider,
        password_provider: _StringProvider,
        log:               _LogCallback = logger.info,
    ) -> Optional[User]:
        """
        Полный цикл авторизации.
        """
        log("🔌 Подключение к серверам Telegram...")
        if not client.is_connected():
            await client.connect()
        
        # --- Проверка активной сессии ---
        if await client.is_user_authorized():
            log("✅ Сессия уже активна")
            return await AuthService.get_me(client, log)

        # --- Получение телефона ---
        phone = await phone_provider()
        if not phone or not phone.strip():
            log("❌ Авторизация отменена: номер не введен")
            return None

        # Очищаем номер от лишнего мусора
        phone = ''.join(filter(lambda x: x.isdigit() or x == '+', phone.strip()))
        if not phone.startswith('+'):
            phone = '+' + phone

        log(f"📲 Запрос кода для {phone}...")

        # --- Отправка запроса на код ---
        try:
            # ВАЖНО: Мы явно просим Telegram отправить код
            await client.send_code_request(phone)
            log("📡 Запрос отправлен. Проверьте сообщения в Telegram на других устройствах")
        except TelethonFloodWaitError as exc:
            log(f"⏳ Слишком много попыток. Подождите {exc.seconds} сек.")
            raise FloodWaitError(exc.seconds) from exc
        except RPCError as exc:
            logger.error("auth: send_code_request failed: %s", exc)
            log(f"❌ Ошибка Telegram: {exc}")
            raise AuthError(f"Ошибка запроса кода: {exc}") from exc

        # --- Получение кода от пользователя ---
        code = await code_provider()
        if not code or not code.strip():
            log("❌ Авторизация отменена: код не введен")
            return None

        # --- Попытка входа ---
        try:
            # Убираем пробелы из кода, если они есть
            clean_code = code.strip().replace(" ", "")
            await client.sign_in(phone, clean_code)
            log("✅ Вход по коду выполнен")

        except TelethonPhoneCodeInvalidError:
            log("❌ Неверный код подтверждения")
            raise PhoneCodeInvalidError("Неверный код")
        except PhoneCodeExpiredError:
            log("❌ Срок действия кода истек")
            raise PhoneCodeInvalidError("Код устарел")
        except SessionPasswordNeededError:
            # --- 2FA (Облачный пароль) ---
            log("🔐 Требуется облачный пароль (2FA)...")
            password = await password_provider()
            if not password:
                log("❌ Отменено: пароль 2FA не введен")
                return None

            try:
                await client.sign_in(password=password)
                log("✅ Облачный пароль принят")
            except PasswordHashInvalidError:
                log("❌ Неверный облачный пароль")
                raise AuthError("Неверный пароль 2FA")
            except RPCError as exc:
                log(f"❌ Ошибка 2FA: {exc}")
                raise AuthError(f"Ошибка облачного пароля: {exc}")

        # Финализация
        return await AuthService.get_me(client, log)

    @staticmethod
    async def get_me(client: TelegramClient, log: _LogCallback) -> Optional[User]:
        """ Получение данных о себе после входа. """
        try:
            me = await client.get_me()
            name = f"{me.first_name or ''} {me.last_name or ''}".strip() or me.username or "User"
            log(f"👤 Вы вошли как: {name}")
            return me
        except Exception as e:
            logger.error("auth: get_me failed: %s", e)
            return None

    @staticmethod
    async def logout(client: TelegramClient, log: _LogCallback) -> None:
        """ Выход из аккаунта. """
        try:
            await client.log_out()
            log("✅ Выход выполнен")
        except Exception as exc:
            raise SessionExpiredError(f"Ошибка выхода: {exc}")
        finally:
            await client.disconnect()

    @staticmethod
    async def check_session(cfg: AppConfig) -> bool:
        """ Быстрая проверка сессии при старте. """
        client = None
        try:
            client = AuthService.build_client(cfg)
            await client.connect()
            return await client.is_user_authorized()
        except Exception:
            return False
        finally:
            if client:
                await client.disconnect()