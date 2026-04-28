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
    def parse_proxy_link(link: str):
        """
        Разбирает ссылку https://t.me/proxy?server=...&port=...&secret=...
        Возвращает dict {type, host, port, secret} или None.
        """
        try:
            from urllib.parse import urlparse, parse_qs
            parsed = urlparse(link.strip())
            if "proxy" not in parsed.path:
                return None
            qs = parse_qs(parsed.query)
            host   = qs.get("server", [""])[0]
            port   = int(qs.get("port", [443])[0])
            secret = qs.get("secret", [""])[0]
            if host and secret:
                return {"type": "mtproto", "host": host, "port": port, "secret": secret}
        except Exception:
            logging.exception('Исключение в parse_proxy_link.')
        return None

    @staticmethod
    def build_client(cfg: AppConfig) -> TelegramClient:
        """
        Единственное место создания TelegramClient — все воркеры используют этот метод.
        Поддерживает SOCKS5 (Tor) и MTProto (ссылки t.me/proxy).
        Если файл сессии уже существует, не требует api_id/api_hash.
        """

        cfg.validate()
        logger.debug("auth: build_client api_id=%s proxy=%s",
                    cfg.api_id, cfg.proxy_type if cfg.proxy_enabled else "none")

        connection_class = None
        proxy = None

        if getattr(cfg, "proxy_enabled", False):
            ptype = getattr(cfg, "proxy_type", "socks5")

            if ptype == "mtproto":
                try:
                    from telethon.network import ConnectionTcpMTProxyAbridged
                    connection_class = ConnectionTcpMTProxyAbridged
                    proxy = (cfg.proxy_host, cfg.proxy_port, cfg.proxy_secret)
                    logger.info("auth: прокси MTProto %s:%s активен", cfg.proxy_host, cfg.proxy_port)
                except Exception as exc:
                    logger.warning("auth: MTProto прокси ошибка: %s", exc)
            else:  # socks5
                try:
                    import socks
                    import socket as _socket
                    try:
                        _s = _socket.socket()
                        _s.settimeout(2)
                        _s.connect((cfg.proxy_host, cfg.proxy_port))
                        _s.close()
                        proxy = (socks.SOCKS5, cfg.proxy_host, cfg.proxy_port)
                        logger.info("auth: прокси SOCKS5 %s:%s активен", cfg.proxy_host, cfg.proxy_port)
                    except OSError:
                        logger.warning("auth: прокси %s:%s недоступен", cfg.proxy_host, cfg.proxy_port)
                        raise ConnectionError(
                            f"🔌 Прокси недоступен ({cfg.proxy_host}:{cfg.proxy_port})\n\n"
                            f"Запустите Tor перед входом в приложение,\n"
                            f"дождитесь «Bootstrapped 100%» и повторите."
                        )
                except ImportError:
                    logger.warning("auth: PySocks не установлен — pip install PySocks")

        session_path = cfg.session_path
        session_file = session_path + ".session"

        api_id   = cfg.api_id_int
        api_hash = cfg.api_hash

        if os.path.exists(session_file):
            logger.info("auth: используем существующую сессию %s", session_file)
        else:
            logger.info("auth: создаём новую сессию")

        kwargs = dict(
            session          = cfg.session_path,
            api_id           = api_id,
            api_hash         = api_hash,
            device_model     = "Rozitta Parser Desktop",
            system_version   = "Windows 11",
            app_version      = "3.3.0",
            lang_code        = "ru",
            system_lang_code = "ru-RU",
            proxy            = proxy,
        )
        if connection_class:
            kwargs["connection"] = connection_class
        return TelegramClient(**kwargs)


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
            logging.exception('Исключение в check_session')
            return False
        finally:
            if client:
                await client.disconnect()

    # ──────────────────────────────────────────────────────────────────────
    # tdata импорт (по мотивам TDL app/login/desktop.go)
    # ──────────────────────────────────────────────────────────────────────

    @staticmethod
    def detect_tdata_path() -> Optional[str]:
        """
        Автоматически находит папку tdata Telegram Desktop.

        Порядок поиска идентичен TDL (pkg/tpath/tpath_*.go):
            Windows : %APPDATA%/Telegram Desktop/tdata
            macOS   : ~/Library/Application Support/Telegram Desktop/tdata
            Linux   : ~/.local/share/TelegramDesktop/tdata
                      ~/.TelegramDesktop/tdata (старый путь)

        Returns:
            Абсолютный путь к папке tdata или None если не найдено.
        """
        import platform
        home = os.path.expanduser("~")

        candidates: list[str] = []

        system = platform.system()
        if system == "Windows":
            appdata = os.environ.get("APPDATA", "")
            if appdata:
                candidates += [
                    os.path.join(appdata, "Telegram Desktop", "tdata"),
                    os.path.join(appdata, "Telegram Desktop UWP", "tdata"),
                ]
        elif system == "Darwin":
            candidates += [
                os.path.join(home, "Library", "Application Support",
                             "Telegram Desktop", "tdata"),
            ]
        else:  # Linux
            local_share = os.path.join(home, ".local", "share")
            candidates += [
                os.path.join(home, ".TelegramDesktop", "tdata"),      # старый
                os.path.join(local_share, "TelegramDesktop", "tdata"),
                os.path.join(local_share, "Telegram Desktop", "tdata"),
                os.path.join(local_share, "KotatogramDesktop", "tdata"),
                os.path.join(local_share, "64Gram", "tdata"),
            ]

        for path in candidates:
            if os.path.isdir(path):
                logger.debug("auth: tdata found at %s", path)
                return path

        logger.debug("auth: tdata not found in %d candidates", len(candidates))
        return None

    @staticmethod
    async def import_from_tdata(
        tdata_path: str,
        session_out: str,
        log: _LogCallback = logger.info,
        passcode: str = "",
    ) -> Optional[User]:
        """
        Импортирует сессию Telegram Desktop без ввода кода или пароля.

        Читает папку tdata через библиотеку opentele и создаёт файл .session
        совместимый с Telethon. Аналог TDL `tdl login -n <ns> desktop`.

        Args:
            tdata_path:  Путь к папке tdata (например C:/Users/.../tdata).
            session_out: Путь к выходному .session файлу (без расширения).
            log:         Колбэк для прогресс-логов.
            passcode:    Пароль шифрования tdata (обычно пустой).

        Returns:
            User если импорт успешен, None при ошибке.

        Raises:
            AuthError: opentele2 не установлен или tdata повреждена.
        """
        log("🖥️ Читаю данные Telegram Desktop...")

        try:
            from opentele2.td import TDesktop          # type: ignore
            from opentele2.api import UseCurrentSession  # type: ignore
            log("   → opentele2 загружен")
        except ImportError:
            msg = (
                "opentele2 не установлен. "
                "Выполните: pip install opentele2"
            )
            log(f"❌ {msg}")
            raise AuthError(msg)

        try:
            log(f"📂 Папка tdata: {tdata_path}")
            log("   → Создаю объект TDesktop...")
            tdesk = TDesktop(tdata_path, passcode=passcode or None)

            log("   → Проверяю загрузку tdata...")
            if not tdesk.isLoaded():
                raise AuthError("Не удалось прочитать tdata. "
                                "Убедитесь что Telegram Desktop закрыт.")
            log("   → tdata загружена")

            log("   → Получаю список аккаунтов...")
            accounts = tdesk.accounts
            if not accounts:
                raise AuthError("В tdata не найдено ни одного аккаунта.")
            log(f"👥 Найдено аккаунтов: {len(accounts)}")

            # Берём первый (активный) аккаунт — аналог UseCurrentSession в TDL
            log("🔄 Конвертирую сессию в формат Telethon...")
            log("   → Вызываю tdesk.ToTelethon...")
            
            try:
                client = await asyncio.wait_for(
                    tdesk.ToTelethon(session=session_out, flag=UseCurrentSession),
                    timeout=60.0
                )
                log("   → ToTelethon завершён (60 сек)")
            except asyncio.TimeoutError:
                log("❌ Таймаут 60 сек при конвертации сессии")
                raise AuthError("Превышено время ожидания конвертации сессии")

            log("   → client.connect()...")
            await asyncio.wait_for(client.connect(), timeout=30.0)
            log("   → Подключено")

            log("   → Получаю данные пользователя...")
            me = await asyncio.wait_for(client.get_me(), timeout=15.0)
            log(f"   → Получен пользователь: {me.id}")

            log("   → Отключаюсь...")
            await asyncio.wait_for(client.disconnect(), timeout=10.0)
            log("   → Отключено")

            if me is None:
                raise AuthError("Сессия импортирована, но аккаунт недоступен.")

            name = f"{me.first_name or ''} {me.last_name or ''}".strip() or me.username or "User"
            log(f"✅ Импорт успешен! Аккаунт: {name} (@{me.username or '—'})")
            logger.info("auth: tdata import ok user_id=%s", me.id)
            return me

        except asyncio.TimeoutError as exc:
            log(f"❌ Таймаут операции: {exc}")
            raise AuthError(f"Превышено время ожидания: {exc}")
        except AuthError:
            raise
        except Exception as exc:
            logger.error("auth: tdata import failed: %s", exc)
            log(f"❌ Ошибка: {exc}")
            raise AuthError(f"Ошибка импорта tdata: {exc}") from exc