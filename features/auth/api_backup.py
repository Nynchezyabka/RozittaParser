"""
features/auth/api.py — Бизнес-логика авторизации в Telegram

Не содержит ни строчки Qt-кода. Вся логика — чистый async Python.
UI-слой (features/auth/ui.py) создаёт воркер, оборачивает threading.Event
в async-колбэки и передаёт их сюда.

Архитектура колбэков:
    UI поток          features/auth/api.py
    ─────────         ────────────────────
    threading.Event   phone_provider()    ← ждёт event.wait(), возвращает строку
    threading.Event   code_provider()     ← то же для кода из Telegram
    threading.Event   password_provider() ← то же для пароля 2FA

Пример использования (в QThread.run):

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def get_phone():
        self.request_input.emit("Телефон:", False)
        self._input_event.wait()
        return self._input_value

    client = await AuthService.build_client(cfg)
    me = await AuthService.sign_in(
        client,
        phone_provider=get_phone,
        code_provider=get_code,
        password_provider=get_password,
        log=self.log_message.emit,
    )
    # me == None → отменено пользователем
    # me == User → успешно авторизованы
"""

from __future__ import annotations

import logging
import os
from typing import Awaitable, Callable, Optional

from telethon import TelegramClient
from telethon.errors import (
    PhoneCodeInvalidError   as TelethonPhoneCodeInvalidError,
    PhoneCodeExpiredError,
    SessionPasswordNeededError,
    PasswordHashInvalidError,
    FloodWaitError          as TelethonFloodWaitError,
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

    Все методы — статические или классовые: сервис не хранит состояния.
    Клиент создаётся извне через build_client() и живёт в воркере.

    Принцип работы:
        1. build_client()   — создаёт TelegramClient из AppConfig
        2. sign_in()        — полный цикл авторизации (код + 2FA)
        3. get_me()         — данные текущего пользователя
        4. logout()         — удалить сессию и выйти
    """

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    @staticmethod
    def build_client(cfg: AppConfig) -> TelegramClient:
        """
        Создаёт TelegramClient из AppConfig.

        Не подключается — только инициализирует объект.
        Соединение устанавливается при вызове sign_in() → client.connect().

        Args:
            cfg: Конфиг с api_id, api_hash, session_name.

        Returns:
            Готовый к подключению TelegramClient.

        Raises:
            ConfigError: если api_id или api_hash не заданы.
        """
        cfg.validate()   # бросит ConfigError если поля пустые / невалидные

        logger.debug("auth: build_client api_id=%s session=%s", cfg.api_id, cfg.session_name)
        return TelegramClient(
            session=cfg.session_path,
            api_id=cfg.api_id_int,
            api_hash=cfg.api_hash,
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
        Полный цикл авторизации: подключение → телефон → код → 2FA (если нужно).

        Метод НЕ разрывает соединение после авторизации — это делает воркер
        явно, чтобы иметь возможность сразу обратиться к get_me().

        Args:
            client:            Готовый TelegramClient (из build_client).
            phone_provider:    async-функция, возвращающая номер телефона.
                               Возврат пустой строки / None → отмена.
            code_provider:     async-функция, возвращающая код из Telegram.
            password_provider: async-функция, возвращающая пароль 2FA.
            log:               Колбэк для UI-логов (по умолчанию logger.info).

        Returns:
            User-объект авторизованного пользователя,
            или None если авторизация отменена пользователем.

        Raises:
            AuthError:              Общая ошибка авторизации (неверные данные и т.д.).
            PhoneCodeInvalidError:  Неверный код подтверждения.
            FloodWaitError:         Telegram требует паузу.
            ConfigError:            api_id/api_hash неверны.
        """
        log("🔌 Подключение к Telegram...")
        await client.connect()
        logger.debug("auth: client.connect() OK")

        # --- Проверяем существующую сессию ---
        session_file = str(client.session.filename) if hasattr(client.session, "filename") else ""
        if session_file and os.path.exists(session_file):
            size = os.path.getsize(session_file)
            log(f"📂 Файл сессии найден ({size} байт)")

        if await client.is_user_authorized():
            log("✅ Сессия активна, авторизация не требуется")
            me = await AuthService.get_me(client, log)
            return me

        # --- Запрашиваем телефон ---
        log("📱 Требуется авторизация...")
        phone = await phone_provider()
        if not phone or not phone.strip():
            log("❌ Отменено: не введён телефон")
            await client.disconnect()
            return None

        phone = phone.strip()
        logger.debug("auth: send_code_request phone=%s", phone)

        # --- Отправляем запрос на код ---
        try:
            await client.send_code_request(phone)
            log("✅ Код отправлен! Проверьте Telegram")
        except TelethonFloodWaitError as exc:
            wait_secs = exc.seconds
            log(f"⏳ FloodWait: подождите {wait_secs} сек.")
            raise FloodWaitError(wait_secs) from exc
        except RPCError as exc:
            logger.error("auth: send_code_request failed: %s", exc)
            await client.disconnect()
            raise AuthError(f"Ошибка отправки кода: {exc}") from exc

        # --- Запрашиваем код ---
        code = await code_provider()
        if not code or not code.strip():
            log("❌ Отменено: не введён код")
            await client.disconnect()
            return None

        # --- Пробуем войти ---
        try:
            await client.sign_in(phone, code.strip())
            log("✅ Код принят")

        except TelethonPhoneCodeInvalidError as exc:
            await client.disconnect()
            raise PhoneCodeInvalidError("Неверный код. Попробуйте ещё раз.") from exc

        except PhoneCodeExpiredError as exc:
            await client.disconnect()
            raise PhoneCodeInvalidError("Код устарел. Запросите новый.") from exc

        except SessionPasswordNeededError:
            # --- 2FA ---
            log("🔒 Требуется пароль 2FA")
            password = await password_provider()
            if not password:
                log("❌ Отменено: не введён пароль 2FA")
                await client.disconnect()
                return None

            try:
                await client.sign_in(password=password)
                log("✅ Пароль 2FA принят")
            except PasswordHashInvalidError as exc:
                await client.disconnect()
                raise AuthError("Неверный пароль 2FA") from exc
            except RPCError as exc:
                await client.disconnect()
                raise AuthError(f"Ошибка входа с паролем: {exc}") from exc

        except TelethonFloodWaitError as exc:
            await client.disconnect()
            raise FloodWaitError(exc.seconds) from exc

        except RPCError as exc:
            logger.error("auth: sign_in failed: %s", exc)
            await client.disconnect()
            raise AuthError(f"Ошибка входа: {exc}") from exc

        # --- Финал: получаем пользователя ---
        me = await AuthService.get_me(client, log)
        return me

    @staticmethod
    async def get_me(
        client: TelegramClient,
        log: _LogCallback = logger.info,
    ) -> Optional[User]:
        """
        Получает данные авторизованного пользователя.

        Args:
            client: Подключённый и авторизованный TelegramClient.
            log:    Колбэк для UI-логов.

        Returns:
            Объект User или None если получить не удалось.
        """
        try:
            me: User = await client.get_me()
            name = (
                me.first_name
                or me.username
                or me.phone
                or "Неизвестный пользователь"
            )
            log(f"👤 Авторизован как: {name}")
            logger.debug("auth: get_me → id=%s username=%s", me.id, me.username)
            return me
        except Exception as exc:
            log(f"⚠️ Не удалось получить данные пользователя: {exc}")
            logger.warning("auth: get_me failed: %s", exc)
            return None

    @staticmethod
    async def logout(
        client: TelegramClient,
        log: _LogCallback = logger.info,
    ) -> None:
        """
        Выход из аккаунта: удаляет сессию на стороне Telegram.

        После этого вызова .session-файл становится недействительным.
        Клиент отключается автоматически.

        Args:
            client: Подключённый TelegramClient.
            log:    Колбэк для UI-логов.

        Raises:
            SessionExpiredError: если сессия уже недействительна.
        """
        try:
            await client.log_out()
            log("✅ Выход выполнен успешно")
            logger.info("auth: logged out")
        except Exception as exc:
            logger.warning("auth: logout error: %s", exc)
            raise SessionExpiredError(f"Ошибка при выходе: {exc}") from exc
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass

    @staticmethod
    async def check_session(cfg: AppConfig) -> bool:
        """
        Быстрая проверка: есть ли активная сессия без полной авторизации.

        Используется при запуске приложения, чтобы показать кнопку
        «Продолжить» вместо формы входа.

        Args:
            cfg: Конфиг с параметрами соединения.

        Returns:
            True если сессия валидна, False в любом другом случае.
        """
        client: Optional[TelegramClient] = None
        try:
            cfg.validate()
            client = AuthService.build_client(cfg)
            await client.connect()
            result = await client.is_user_authorized()
            logger.debug("auth: check_session → %s", result)
            return result
        except Exception as exc:
            logger.debug("auth: check_session failed: %s", exc)
            return False
        finally:
            if client is not None:
                try:
                    await client.disconnect()
                except Exception:
                    pass
