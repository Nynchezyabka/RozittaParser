"""
FILE: features/auth/ui.py

Авторизация в Telegram: воркер + экран.

Реальный API AuthService (features/auth/api.py):
    ┌─────────────────────────────────────────────────────────┐
    │  AuthService.build_client(cfg) -> TelegramClient        │
    │  AuthService.sign_in(                                   │
    │      client,                                            │
    │      phone_provider:    async () -> str,                │
    │      code_provider:     async () -> str,                │
    │      password_provider: async () -> str,                │
    │      log:               (str) -> None,                  │
    │  ) -> Optional[User]          ← только User, не client  │
    │                                                         │
    │  AuthService.check_session(cfg) -> bool                 │
    │      (проверяет сессию и отключается, не возвращает Me) │
    └─────────────────────────────────────────────────────────┘

Было неправильно (вызывало TypeError):
    service = AuthService(cfg=..., log_callback=..., input_callback=...)
    ← AuthService() takes no arguments (он статический)

Изменение сигнала auth_complete:
    БЫЛО:  Signal(object)          ← только user
    СТАЛО: Signal(object, object)  ← (client, user)
    MainWindow._on_auth_complete(client, user) — принимает оба.
    client нужен для ChatsWorker / ParseWorker.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from PySide6.QtCore import Qt, Signal, Slot, QThread
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame, QInputDialog, QLabel, QLineEdit,
    QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from config import AppConfig
from core.ui_shared.styles import (
    ACCENT_ORANGE, ACCENT_SOFT_ORANGE,
    COLOR_SUCCESS, COLOR_ERROR, COLOR_WARNING,
    TEXT_SECONDARY,
    OVERLAY2_HEX, BORDER_HEX,
    RADIUS_MD, RADIUS_XS,
    FONT_FAMILY, FONT_SIZE_SMALL, FONT_SIZE_XS,
    QSS_INPUT, QSS_BUTTON_PRIMARY,
)
from core.ui_shared.widgets import PasswordLineEdit

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# SESSION CHECK WORKER
# ══════════════════════════════════════════════════════════════════════════════

class SessionCheckWorker(QThread):
    """
    Тихая проверка сессии при старте.

    Использует AuthService.check_session(cfg) -> bool.
    Если сессия жива — строит client, получает User, эмитирует session_valid.

    Почему не просто check_session:
        check_session возвращает bool и отключается.
        Нам нужен живой client для дальнейшей работы.
        Поэтому после is_user_authorized() мы не отключаемся,
        а получаем get_me() и передаём (client, user) наверх.
    """

    session_valid = Signal(object, object)  # (TelegramClient, User)
    log_message   = Signal(str)

    def __init__(self, cfg: AppConfig, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._cfg = cfg

    def run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(self._check())
            if result is not None:
                client, user = result
                self.session_valid.emit(client, user)
        except Exception:
            pass  # нет сессии — молча ничего не делаем
        finally:
            loop.close()

    async def _check(self):
        """
        Возвращает (None, user) если сессия жива, иначе None.
        Client всегда отключается здесь — ChatsWorker/ParseWorker создадут свой.
        """
        from features.auth.api import AuthService
        client = None
        try:
            client = AuthService.build_client(self._cfg)
            await client.connect()
            if await client.is_user_authorized():
                user = await client.get_me()
                if user is not None:
                    return None, user   # сессия сохранена на диск — живой client не нужен
        except Exception:
            pass
        finally:
            if client is not None:
                try:
                    await client.disconnect()
                except Exception:
                    pass
        return None


# ══════════════════════════════════════════════════════════════════════════════
# AUTH WORKER
# ══════════════════════════════════════════════════════════════════════════════

class AuthWorker(QThread):
    """
    QThread-воркер авторизации через Telethon.

    Правильный порядок вызовов AuthService:
        client = AuthService.build_client(cfg)         # синхронный @staticmethod
        user   = await AuthService.sign_in(            # async @staticmethod
                     client,
                     phone_provider    = self._provide_phone,
                     code_provider     = self._provide_code,
                     password_provider = self._provide_password,
                     log               = self.log_message.emit,
                 )
        # sign_in возвращает User | None — client остаётся живым

    Сигналы:
        log_message(str)
        auth_complete(object, object)  — (TelegramClient, User); (None, None) = отмена
        error(str)
        request_input(str, str, bool)  — prompt, title, is_password
        character_state(str)
    """

    log_message     = Signal(str)
    auth_complete   = Signal(object, object)   # (client, user) | (None, None)
    error           = Signal(str)
    request_input   = Signal(str, str, bool)
    character_state = Signal(str)

    def __init__(self, cfg: AppConfig, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._cfg         = cfg
        self._input_value: Optional[str] = None
        self._input_ready = False
        self._client      = None   # держим для передачи в auth_complete

    def provide_input(self, value: Optional[str]) -> None:
        """Передать ответ UI в ожидающую корутину."""
        self._input_value = value
        self._input_ready = True

    def run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._auth())
        except Exception as exc:
            logger.exception("AuthWorker error")
            self.error.emit(str(exc))
            self.character_state.emit("error")
        finally:
            loop.close()

    async def _auth(self) -> None:
        from features.auth.api import AuthService

        self.character_state.emit("process")
        self.log_message.emit("🔑 Подключение к Telegram...")

        # build_client — синхронный @staticmethod
        self._client = AuthService.build_client(self._cfg)

        # sign_in — async @staticmethod, возвращает User | None
        user = await AuthService.sign_in(
            self._client,
            phone_provider    = self._provide_phone,
            code_provider     = self._provide_code,
            password_provider = self._provide_password,
            log               = lambda m: self.log_message.emit(m),
        )

        # Отключаем client ЗДЕСЬ, в event loop воркера — это единственный безопасный способ
        # снять SQLite-блокировку сессии ДО того, как MainWindow запустит ChatsWorker.
        # Передавать живой client в MainWindow не нужно: ChatsWorker создаёт свой.
        try:
            await self._client.disconnect()
        except Exception:
            pass

        if user is None:
            self.auth_complete.emit(None, None)
            self.character_state.emit("idle")
        else:
            self.auth_complete.emit(None, user)   # client=None — уже отключён
            self.character_state.emit("success")

    # ── Поставщики ввода ──────────────────────────────────────────────────

    async def _provide_phone(self) -> Optional[str]:
        """Телефон берётся из cfg — не спрашиваем пользователя повторно."""
        phone = getattr(self._cfg, "phone", None) or ""
        if phone:
            self.log_message.emit(f"📞 Телефон из конфига: {phone}")
            return phone
        # Если по какой-то причине в cfg нет телефона — спрашиваем
        return await self._ask("Введите номер телефона", "Телефон", False)

    async def _provide_code(self) -> Optional[str]:
        return await self._ask(
            "Введите код из Telegram / SMS",
            "Код подтверждения",
            False,
        )

    async def _provide_password(self) -> Optional[str]:
        return await self._ask(
            "Введите облачный пароль (2FA)",
            "Двухфакторная аутентификация",
            True,
        )

    async def _ask(self, prompt: str, title: str, is_password: bool) -> Optional[str]:
        """
        Эмитирует request_input → UI показывает QInputDialog →
        provide_input() возвращает ответ → возвращаем в корутину.
        """
        self._input_ready = False
        self._input_value = None
        self.request_input.emit(prompt, title, is_password)
        while not self._input_ready:
            await asyncio.sleep(0.05)
        return self._input_value


# ══════════════════════════════════════════════════════════════════════════════
# AUTH SCREEN
# ══════════════════════════════════════════════════════════════════════════════

class AuthScreen(QWidget):
    """
    Экран авторизации (верхняя часть колонки 1).

    Сигналы:
        auth_complete(object, object)  — (TelegramClient, User) | (None, None)
        log_message(str)
        character_state(str)
        character_tip(str)

    Изменение в MainWindow:
        БЫЛО:  _on_auth_complete(self, user)
        СТАЛО: _on_auth_complete(self, client, user)
        client нужен для передачи в ChatsWorker / ParseWorker.
    """

    auth_complete   = Signal(object, object)
    log_message     = Signal(str)
    character_state = Signal(str)
    character_tip   = Signal(str)

    _STATUSES: dict[str, tuple[str, str]] = {
        "idle":    (OVERLAY2_HEX,             TEXT_SECONDARY),
        "process": (ACCENT_SOFT_ORANGE,        ACCENT_ORANGE),
        "success": ("rgba(0,200,83,0.15)",     COLOR_SUCCESS),
        "error":   ("rgba(255,77,77,0.15)",    COLOR_ERROR),
        "warning": ("rgba(255,170,0,0.15)",    COLOR_WARNING),
    }

    def __init__(self, cfg: AppConfig, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._cfg     = cfg
        self._worker:  Optional[AuthWorker]        = None
        self._checker: Optional[SessionCheckWorker] = None
        self._build_ui()
        self._check_existing_session()

    # ──────────────────────────────────────────────────────────────────────
    # UI
    # ──────────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        # Заголовок
        title = QLabel("🔑  API и вход")
        title.setFont(QFont(FONT_FAMILY, FONT_SIZE_SMALL, QFont.Weight.DemiBold))
        title.setStyleSheet(
            f"QLabel {{ color: {ACCENT_ORANGE}; background: transparent; }}"
        )
        layout.addWidget(title)

        # API ID
        layout.addWidget(self._field_label("API ID"))
        self._api_id = QLineEdit()
        self._api_id.setPlaceholderText("123456")
        self._api_id.setStyleSheet(QSS_INPUT)
        self._api_id.setFixedHeight(36)
        if v := getattr(self._cfg, "api_id", None):
            self._api_id.setText(str(v))
        layout.addWidget(self._api_id)

        # API Hash
        layout.addWidget(self._field_label("API Hash"))
        self._api_hash = PasswordLineEdit(placeholder="ваш hash")
        self._api_hash.setFixedHeight(36)
        if h := getattr(self._cfg, "api_hash", None):
            self._api_hash.setText(h)
        layout.addWidget(self._api_hash)

        # Телефон
        layout.addWidget(self._field_label("Номер телефона"))
        self._phone = QLineEdit()
        self._phone.setPlaceholderText("+79001234567")
        self._phone.setStyleSheet(QSS_INPUT)
        self._phone.setFixedHeight(36)
        self._phone.setText(getattr(self._cfg, "phone", "") or "")
        layout.addWidget(self._phone)

        # Кнопка входа
        self._login_btn = QPushButton("🔐  Войти")
        self._login_btn.setFixedHeight(40)
        self._login_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._login_btn.setStyleSheet(QSS_BUTTON_PRIMARY)
        self._login_btn.clicked.connect(self._start_auth)
        layout.addWidget(self._login_btn)

        # Статус
        self._status_lbl = QLabel("Не авторизован")
        self._status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_lbl.setFixedHeight(28)
        self._set_status("idle", "Не авторизован")
        layout.addWidget(self._status_lbl)

        # Инфо-блок
        layout.addWidget(self._make_info_block())

    def _field_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setFont(QFont(FONT_FAMILY, FONT_SIZE_SMALL))
        lbl.setStyleSheet(
            f"QLabel {{ color: {TEXT_SECONDARY}; background: transparent; }}"
        )
        return lbl

    def _make_info_block(self) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet(f"""
            QFrame {{
                background: {OVERLAY2_HEX};
                border: 1px solid {BORDER_HEX};
                border-radius: {RADIUS_MD}px;
            }}
            QFrame QLabel {{ background: transparent; }}
        """)
        fl = QVBoxLayout(frame)
        fl.setContentsMargins(12, 10, 12, 10)
        fl.setSpacing(6)

        hdr = QLabel("ℹ️  Как получить API ключи")
        hdr.setFont(QFont(FONT_FAMILY, FONT_SIZE_SMALL, QFont.Weight.DemiBold))
        hdr.setStyleSheet(f"color: {ACCENT_ORANGE};")
        fl.addWidget(hdr)

        body = QLabel(
            "Зайдите на my.telegram.org → API development tools.\n"
            "При первом входе придёт код подтверждения в Telegram.\n"
            "Если включена 2FA — потребуется облачный пароль."
        )
        body.setFont(QFont(FONT_FAMILY, FONT_SIZE_XS))
        body.setWordWrap(True)
        body.setStyleSheet(f"color: {TEXT_SECONDARY};")
        fl.addWidget(body)

        return frame

    # ──────────────────────────────────────────────────────────────────────
    # СТАТУС
    # ──────────────────────────────────────────────────────────────────────

    def _set_status(self, level: str, text: str) -> None:
        bg, fg = self._STATUSES.get(level, self._STATUSES["idle"])
        self._status_lbl.setText(text)
        self._status_lbl.setStyleSheet(f"""
            QLabel {{
                background: {bg};
                color: {fg};
                border-radius: {RADIUS_XS}px;
                padding: 0 10px;
                font-family: {FONT_FAMILY};
                font-size: {FONT_SIZE_XS}px;
                font-weight: 600;
            }}
        """)

    def _set_controls_enabled(self, enabled: bool) -> None:
        self._api_id.setEnabled(enabled)
        self._api_hash.setReadOnly(not enabled)
        self._phone.setEnabled(enabled)
        self._login_btn.setEnabled(enabled)

    # ──────────────────────────────────────────────────────────────────────
    # ПРОВЕРКА СЕССИИ
    # ──────────────────────────────────────────────────────────────────────

    def _check_existing_session(self) -> None:
        """Тихая проверка при старте. Если сессия жива — пропускаем форму."""
        # Блокируем кнопку на время проверки — предотвращает гонку SessionCheck ∩ AuthWorker
        self._set_controls_enabled(False)
        self._checker = SessionCheckWorker(self._cfg, parent=self)
        self._checker.session_valid.connect(self._on_session_restored)
        self._checker.log_message.connect(self.log_message)
        self._checker.finished.connect(self._on_checker_finished)
        self._checker.start()
        self.log_message.emit("🔍 Проверка сессии...")

    @Slot()
    def _on_checker_finished(self) -> None:
        """SessionCheckWorker завершился без валидной сессии — разблокируем форму."""
        # Если сессия была найдена, _on_session_restored уже заблокировал форму навсегда.
        # Разблокируем только если авторизация НЕ произошла.
        if self._status_lbl.text() in ("Не авторизован", "🔍 Проверка..."):
            self._set_controls_enabled(True)
            self._set_status("idle", "Не авторизован")

    @Slot(object, object)
    def _on_session_restored(self, client, user) -> None:
        name = getattr(user, "first_name", "пользователь")
        self._set_status("success", f"Сессия: {name}")
        # Форма остаётся заблокированной — повторный вход не нужен,
        # и предотвращает гонку AuthWorker ∩ ChatsWorker за сессионный файл
        self._set_controls_enabled(False)
        self.character_state.emit("success")
        self.character_tip.emit(f"Добро пожаловать, {name}! 👋")
        self.log_message.emit(f"✅ Сессия восстановлена: {name}")
        self.auth_complete.emit(client, user)

    # ──────────────────────────────────────────────────────────────────────
    # ПУБЛИЧНЫЙ API
    # ──────────────────────────────────────────────────────────────────────

    def reset(self) -> None:
        """
        Сбросить экран в исходное состояние для повторного входа.
        Вызывается из MainWindow после успешного выхода (logout).
        """
        # Остановить любые незавершённые воркеры
        for w in (self._checker, self._worker):
            if w is not None and w.isRunning():
                w.quit()
                w.wait(1000)
        self._checker = None
        self._worker  = None

        self._set_controls_enabled(True)
        self._set_status("idle", "Не авторизован")
        self.character_state.emit("idle")
        self.character_tip.emit("")

    # ──────────────────────────────────────────────────────────────────────
    # СЛОТЫ
    # ──────────────────────────────────────────────────────────────────────

    @Slot()
    def _start_auth(self) -> None:
        # Защита: не запускать AuthWorker пока SessionCheckWorker ещё держит сессионный файл
        if self._checker is not None and self._checker.isRunning():
            self.log_message.emit("⏳ Дождитесь завершения проверки сессии...")
            return

        api_id_text = self._api_id.text().strip()
        api_hash    = self._api_hash.text().strip()
        phone       = self._phone.text().strip()

        if not api_id_text.isdigit():
            QMessageBox.warning(self, "Ошибка", "API ID должен содержать только цифры")
            return
        if not api_hash:
            QMessageBox.warning(self, "Ошибка", "Введите API Hash")
            return
        if not phone:
            QMessageBox.warning(self, "Ошибка", "Введите номер телефона")
            return

        # Сохраняем в конфиг — phone_provider в воркере возьмёт отсюда.
        # api_id — СТРОКА (AppConfig.api_id: str), validate() делает api_id.strip().
        # Конвертацию в int делает cfg.api_id_int (property в AppConfig).
        self._cfg.api_id   = api_id_text   # str, НЕ int
        self._cfg.api_hash = api_hash
        self._cfg.phone    = phone

        self._set_controls_enabled(False)
        self._set_status("process", "Подключение...")
        self.character_state.emit("process")
        self.character_tip.emit("Подключаюсь к Telegram...")
        self.log_message.emit(f"📞 Авторизация: {phone}")

        self._worker = AuthWorker(self._cfg, parent=self)
        self._worker.log_message.connect(self.log_message)
        self._worker.auth_complete.connect(self._on_auth_complete)
        self._worker.error.connect(self._on_auth_error)
        self._worker.request_input.connect(self._on_input_request)
        self._worker.character_state.connect(self.character_state)
        self._worker.start()

    @Slot(object, object)
    def _on_auth_complete(self, client, user) -> None:
        if user is None:
            self._set_controls_enabled(True)
            self._set_status("warning", "Отменено")
            self.character_state.emit("idle")
            self.character_tip.emit("Авторизация отменена")
            self.log_message.emit("⚠️ Авторизация отменена пользователем")
            return

        name = getattr(user, "first_name", "пользователь")
        self._set_status("success", f"Авторизован: {name}")
        self.character_state.emit("success")
        self.character_tip.emit(f"Привет, {name}! 👋")
        self.log_message.emit(f"✅ Авторизован: {name}")
        logger.info("Авторизация: %s (id=%s)", name, getattr(user, "id", "?"))

        # Сохраняем api_id / api_hash / phone на диск — при следующем запуске
        # поля формы будут заполнены автоматически и сессия подтянется без ввода.
        try:
            from config import save_config
            save_config(self._cfg)
            logger.debug("auth: config saved to disk")
        except Exception as exc:
            logger.warning("auth: не удалось сохранить config: %s", exc)

        self.auth_complete.emit(client, user)

    @Slot(str)
    def _on_auth_error(self, error_msg: str) -> None:
        self._set_controls_enabled(True)
        self._set_status("error", "Ошибка входа")
        self.character_state.emit("error")
        self.character_tip.emit("Ошибка авторизации")
        self.log_message.emit(f"❌ {error_msg}")
        QMessageBox.critical(
            self, "Ошибка авторизации",
            f"Не удалось войти в Telegram:\n\n{error_msg}"
        )

    @Slot(str, str, bool)
    def _on_input_request(self, prompt: str, title: str, is_password: bool) -> None:
        self.character_tip.emit(prompt)
        self.log_message.emit(f"⌨️ Требуется ввод: {prompt}")
        echo = QLineEdit.EchoMode.Password if is_password else QLineEdit.EchoMode.Normal
        text, ok = QInputDialog.getText(self, title, prompt, echo)
        if self._worker:
            self._worker.provide_input(text if (ok and text) else None)
