"""
ui/screens/auth_screen.py — Экран авторизации в Telegram

Workflow:
    1. Проверка сессии (check_session)
    2. Если нет сессии → запрос телефона
    3. Ввод кода из SMS/Telegram
    4. Опционально: ввод 2FA пароля
    5. auth_success Signal → переход к ChatsScreen

UI компоненты:
    - ModernCard с полями ввода
    - PrimaryButton для отправки
    - Индикатор загрузки
    - Статус авторизации
"""

import logging
from typing import Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QInputDialog, QMessageBox, QSpacerItem, QSizePolicy
)
from PySide6.QtCore import Qt, Signal, Slot

from config import AppConfig
from features.auth.ui import AuthWorker
from ui_shared.widgets import ModernCard, PrimaryButton, GhostButton, SectionLabel
from ui_shared.styles import ACCENT_PINK, ACCENT_LAVENDER, TEXT_MUTED, ACCENT_AMBER, ACCENT_CORAL

logger = logging.getLogger(__name__)


# ==============================================================================
# AuthScreen
# ==============================================================================

class AuthScreen(QWidget):
    """
    Экран авторизации в Telegram.

    Интегрирует AuthWorker и обрабатывает callback-запросы на ввод данных.

    Signals:
        auth_success: Авторизация завершена успешно.
        log_message: Сообщение для лога (str).
        character_state: Состояние персонажа (str).
    """

    auth_success = Signal()
    log_message = Signal(str)
    character_state = Signal(str)

    def __init__(self, cfg: AppConfig, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.cfg = cfg
        self._worker: Optional[AuthWorker] = None

        self._setup_ui()
        self._check_existing_session()

    # ------------------------------------------------------------------
    # UI Setup
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        """Создаёт UI экрана авторизации."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(20)

        # Заголовок
        title = SectionLabel("🔐 Авторизация в Telegram")
        layout.addWidget(title)

        # Карточка авторизации
        self.card = ModernCard("📱 Вход в аккаунт", "🔑")
        card_layout = QVBoxLayout()

        # Поле телефона
        phone_label = QLabel("Номер телефона:")
        phone_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 13px;")
        self.phone_input = QLineEdit()
        self.phone_input.setPlaceholderText("+79991234567")
        self.phone_input.setText(self.cfg.phone or "")
        self.phone_input.setStyleSheet("""
            QLineEdit {
                padding: 12px;
                font-size: 14px;
                border-radius: 8px;
                background: rgba(255, 255, 255, 0.05);
                border: 1px solid rgba(255, 255, 255, 0.1);
                color: white;
            }
            QLineEdit:focus {
                border: 1px solid """ + ACCENT_LAVENDER + """;
                background: rgba(255, 255, 255, 0.08);
            }
        """)

        # Кнопка входа
        self.login_btn = PrimaryButton("Войти")
        self.login_btn.clicked.connect(self._start_auth)

        # Статус авторизации (QLabel вместо StatusBadge — StatusBadge для типов чатов)
        self.status_badge = QLabel("Не авторизован")
        self.status_badge.setAlignment(Qt.AlignCenter)
        self._set_status_style("warning")

        card_layout.addWidget(phone_label)
        card_layout.addWidget(self.phone_input)
        card_layout.addSpacing(10)
        card_layout.addWidget(self.login_btn)
        card_layout.addSpacing(10)
        card_layout.addWidget(self.status_badge)

        self.card.add_layout(card_layout)
        layout.addWidget(self.card)

        # Информационная карточка
        info_card = ModernCard("ℹ️ Информация", "💡")
        info_text = QLabel(
            "При первом входе Telegram отправит код подтверждения.\n"
            "Если включена двухфакторная аутентификация (2FA),\n"
            "потребуется ввести пароль облачного доступа."
        )
        info_text.setWordWrap(True)
        info_text.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 13px; line-height: 1.6;")
        info_card.add_widget(info_text)
        layout.addWidget(info_card)

        layout.addStretch()

    # ------------------------------------------------------------------
    # Вспомогательные методы UI
    # ------------------------------------------------------------------

    _STATUS_STYLES: dict = {
        "warning": ("rgba(255,179,71,40)",  "#FFB347"),
        "info":    ("rgba(166,130,255,40)", "#A682FF"),
        "success": ("rgba(107,255,142,40)", "#6BFF8E"),
        "error":   ("rgba(255,122,107,40)", "#FF7A6B"),
    }

    def _set_status_style(self, status: str) -> None:
        """Обновляет стиль статус-лейбла по ключу: warning/info/success/error."""
        bg, fg = self._STATUS_STYLES.get(status, self._STATUS_STYLES["warning"])
        self.status_badge.setStyleSheet(
            f"background: {bg}; color: {fg}; border-radius: 6px; "
            f"font-size: 11px; font-weight: 600; padding: 4px 10px;"
        )

    # ------------------------------------------------------------------
    # Проверка существующей сессии
    # ------------------------------------------------------------------

    def _check_existing_session(self) -> None:
        """Проверяет валидность существующей сессии при загрузке."""
        self.log_message.emit("🔍 Проверка существующей сессии...")
        # TODO: Запустить AuthWorker в режиме check_session
        # Пока просто логируем
        logger.info("AuthScreen: проверка сессии (TODO)")

    # ------------------------------------------------------------------
    # Slots — управление workflow
    # ------------------------------------------------------------------

    @Slot()
    def _start_auth(self) -> None:
        """Запускает процесс авторизации."""
        phone = self.phone_input.text().strip()
        if not phone:
            QMessageBox.warning(self, "Ошибка", "Введите номер телефона")
            return

        # Сохраняем телефон в конфиг
        self.cfg.phone = phone

        self.log_message.emit(f"📞 Начинаем авторизацию: {phone}")
        self.login_btn.setEnabled(False)
        self.status_badge.setText("Подключение...")
        self._set_status_style("info")
        self.character_state.emit("working")

        # Создаём и запускаем воркер
        self._worker = AuthWorker(self.cfg, parent=self)
        self._worker.log_message.connect(self.log_message.emit)
        self._worker.auth_complete.connect(self._on_auth_complete)
        self._worker.error.connect(self._on_auth_error)
        self._worker.request_input.connect(self._on_input_request)
        self._worker.character_state.connect(self.character_state.emit)
        self._worker.start()

    @Slot(object)
    def _on_auth_complete(self, user):
        """Обработка успешной авторизации."""
        if user is None:
            self.log_message.emit("⚠️ Авторизация отменена пользователем")
            self.login_btn.setEnabled(True)
            self.status_badge.setText("Не авторизован")
            self._set_status_style("warning")
            self.character_state.emit("idle")
            return

        self.log_message.emit(f"✅ Авторизация успешна: {user.first_name}")
        self.status_badge.setText(f"Авторизован: {user.first_name}")
        self._set_status_style("success")
        self.character_state.emit("success")

        logger.info("Авторизация завершена: %s (id=%d)", user.first_name, user.id)

        # Уведомляем MainWindow
        self.auth_success.emit()

    @Slot(str)
    def _on_auth_error(self, error_msg: str):
        """Обработка ошибки авторизации."""
        self.log_message.emit(f"❌ Ошибка авторизации: {error_msg}")
        self.login_btn.setEnabled(True)
        self.status_badge.setText("Ошибка")
        self._set_status_style("error")
        self.character_state.emit("error")

        QMessageBox.critical(
            self,
            "Ошибка авторизации",
            f"Не удалось войти в Telegram:\n\n{error_msg}"
        )

    @Slot(str, str, bool)
    def _on_input_request(self, prompt: str, window_title: str, is_password: bool):
        """Обработка запроса на ввод данных (код/пароль)."""
        self.log_message.emit(f"⌨️ Требуется ввод: {prompt}")

        if is_password:
            text, ok = QInputDialog.getText(
                self,
                window_title,
                prompt,
                QLineEdit.EchoMode.Password
            )
        else:
            text, ok = QInputDialog.getText(
                self,
                window_title,
                prompt,
                QLineEdit.EchoMode.Normal
            )

        if ok and text:
            # Передаём введённое значение обратно в воркер
            if self._worker:
                self._worker.provide_input(text)
        else:
            # Пользователь отменил ввод
            if self._worker:
                self._worker.provide_input(None)
