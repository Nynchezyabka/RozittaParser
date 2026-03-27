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

from PySide6.QtCore import Qt, Signal, Slot, QThread, QUrl
from PySide6.QtGui import QFont, QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QFrame, QFileDialog, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QMessageBox, QPushButton, QScrollArea, QSpinBox, QVBoxLayout, QWidget, QGridLayout
)
from config import AppConfig
from core.ui_shared.styles import (
    ACCENT_ORANGE, ACCENT_SOFT_ORANGE,
    COLOR_SUCCESS, COLOR_ERROR, COLOR_WARNING,
    TEXT_PRIMARY, TEXT_SECONDARY,
    OVERLAY_HEX, OVERLAY2_HEX, BORDER_HEX,
    RADIUS_MD, RADIUS_XS,
    FONT_FAMILY, FONT_SIZE_SMALL, FONT_SIZE_XS,
    QSS_INPUT, QSS_BUTTON_PRIMARY,
)
from core.ui_shared.widgets import PasswordLineEdit, ToggleSwitch

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
        except ConnectionError as exc:
            self.log_message.emit(f"❌ {exc}")
        except Exception:
            pass  # нет сессии — молча ничего не делаем
        finally:
            loop.close()

    async def _check(self):
        from features.auth.api import AuthService
        client = None
        try:
            self.log_message.emit("🔌 Подключаюсь к Telegram...")
            client = AuthService.build_client(self._cfg)
            await client.connect()
            self.log_message.emit("🔍 Проверяю сессию...")
            if await client.is_user_authorized():
                self.log_message.emit("✅ Сессия активна, получаю данные...")
                user = await client.get_me()
                if user is not None:
                    return None, user
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
        # Может бросить ConnectionError если прокси включён но недоступен
        try:
            self._client = AuthService.build_client(self._cfg)
        except ConnectionError as exc:
            self.log_message.emit(f"❌ {exc}")
            self.error.emit(str(exc))
            self.character_state.emit("error")
            return

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
        self._worker:       Optional[AuthWorker]        = None
        self._checker:      Optional[SessionCheckWorker] = None
        self._tdata_worker: Optional[TdataImportWorker]  = None
        self._build_ui()
        self._check_existing_session()

    # ──────────────────────────────────────────────────────────────────────
    # UI
    # ──────────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        container = QWidget()
        container.setStyleSheet("background: transparent;")
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

        # ── Прокси (SOCKS5 / MTProto) ────────────────────────────────────
        proxy_frame = QFrame()
        proxy_frame.setStyleSheet(f"""
            QFrame {{
                background: {OVERLAY2_HEX};
                border: 1px solid {BORDER_HEX};
                border-radius: {RADIUS_MD}px;
            }}
            QFrame QLabel {{ background: transparent; color: {TEXT_SECONDARY}; }}
        """)
        pfl = QVBoxLayout(proxy_frame)
        pfl.setContentsMargins(10, 8, 10, 8)
        pfl.setSpacing(6)

        # Строка: заголовок + тоггл
        proxy_row = QHBoxLayout()
        proxy_lbl = QLabel("🔌  Прокси")
        proxy_lbl.setFont(QFont(FONT_FAMILY, FONT_SIZE_XS))
        proxy_row.addWidget(proxy_lbl)
        proxy_row.addStretch()
        self._proxy_toggle = ToggleSwitch(
            checked=getattr(self._cfg, "proxy_enabled", False)
        )
        proxy_row.addWidget(self._proxy_toggle)
        pfl.addLayout(proxy_row)

        # Переключатель типа: SOCKS5 / MTProto
        type_row = QHBoxLayout()
        type_row.setSpacing(6)
        self._proxy_socks5_btn = QPushButton("SOCKS5 (Tor)")
        self._proxy_mtproto_btn = QPushButton("MTProto")
        for btn in (self._proxy_socks5_btn, self._proxy_mtproto_btn):
            btn.setCheckable(True)
            btn.setFixedHeight(24)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    border: 1px solid {BORDER_HEX};
                    border-radius: 4px;
                    color: {TEXT_SECONDARY};
                    font-size: 11px;
                    padding: 0 8px;
                }}
                QPushButton:checked {{
                    background: {ACCENT_ORANGE};
                    color: #000;
                    border-color: {ACCENT_ORANGE};
                }}
            """)
        is_mtproto = getattr(self._cfg, "proxy_type", "socks5") == "mtproto"
        self._proxy_socks5_btn.setChecked(not is_mtproto)
        self._proxy_mtproto_btn.setChecked(is_mtproto)
        type_row.addWidget(self._proxy_socks5_btn)
        type_row.addWidget(self._proxy_mtproto_btn)
        type_row.addStretch()
        pfl.addLayout(type_row)

        # Поля хост + порт (для SOCKS5)
        host_row = QHBoxLayout()
        host_row.setSpacing(6)
        self._proxy_host_auth = QLineEdit(getattr(self._cfg, "proxy_host", "127.0.0.1"))
        self._proxy_host_auth.setPlaceholderText("127.0.0.1")
        self._proxy_host_auth.setFixedHeight(28)
        self._proxy_host_auth.setStyleSheet(QSS_INPUT)
        self._proxy_port_auth = QSpinBox()
        self._proxy_port_auth.setRange(1, 65535)
        self._proxy_port_auth.setValue(getattr(self._cfg, "proxy_port", 9050))
        self._proxy_port_auth.setFixedHeight(28)
        self._proxy_port_auth.setFixedWidth(80)
        self._proxy_port_auth.setStyleSheet(QSS_INPUT)
        host_row.addWidget(self._proxy_host_auth, 1)
        host_row.addWidget(self._proxy_port_auth)
        pfl.addLayout(host_row)

        # Поле для MTProto ссылки (t.me/proxy?...)
        self._proxy_link_edit = QLineEdit(
            f"https://t.me/proxy?server={self._cfg.proxy_host}&port={self._cfg.proxy_port}&secret={getattr(self._cfg, 'proxy_secret', '')}"
            if is_mtproto and getattr(self._cfg, "proxy_secret", "") else ""
        )
        self._proxy_link_edit.setPlaceholderText("https://t.me/proxy?server=...&port=...&secret=...")
        self._proxy_link_edit.setFixedHeight(28)
        self._proxy_link_edit.setStyleSheet(QSS_INPUT)
        pfl.addWidget(self._proxy_link_edit)

        # Показываем/скрываем нужные поля
        def _refresh_proxy_ui():
            mtproto = self._proxy_mtproto_btn.isChecked()
            self._proxy_host_auth.setVisible(not mtproto)
            self._proxy_port_auth.setVisible(not mtproto)
            self._proxy_link_edit.setVisible(mtproto)
            if mtproto:
                self._proxy_socks5_btn.setChecked(False)
            else:
                self._proxy_mtproto_btn.setChecked(False)

        self._proxy_socks5_btn.clicked.connect(lambda: (
            self._proxy_mtproto_btn.setChecked(False),
            self._proxy_socks5_btn.setChecked(True),
            _refresh_proxy_ui(),
        ))
        self._proxy_mtproto_btn.clicked.connect(lambda: (
            self._proxy_socks5_btn.setChecked(False),
            self._proxy_mtproto_btn.setChecked(True),
            _refresh_proxy_ui(),
        ))
        _refresh_proxy_ui()

        def _save_proxy_auth():
            from features.auth.api import AuthService
            self._cfg.proxy_enabled = self._proxy_toggle.isChecked()
            if self._proxy_mtproto_btn.isChecked():
                self._cfg.proxy_type = "mtproto"
                # Пробуем распарсить ссылку
                link = self._proxy_link_edit.text().strip()
                parsed = AuthService.parse_proxy_link(link) if link else None
                if parsed:
                    self._cfg.proxy_host   = parsed["host"]
                    self._cfg.proxy_port   = parsed["port"]
                    self._cfg.proxy_secret = parsed["secret"]
            else:
                self._cfg.proxy_type   = "socks5"
                self._cfg.proxy_host   = self._proxy_host_auth.text().strip() or "127.0.0.1"
                self._cfg.proxy_port   = self._proxy_port_auth.value()
                self._cfg.proxy_secret = ""
            try:
                from config import save_config
                save_config(self._cfg)
            except Exception:
                pass

        self._proxy_toggle.toggled.connect(_save_proxy_auth)
        self._proxy_host_auth.editingFinished.connect(_save_proxy_auth)
        self._proxy_port_auth.valueChanged.connect(_save_proxy_auth)
        self._proxy_link_edit.editingFinished.connect(_save_proxy_auth)

        layout.addWidget(proxy_frame)

        # Кнопка входа
        self._login_btn = QPushButton("🔐  Войти")
        self._login_btn.setFixedHeight(40)
        self._login_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._login_btn.setStyleSheet(QSS_BUTTON_PRIMARY)
        self._login_btn.clicked.connect(self._start_auth)
        layout.addWidget(self._login_btn)

        # Разделитель
        sep_lbl = QLabel("— или —")
        sep_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sep_lbl.setStyleSheet(
            f"QLabel {{ color: {TEXT_SECONDARY}; font-size: {FONT_SIZE_XS}px;"
            f" background: transparent; }}"
        )
        layout.addWidget(sep_lbl)

        # Кнопка импорта из Telegram Desktop
        self._tdata_btn = QPushButton("🖥️  Импорт из Telegram Desktop")
        self._tdata_btn.setFixedHeight(36)
        self._tdata_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._tdata_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {OVERLAY2_HEX};
                border: 1px solid {BORDER_HEX};
                border-radius: {RADIUS_MD}px;
                color: {TEXT_SECONDARY};
                font-family: {FONT_FAMILY};
                font-size: {FONT_SIZE_SMALL}px;
            }}
            QPushButton:hover:enabled {{
                background-color: {OVERLAY_HEX};
                color: {TEXT_PRIMARY};
                border-color: {ACCENT_ORANGE};
            }}
            QPushButton:disabled {{
                color: rgba(255,255,255,0.25);
            }}
        """)
        self._tdata_btn.clicked.connect(self._start_tdata_import)
        layout.addWidget(self._tdata_btn)

        # Статус
        self._status_lbl = QLabel("Не авторизован")
        self._status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_lbl.setFixedHeight(28)
        self._set_status("idle", "Не авторизован")
        layout.addWidget(self._status_lbl)

        # Инфо-блок
        layout.addWidget(self._make_info_block())
        layout.addStretch()

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

        # Ссылка my.telegram.org — кликабельная
        link = QLabel(
            '<a href="https://my.telegram.org" style="color: #FF9500;">'
            'my.telegram.org</a> → API development tools.'
        )
        link.setFont(QFont(FONT_FAMILY, FONT_SIZE_XS))
        link.setOpenExternalLinks(True)
        link.setTextFormat(Qt.TextFormat.RichText)
        link.setToolTip("Открыть my.telegram.org в браузере")
        fl.addWidget(link)

        body = QLabel(
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
        self._tdata_btn.setEnabled(enabled)

    # ──────────────────────────────────────────────────────────────────────
    # TDATA IMPORT
    # ──────────────────────────────────────────────────────────────────────

    @Slot()
    def _start_tdata_import(self) -> None:
        """Открывает диалог выбора папки tdata и запускает импорт."""
        from features.auth.api import AuthService

        # Предлагаем автодетектированный путь как начальный
        default_path = AuthService.detect_tdata_path() or ""

        tdata_path = QFileDialog.getExistingDirectory(
            self,
            "Выберите папку tdata Telegram Desktop",
            default_path or "",
        )
        if not tdata_path:
            return  # пользователь закрыл диалог

        self._set_controls_enabled(False)
        self._set_status("process", "Импорт сессии...")
        self.character_state.emit("process")
        self.character_tip.emit("Читаю данные Telegram Desktop...")
        self.log_message.emit(f"🖥️ Импорт из: {tdata_path}")

        self._tdata_worker = TdataImportWorker(tdata_path, self._cfg, parent=self)
        self._tdata_worker.log_message.connect(self.log_message)
        self._tdata_worker.import_complete.connect(self._on_tdata_complete,
                                                   Qt.UniqueConnection)
        self._tdata_worker.error.connect(self._on_tdata_error,
                                         Qt.UniqueConnection)
        self._tdata_worker.character_state.connect(self.character_state)
        self._tdata_worker.start()

    @Slot(object, object)
    def _on_tdata_complete(self, _client, user) -> None:
        if user is None:
            self._set_controls_enabled(True)
            self._set_status("error", "Импорт не дал результата")
            return

        name = getattr(user, "first_name", "пользователь")
        self._set_status("success", f"Импортирован: {name}")
        self.character_state.emit("success")
        self.character_tip.emit(f"Добро пожаловать, {name}! 👋")
        self.log_message.emit(f"✅ Сессия импортирована: {name}")
        self.auth_complete.emit(None, user)

    @Slot(str)
    def _show_install_dialog(self, title: str, text: str, command: str) -> None:
        """
        Диалог с командой установки библиотеки и кнопкой «Скопировать».

        Args:
            title:   Заголовок окна.
            text:    HTML-текст пояснения (над командой).
            command: Команда pip install ... для копирования.
        """
        from PySide6.QtWidgets import QDialog, QHBoxLayout
        from PySide6.QtGui import QClipboard

        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        dlg.setMinimumWidth(420)
        dlg.setStyleSheet(f"""
            QDialog {{
                background: #1a1d26;
            }}
            QLabel {{ color: #e0e0e0; font-family: {FONT_FAMILY}; background: transparent; }}
            QPushButton {{
                border-radius: {RADIUS_MD}px;
                font-family: {FONT_FAMILY};
                font-size: 12px;
                padding: 6px 16px;
            }}
        """)

        lay = QVBoxLayout(dlg)
        lay.setSpacing(12)
        lay.setContentsMargins(20, 20, 20, 20)

        # Пояснительный текст
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(lbl)

        # Блок с командой
        cmd_frame = QFrame()
        cmd_frame.setStyleSheet(f"""
            QFrame {{
                background: #0d0f14;
                border: 1px solid {BORDER_HEX};
                border-radius: {RADIUS_MD}px;
            }}
            QFrame QLabel {{ color: {ACCENT_ORANGE}; font-size: 13px;
                             font-family: 'Consolas', monospace; background: transparent; }}
        """)
        cmd_lay = QHBoxLayout(cmd_frame)
        cmd_lay.setContentsMargins(12, 8, 8, 8)
        cmd_lay.setSpacing(8)

        cmd_lbl = QLabel(command)
        cmd_lbl.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        cmd_lay.addWidget(cmd_lbl, 1)

        copy_btn = QPushButton("📋 Скопировать")
        copy_btn.setFixedHeight(30)
        copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        copy_btn.setStyleSheet(f"""
            QPushButton {{
                background: {ACCENT_SOFT_ORANGE};
                border: 1px solid {ACCENT_ORANGE};
                color: {ACCENT_ORANGE};
                font-weight: 600;
            }}
            QPushButton:hover {{ background: {ACCENT_ORANGE}; color: #000; }}
        """)

        def _copy():
            QApplication.clipboard().setText(command)
            copy_btn.setText("✅ Скопировано!")
            copy_btn.setEnabled(False)

        copy_btn.clicked.connect(_copy)
        cmd_lay.addWidget(copy_btn)
        lay.addWidget(cmd_frame)

        # Примечание
        note = QLabel("После установки перезапустите приложение.")
        note.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 11px;")
        lay.addWidget(note)

        # Кнопка закрыть
        close_btn = QPushButton("Закрыть")
        close_btn.setFixedHeight(34)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(QSS_BUTTON_PRIMARY)
        close_btn.clicked.connect(dlg.accept)
        lay.addWidget(close_btn)

        dlg.exec()

    def _on_tdata_error(self, error_msg: str) -> None:
        self._set_controls_enabled(True)
        self._set_status("error", "Ошибка импорта")
        self.character_state.emit("error")
        self.character_tip.emit("Ошибка импорта tdata")
        self.log_message.emit(f"❌ {error_msg}")

        # Проверяем нужна ли установка opentele
        if "opentele" in error_msg.lower() or "pip install" in error_msg:
            self._show_install_dialog(
                title   = "Требуется библиотека opentele",
                text    = (
                    "Для импорта из Telegram Desktop нужна библиотека <b>opentele</b>.<br><br>"
                    "Установите её командой и перезапустите приложение:"
                ),
                command = "pip install opentele",
            )
        else:
            QMessageBox.warning(
                self,
                "Ошибка импорта",
                f"Не удалось импортировать сессию:\n\n{error_msg}\n\n"
                "Убедитесь что:\n"
                "• Telegram Desktop закрыт\n"
                "• Выбрана правильная папка tdata\n"
                "• Папка не зашифрована паролем",
            )

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
        if getattr(self._cfg, "proxy_enabled", False):
            self.log_message.emit(
                f"🔌 Соединение через Tor ({self._cfg.proxy_host}:{self._cfg.proxy_port}) — "
                "может занять 1-2 минуты, подождите..."
            )

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
        for w in (self._checker, self._worker, self._tdata_worker):
            if w is not None and w.isRunning():
                w.quit()
                w.wait(1000)
        self._checker      = None
        self._worker       = None
        self._tdata_worker = None

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


# ══════════════════════════════════════════════════════════════════════════════
# TDATA IMPORT WORKER
# ══════════════════════════════════════════════════════════════════════════════

class TdataImportWorker(QThread):
    """
    QThread-воркер импорта сессии из папки tdata Telegram Desktop.

    Вызывает AuthService.import_from_tdata() в собственном event loop.
    Не трогает основной session-файл до успешного завершения.

    Сигналы:
        log_message(str)
        import_complete(object, object)  — (None, User) при успехе
        error(str)
        character_state(str)
    """

    log_message     = Signal(str)
    import_complete = Signal(object, object)  # (None, user)
    error           = Signal(str)
    character_state = Signal(str)

    def __init__(self, tdata_path: str, cfg: AppConfig,
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._tdata_path = tdata_path
        self._cfg        = cfg

    def run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._import())
        except Exception as exc:
            logger.exception("TdataImportWorker error")
            self.error.emit(str(exc))
            self.character_state.emit("error")
        finally:
            loop.close()

    async def _import(self) -> None:
        from features.auth.api import AuthService

        self.character_state.emit("process")
        self.log_message.emit("🖥️ Импорт сессии из Telegram Desktop...")

        user = await AuthService.import_from_tdata(
            tdata_path  = self._tdata_path,
            session_out = self._cfg.session_path,
            log         = self.log_message.emit,
        )

        if user is None:
            self.error.emit("Импорт не дал результата")
            self.character_state.emit("error")
            return

        # Сохраняем конфиг — теперь сессия активна
        try:
            from config import save_config
            save_config(self._cfg)
        except Exception as exc:
            logger.warning("TdataImportWorker: save_config failed: %s", exc)

        self.character_state.emit("success")
        self.import_complete.emit(None, user)
