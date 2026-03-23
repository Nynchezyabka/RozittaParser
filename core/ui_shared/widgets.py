"""
FILE: core/ui_shared/widgets.py

Переиспользуемые UI-компоненты Rozitta Parser.
Источник: Rozitta_prototype.html

Компоненты:
  - HeaderBar          — шапка с логотипом и степпером
  - StepperWidget      — навигация по шагам (1→2→3→4)
  - ModernCard         — glassmorphism-карточка (контейнер)
  - SectionTitle       — заголовок раздела внутри карточки (с иконкой)
  - ToggleSwitch       — анимированный переключатель on/off
  - MediaButton        — кнопка-тайл медиатипа (фото/видео/голос...)
  - ChipButton         — pill-кнопка с иконкой ✓ (recognition chips)
  - SplitModeButton    — кнопка режима разбивки документа
  - FilterButton       — кнопка фильтра лога (All/Info/Success/...)
  - UserTag            — тег пользователя (checkable)
  - RozittaWidget      — блок с аватаром и подсказкой персонажа
  - LogWidget          — виджет журнала (вывод + фильтры + кнопки)
  - PasswordLineEdit   — поле ввода с кнопкой показа пароля

ПРАВИЛО: Только PySide6. Никакой бизнес-логики. Связь через Signal/Slot.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import (
    Qt, Signal, QPropertyAnimation, QEasingCurve,
    QRect, QSize, Property, QObject,
)
from PySide6.QtGui import (
    QColor, QPainter, QPainterPath, QFont, QLinearGradient,
    QFontDatabase, QTextCursor, QIcon,
)
from PySide6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QHBoxLayout,
    QVBoxLayout, QSizePolicy, QLineEdit, QTextEdit,
    QScrollArea, QGraphicsDropShadowEffect, QApplication,
)

from core.ui_shared.styles import (
    # Цвета
    BG_PRIMARY, ACCENT_ORANGE, ACCENT_PINK, ACCENT_SOFT_ORANGE,
    ACCENT_SOFT_PINK, TEXT_PRIMARY, TEXT_SECONDARY, TEXT_DISABLED,
    OVERLAY_HEX, OVERLAY2_HEX, BORDER_HEX,
    COLOR_SUCCESS, COLOR_ERROR, COLOR_WARNING,
    # Размеры
    RADIUS_LG, RADIUS_MD, RADIUS_SM, RADIUS_XS,
    FONT_FAMILY, FONT_SIZE_H1, FONT_SIZE_H2, FONT_SIZE_BODY,
    FONT_SIZE_SMALL, FONT_SIZE_XS,
    # QSS блоки
    QSS_BUTTON_PRIMARY, QSS_BUTTON_SECONDARY, QSS_BUTTON_BASE,
    QSS_BUTTON_ICON, QSS_INPUT, QSS_LOG_OUTPUT, QSS_PROGRESS,
    QSS_FILTER_BUTTON, QSS_SCROLL_AREA,
    QSS_STEPPER_NUMBER_ACTIVE, QSS_STEPPER_NUMBER_INACTIVE,
    QSS_STEPPER_STEP_ACTIVE, QSS_STEPPER_STEP_INACTIVE,
    # Утилиты
    apply_style,
)


# ══════════════════════════════════════════════════════════════════════════════
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ══════════════════════════════════════════════════════════════════════════════

def _shadow(widget: QWidget,
            blur: int = 24,
            x_offset: int = 0,
            y_offset: int = 8,
            alpha: int = 100) -> None:
    """Добавляет QGraphicsDropShadowEffect к виджету."""
    eff = QGraphicsDropShadowEffect(widget)
    eff.setBlurRadius(blur)
    eff.setOffset(x_offset, y_offset)
    eff.setColor(QColor(0, 0, 0, alpha))
    widget.setGraphicsEffect(eff)


def _font(size: int, weight: int = QFont.Weight.Normal) -> QFont:
    f = QFont(FONT_FAMILY, size)
    f.setWeight(weight)
    return f


# ══════════════════════════════════════════════════════════════════════════════
# PASSWORD LINE EDIT
# ══════════════════════════════════════════════════════════════════════════════

class PasswordLineEdit(QWidget):
    """
    Поле ввода пароля с кнопкой показа/скрытия (иконка глаза).
    Эмитирует textChanged(str) — как стандартный QLineEdit.

    Пример:
        field = PasswordLineEdit(placeholder="ваш hash")
        field.textChanged.connect(on_hash_changed)
        value = field.text()
    """

    textChanged = Signal(str)

    def __init__(self, placeholder: str = "", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._build_ui(placeholder)

    def _build_ui(self, placeholder: str) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._edit = QLineEdit()
        self._edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._edit.setPlaceholderText(placeholder)
        self._edit.setStyleSheet(QSS_INPUT)
        self._edit.textChanged.connect(self.textChanged)

        self._toggle_btn = QPushButton("👁")
        self._toggle_btn.setFixedSize(36, 36)
        self._toggle_btn.setCheckable(True)
        self._toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: none;
                color: {TEXT_SECONDARY};
                font-size: 16px;
                margin-left: -38px;
            }}
            QPushButton:hover {{ color: {TEXT_PRIMARY}; }}
        """)
        self._toggle_btn.toggled.connect(self._on_toggle)

        # Кнопку накладываем поверх поля через отступ справа в LineEdit
        self._edit.setStyleSheet(QSS_INPUT + f"""
            QLineEdit {{ padding-right: 36px; }}
        """)

        layout.addWidget(self._edit)
        layout.addWidget(self._toggle_btn)
        # Сдвигаем кнопку внутрь поля
        self._toggle_btn.setParent(self._edit)
        self._toggle_btn.move(
            self._edit.width() - 38,
            (self._edit.height() - 36) // 2
        )

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        if hasattr(self, "_toggle_btn") and hasattr(self, "_edit"):
            self._toggle_btn.move(
                self._edit.width() - 38,
                max(0, (self._edit.height() - 36) // 2),
            )

    def _on_toggle(self, checked: bool) -> None:
        mode = QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
        self._edit.setEchoMode(mode)
        self._toggle_btn.setText("🙈" if checked else "👁")

    def text(self) -> str:
        return self._edit.text()

    def setText(self, text: str) -> None:
        self._edit.setText(text)

    def setPlaceholderText(self, text: str) -> None:
        self._edit.setPlaceholderText(text)

    def setReadOnly(self, ro: bool) -> None:
        self._edit.setReadOnly(ro)


# ══════════════════════════════════════════════════════════════════════════════
# MODERN CARD  — glassmorphism контейнер
# ══════════════════════════════════════════════════════════════════════════════

class ModernCard(QFrame):
    """
    Glassmorphism-панель: тёмный фон, скруглённые углы, тонкая рамка, тень.
    Используется как контейнер для любого экрана.

    Пример:
        card = ModernCard(parent=self)
        layout = QVBoxLayout(card)
        layout.addWidget(some_widget)
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setStyleSheet(f"""
            ModernCard {{
                background-color: {OVERLAY_HEX};
                border: 1px solid {BORDER_HEX};
                border-radius: {RADIUS_LG}px;
            }}
        """)
        _shadow(self, blur=32, y_offset=8, alpha=100)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION TITLE  — заголовок раздела внутри карточки
# ══════════════════════════════════════════════════════════════════════════════

class SectionTitle(QWidget):
    """
    Строка «иконка + текст заголовка + опциональный описательный текст».
    Соответствует .card-title и .settings-section-title из прототипа.

    Пример:
        title = SectionTitle("🔑", "API и вход")
        title = SectionTitle("📥", "Медиафайлы", accent=True)
        title = SectionTitle("📁", "Разбивка", desc="единый / дни / месяцы")
    """

    def __init__(
        self,
        icon: str,
        text: str,
        desc: str = "",
        accent: bool = False,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 8)
        layout.setSpacing(8)

        # Иконка
        icon_label = QLabel(icon)
        icon_label.setFixedSize(26, 26)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if accent:
            icon_label.setStyleSheet(f"""
                QLabel {{
                    background: {ACCENT_SOFT_ORANGE};
                    border-radius: {RADIUS_MD}px;
                    font-size: 13px;
                }}
            """)
        else:
            icon_label.setStyleSheet(f"""
                QLabel {{
                    background: {ACCENT_SOFT_ORANGE};
                    border-radius: {RADIUS_MD}px;
                    font-size: 13px;
                }}
            """)
        layout.addWidget(icon_label)

        # Текст заголовка
        color = ACCENT_ORANGE if accent else TEXT_PRIMARY
        title_label = QLabel(text)
        title_label.setFont(_font(FONT_SIZE_BODY, QFont.Weight.DemiBold))
        title_label.setStyleSheet(f"QLabel {{ color: {color}; background: transparent; }}")
        layout.addWidget(title_label)

        # Описание (маленький текст справа)
        if desc:
            desc_label = QLabel(desc)
            desc_label.setFont(_font(FONT_SIZE_XS))
            desc_label.setStyleSheet(
                f"QLabel {{ color: {TEXT_SECONDARY}; background: transparent; }}"
            )
            layout.addWidget(desc_label)

        layout.addStretch()

        # Отступ снизу вместо HLine-разделителя:
        # QFrame.HLine рендерится поверх содержимого при вложенных layout,
        # создавая визуальный артефакт (перечёркивающую линию).
        self.setContentsMargins(0, 0, 0, 6)


# ══════════════════════════════════════════════════════════════════════════════
# TOGGLE SWITCH  — анимированный переключатель
# ══════════════════════════════════════════════════════════════════════════════

class ToggleSwitch(QWidget):
    """
    Кастомный toggle-переключатель: анимированный кружок на треке.
    Соответствует .toggle-switch из прототипа (40×20px).

    Signals:
        toggled(bool) — состояние изменилось

    Пример:
        sw = ToggleSwitch()
        sw.toggled.connect(lambda v: print("on" if v else "off"))
        sw.setChecked(True)
    """

    toggled = Signal(bool)

    _TRACK_W = 40
    _TRACK_H = 20
    _KNOB_D  = 16   # диаметр кружка

    def __init__(self, checked: bool = False, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._checked = checked
        # _knob_x: 0.0 = выкл, 1.0 = вкл (используем как float для анимации)
        self._knob_pos: float = 1.0 if checked else 0.0
        self.setFixedSize(self._TRACK_W, self._TRACK_H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        # Анимация через QPropertyAnimation
        self._anim = QPropertyAnimation(self, b"_knob_pos_prop", self)
        self._anim.setDuration(150)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutQuad)

    # ── Qt property для анимации ───────────────────────────────────────────
    def _get_knob_pos(self) -> float:
        return self._knob_pos

    def _set_knob_pos(self, v: float) -> None:
        self._knob_pos = v
        self.update()

    _knob_pos_prop = Property(float, _get_knob_pos, _set_knob_pos)

    # ── Отрисовка ─────────────────────────────────────────────────────────
    def paintEvent(self, event) -> None:  # type: ignore[override]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self._TRACK_W, self._TRACK_H
        r = h / 2

        # Трек
        track_color = QColor(ACCENT_ORANGE) if self._checked else QColor(OVERLAY_HEX)
        p.setBrush(track_color)
        p.setPen(QColor(BORDER_HEX))
        path = QPainterPath()
        path.addRoundedRect(0, 0, w, h, r, r)
        p.drawPath(path)

        # Кружок
        knob_travel = w - self._KNOB_D - 4
        knob_x = 2 + knob_travel * self._knob_pos
        p.setBrush(QColor("#ffffff"))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(
            int(knob_x), 2,
            self._KNOB_D, self._KNOB_D,
        )
        p.end()

    # ── Клик ──────────────────────────────────────────────────────────────
    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        self.setChecked(not self._checked)

    def setChecked(self, checked: bool) -> None:
        if self._checked == checked:
            return
        self._checked = checked
        target = 1.0 if checked else 0.0
        self._anim.stop()
        self._anim.setStartValue(self._knob_pos)
        self._anim.setEndValue(target)
        self._anim.start()
        self.toggled.emit(checked)

    def isChecked(self) -> bool:
        return self._checked


# ══════════════════════════════════════════════════════════════════════════════
# MEDIA BUTTON  — тайл медиатипа (Фото / Видео / Кружки / Голос / Файлы)
# ══════════════════════════════════════════════════════════════════════════════

class MediaButton(QPushButton):
    """
    Квадратная кнопка-тайл для выбора медиатипа.
    Соответствует .media-btn из прототипа.

    Пример:
        btn = MediaButton("📷", "Фото", media_type="photo")
        btn.toggled.connect(lambda on: ...)
        btn.setActive(True)
    """

    def __init__(
        self,
        icon: str,
        label: str,
        media_type: str = "",
        active: bool = True,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._media_type = media_type
        self._active = active
        self.setCheckable(True)
        self.setChecked(active)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 8, 4, 8)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._icon_lbl = QLabel(icon)
        self._icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon_lbl.setFont(_font(18))
        self._icon_lbl.setStyleSheet("background: transparent;")

        self._text_lbl = QLabel(label)
        self._text_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._text_lbl.setFont(_font(FONT_SIZE_XS))
        self._text_lbl.setStyleSheet("background: transparent;")

        layout.addWidget(self._icon_lbl)
        layout.addWidget(self._text_lbl)

        self.toggled.connect(self._refresh)
        self._refresh(active)

    @property
    def media_type(self) -> str:
        return self._media_type

    def setActive(self, active: bool) -> None:
        self.setChecked(active)

    def isActive(self) -> bool:
        return self.isChecked()

    def _refresh(self, checked: bool) -> None:
        if checked:
            self.setStyleSheet(f"""
                MediaButton, QPushButton {{
                    background-color: {ACCENT_SOFT_ORANGE};
                    border: 1px solid {ACCENT_ORANGE};
                    border-radius: {RADIUS_MD}px;
                    color: {ACCENT_ORANGE};
                }}
                MediaButton:hover, QPushButton:hover {{
                    background-color: {OVERLAY2_HEX};
                }}
            """)
            self._icon_lbl.setStyleSheet(
                f"color: {ACCENT_ORANGE}; background: transparent;"
            )
            self._text_lbl.setStyleSheet(
                f"color: {ACCENT_ORANGE}; background: transparent;"
            )
        else:
            self.setStyleSheet(f"""
                MediaButton, QPushButton {{
                    background-color: {OVERLAY2_HEX};
                    border: 1px solid {BORDER_HEX};
                    border-radius: {RADIUS_MD}px;
                    color: {TEXT_SECONDARY};
                }}
                MediaButton:hover, QPushButton:hover {{
                    background-color: {OVERLAY_HEX};
                }}
            """)
            self._icon_lbl.setStyleSheet(
                f"color: {TEXT_SECONDARY}; background: transparent;"
            )
            self._text_lbl.setStyleSheet(
                f"color: {TEXT_SECONDARY}; background: transparent;"
            )


# ══════════════════════════════════════════════════════════════════════════════
# CHIP BUTTON  — pill с иконкой ✓ (recognition chips)
# ══════════════════════════════════════════════════════════════════════════════

class ChipButton(QWidget):
    """
    Pill-кнопка с иконкой типа медиа и галочкой ✓ при активации.
    Соответствует .recognition-chip из прототипа.

    Signals:
        toggled(bool)

    Пример:
        chip = ChipButton("🎥", "Видео", media_type="video", active=True)
        chip.toggled.connect(lambda on: ...)
    """

    toggled = Signal(bool)

    def __init__(
        self,
        icon: str,
        label: str,
        media_type: str = "",
        active: bool = True,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._active = active
        self._media_type = media_type
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 5, 10, 5)
        layout.setSpacing(6)

        self._icon_lbl = QLabel(icon)
        self._icon_lbl.setFont(_font(14))
        self._icon_lbl.setStyleSheet("background: transparent;")

        self._text_lbl = QLabel(label)
        self._text_lbl.setFont(_font(FONT_SIZE_SMALL))
        self._text_lbl.setStyleSheet("background: transparent;")

        self._check_lbl = QLabel("✓")
        self._check_lbl.setFont(_font(FONT_SIZE_SMALL, QFont.Weight.Bold))
        self._check_lbl.setStyleSheet(f"color: {COLOR_SUCCESS}; background: transparent;")

        layout.addWidget(self._icon_lbl)
        layout.addWidget(self._text_lbl)
        layout.addWidget(self._check_lbl)

        self._refresh()

    @property
    def media_type(self) -> str:
        return self._media_type

    def isActive(self) -> bool:
        return self._active

    def setActive(self, active: bool) -> None:
        self._active = active
        self._refresh()
        self.toggled.emit(active)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        self.setActive(not self._active)

    def _refresh(self) -> None:
        self._check_lbl.setVisible(self._active)
        if self._active:
            self.setStyleSheet(f"""
                ChipButton {{
                    background-color: {ACCENT_SOFT_ORANGE};
                    border: 1px solid {ACCENT_ORANGE};
                    border-radius: 30px;
                }}
            """)
            self._icon_lbl.setStyleSheet(
                f"color: {ACCENT_ORANGE}; background: transparent;"
            )
            self._text_lbl.setStyleSheet(
                f"color: {TEXT_PRIMARY}; background: transparent;"
            )
        else:
            self.setStyleSheet(f"""
                ChipButton {{
                    background-color: {OVERLAY2_HEX};
                    border: 1px solid {BORDER_HEX};
                    border-radius: 30px;
                }}
            """)
            self._icon_lbl.setStyleSheet(
                f"color: {TEXT_SECONDARY}; background: transparent;"
            )
            self._text_lbl.setStyleSheet(
                f"color: {TEXT_SECONDARY}; background: transparent;"
            )


# ══════════════════════════════════════════════════════════════════════════════
# SPLIT MODE BUTTON  — кнопка режима разбивки документа
# ══════════════════════════════════════════════════════════════════════════════

class SplitModeButton(QPushButton):
    """
    Тайл режима разбивки: Единый / Дни / Месяцы / Посты.
    Соответствует .split-btn из прототипа.

    Пример:
        btn = SplitModeButton("📄", "Единый", mode="none", active=True)
    """

    def __init__(
        self,
        icon: str,
        label: str,
        mode: str,
        active: bool = False,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._mode = mode
        self.setCheckable(True)
        self.setChecked(active)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 8, 4, 8)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._icon_lbl = QLabel(icon)
        self._icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon_lbl.setFont(_font(18))
        self._icon_lbl.setStyleSheet("background: transparent;")

        self._text_lbl = QLabel(label)
        self._text_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._text_lbl.setFont(_font(FONT_SIZE_XS, QFont.Weight.Medium))
        self._text_lbl.setStyleSheet("background: transparent;")

        layout.addWidget(self._icon_lbl)
        layout.addWidget(self._text_lbl)

        self.toggled.connect(self._refresh)
        self._refresh(active)

    @property
    def mode(self) -> str:
        return self._mode

    def _refresh(self, checked: bool) -> None:
        if checked:
            self.setStyleSheet(f"""
                SplitModeButton, QPushButton {{
                    background-color: {ACCENT_SOFT_ORANGE};
                    border: 1px solid {ACCENT_ORANGE};
                    border-radius: {RADIUS_MD}px;
                    color: {ACCENT_ORANGE};
                }}
            """)
            for lbl in (self._icon_lbl, self._text_lbl):
                lbl.setStyleSheet(f"color: {ACCENT_ORANGE}; background: transparent;")
        else:
            self.setStyleSheet(f"""
                SplitModeButton, QPushButton {{
                    background-color: {OVERLAY2_HEX};
                    border: 1px solid {BORDER_HEX};
                    border-radius: {RADIUS_MD}px;
                    color: {TEXT_SECONDARY};
                }}
                SplitModeButton:hover, QPushButton:hover {{
                    background-color: {OVERLAY_HEX};
                }}
            """)
            for lbl in (self._icon_lbl, self._text_lbl):
                lbl.setStyleSheet(f"color: {TEXT_SECONDARY}; background: transparent;")


# ══════════════════════════════════════════════════════════════════════════════
# FILTER BUTTON  — кнопка фильтра лога
# ══════════════════════════════════════════════════════════════════════════════

class FilterButton(QPushButton):
    """
    Pill-кнопка фильтра лога: Все / Инфо / Успех / Предупр. / Ошибки.
    Соответствует .filter-btn из прототипа.
    """

    def __init__(self, label: str, filter_key: str = "all",
                 parent: Optional[QWidget] = None):
        super().__init__(label, parent)
        self._filter_key = filter_key
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(QSS_FILTER_BUTTON)

    @property
    def filter_key(self) -> str:
        return self._filter_key


# ══════════════════════════════════════════════════════════════════════════════
# USER TAG  — тег участника (checkable pill)
# ══════════════════════════════════════════════════════════════════════════════

class UserTag(QPushButton):
    """
    Checkable тег пользователя с иконкой.
    Соответствует .user-tag из прототипа.

    Пример:
        tag = UserTag("@anna_s")
        tag = UserTag("Все", is_all=True)
        tag.toggled.connect(on_user_selected)
    """

    def __init__(
        self,
        username: str,
        user_id: int = 0,
        is_all: bool = False,
        selected: bool = False,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._user_id = user_id
        self._is_all = is_all

        icon = "✓ " if is_all else "👤 "
        self.setText(icon + username)
        self.setCheckable(True)
        self.setChecked(selected)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggled.connect(self._refresh)
        self._refresh(selected)

    @property
    def user_id(self) -> int:
        return self._user_id

    @property
    def is_all(self) -> bool:
        return self._is_all

    def _refresh(self, checked: bool) -> None:
        if checked:
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: {ACCENT_PINK};
                    border: 1px solid {ACCENT_PINK};
                    border-radius: 20px;
                    padding: 3px 12px;
                    color: {BG_PRIMARY};
                    font-size: {FONT_SIZE_SMALL}px;
                    font-weight: 600;
                }}
            """)
        else:
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: {ACCENT_SOFT_PINK};
                    border: 1px solid {ACCENT_PINK};
                    border-radius: 20px;
                    padding: 3px 12px;
                    color: {TEXT_SECONDARY};
                    font-size: {FONT_SIZE_SMALL}px;
                }}
                QPushButton:hover {{
                    background-color: rgba(255,107,201,0.25);
                }}
            """)


# ══════════════════════════════════════════════════════════════════════════════
# STEPPER WIDGET  — навигация по шагам
# ══════════════════════════════════════════════════════════════════════════════

class StepperWidget(QWidget):
    """
    Горизонтальная навигация: 4 шага с номерами.
    Соответствует .stepper / .step из прототипа.

    Пример:
        stepper = StepperWidget(steps=["Вход", "Чаты", "Настройки", "Экспорт"])
        stepper.set_active(0)   # шаг 1 активен
    """

    # Шаги: список кортежей (номер_QLabel, текст_QLabel)
    _STEPS = [
        ("1", "Вход"),
        ("2", "Чаты"),
        ("3", "Настройки"),
        ("4", "Экспорт"),
    ]

    def __init__(
        self,
        steps: Optional[list[str]] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._active_index: int = 0
        self._step_labels: list[tuple[QLabel, QLabel]] = []

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(32)

        step_defs = [(str(i + 1), name) for i, name in enumerate(steps)] \
            if steps else self._STEPS

        for num_str, name in step_defs:
            step_widget = QWidget()
            step_layout = QHBoxLayout(step_widget)
            step_layout.setContentsMargins(0, 0, 0, 0)
            step_layout.setSpacing(8)

            num_lbl = QLabel(num_str)
            num_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            num_lbl.setFixedSize(24, 24)

            text_lbl = QLabel(name)
            text_lbl.setFont(_font(FONT_SIZE_BODY, QFont.Weight.Medium))

            step_layout.addWidget(num_lbl)
            step_layout.addWidget(text_lbl)
            layout.addWidget(step_widget)

            self._step_labels.append((num_lbl, text_lbl))

        self.set_active(0)

    def set_active(self, index: int) -> None:
        """Активировать шаг по индексу (0-based)."""
        self._active_index = index
        for i, (num_lbl, text_lbl) in enumerate(self._step_labels):
            if i == index:
                num_lbl.setStyleSheet(QSS_STEPPER_NUMBER_ACTIVE)
                text_lbl.setStyleSheet(
                    f"QLabel {{ color: {ACCENT_ORANGE}; font-weight: 500;"
                    f" background: transparent; }}"
                )
            else:
                num_lbl.setStyleSheet(QSS_STEPPER_NUMBER_INACTIVE)
                text_lbl.setStyleSheet(
                    f"QLabel {{ color: {TEXT_SECONDARY}; font-weight: 500;"
                    f" background: transparent; }}"
                )

    def current_step(self) -> int:
        return self._active_index


# ══════════════════════════════════════════════════════════════════════════════
# HEADER BAR  — шапка приложения
# ══════════════════════════════════════════════════════════════════════════════

class HeaderBar(QWidget):
    """
    Шапка приложения: логотип слева, степпер по центру.
    Соответствует .header из прототипа.

    Доступ к степперу: header.stepper.set_active(n)
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setFixedHeight(56)
        self.setStyleSheet(f"""
            HeaderBar {{
                background-color: {OVERLAY_HEX};
                border: 1px solid {BORDER_HEX};
                border-radius: {RADIUS_LG}px;
            }}
        """)
        _shadow(self, blur=24, y_offset=4, alpha=80)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(24, 8, 24, 8)
        layout.setSpacing(0)

        # Логотип с градиентным текстом (эмулируем через HTML в QLabel)
        self._logo = QLabel()
        self._logo.setText(
            "<span style='"
            f"font-size:{FONT_SIZE_H1}px; font-weight:600;"
            " background: transparent;"
            f"color:{ACCENT_ORANGE};"   # fallback — Qt не поддерживает gradient text
            "'>Rozitta Parser</span>"
        )
        self._logo.setTextFormat(Qt.TextFormat.RichText)
        self._logo.setStyleSheet("background: transparent;")
        layout.addWidget(self._logo)

        layout.addStretch()

        self.stepper = StepperWidget()
        layout.addWidget(self.stepper)

    def set_step(self, index: int) -> None:
        """Shortcut: header.set_step(2)"""
        self.stepper.set_active(index)


# ══════════════════════════════════════════════════════════════════════════════
# ROZETTA WIDGET  — блок с аватаром и подсказкой персонажа
# ══════════════════════════════════════════════════════════════════════════════

class RozittaWidget(QWidget):
    """
    Блок персонажа Розитты: большой аватар + имя + текст подсказки.
    Соответствует .character-large из прототипа.

    API:
        w.set_tip("Авторизация успешна!")   # обновить текст
        w.set_state("success")              # success / error / warning / idle
        w.set_image_path("/path/to/img.png") # заменить placeholder-эмодзи на картинку

    При state="success"  — аватар пульсирует зелёной рамкой
    При state="error"    — красной
    При state="warning"  — жёлтой
    При state="idle"     — розовой (default)
    """

    # Цвета рамки по состоянию
    _STATE_COLORS: dict[str, str] = {
        "idle":    ACCENT_PINK,
        "success": COLOR_SUCCESS,
        "error":   COLOR_ERROR,
        "warning": COLOR_WARNING,
        "auth":    ACCENT_ORANGE,
        "process": ACCENT_ORANGE,
    }

    clicked = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._state = "idle"
        self._image_path: Optional[str] = None
        self._build_ui()

    def _build_ui(self) -> None:
        self.setStyleSheet(f"""
            RozittaWidget {{
                background-color: {OVERLAY2_HEX};
                border: 1px dashed {ACCENT_PINK};
                border-radius: {RADIUS_LG}px;
            }}
        """)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.setSpacing(12)
        outer.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        # ── Аватар-круг ───────────────────────────────────────────────────
        self._avatar = _AvatarFrame()
        self._avatar.setFixedSize(160, 160)
        outer.addWidget(self._avatar, alignment=Qt.AlignmentFlag.AlignHCenter)

        # ── Имя ───────────────────────────────────────────────────────────
        self._name_lbl = QLabel("Розитта")
        self._name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._name_lbl.setFont(_font(FONT_SIZE_BODY, QFont.Weight.DemiBold))
        self._name_lbl.setStyleSheet(
            f"QLabel {{ color: {ACCENT_PINK}; background: transparent; }}"
        )
        outer.addWidget(self._name_lbl)

        # ── Подсказка ─────────────────────────────────────────────────────
        self._tip_lbl = QLabel("Начните с авторизации")
        self._tip_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._tip_lbl.setWordWrap(True)
        self._tip_lbl.setFont(_font(FONT_SIZE_SMALL))
        self._tip_lbl.setStyleSheet(
            f"QLabel {{ color: {TEXT_SECONDARY}; background: transparent; }}"
        )
        self._tip_lbl.setMaximumWidth(220)
        self._tip_lbl.setMinimumHeight(40)
        outer.addWidget(self._tip_lbl, alignment=Qt.AlignmentFlag.AlignHCenter)

        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        self.clicked.emit()
        self._animate_avatar()

    def set_tip(self, text: str) -> None:
        """Обновить текст подсказки и запустить анимацию."""
        self._tip_lbl.setText(text)
        self._animate_avatar()

    def set_state(self, state: str) -> None:
        """
        Изменить визуальное состояние:
        'idle' | 'success' | 'error' | 'warning' | 'auth' | 'process'
        """
        self._state = state
        color = self._STATE_COLORS.get(state, ACCENT_PINK)
        self._avatar.set_border_color(color)
        self.setStyleSheet(f"""
            RozittaWidget {{
                background-color: {OVERLAY2_HEX};
                border: 1px dashed {color};
                border-radius: {RADIUS_LG}px;
            }}
        """)

    def set_image_path(self, path: str) -> None:
        """Заменить emoji-placeholder на реальное изображение."""
        self._image_path = path
        self._avatar.set_image(path)

    def _animate_avatar(self) -> None:
        """Лёгкий scale-импульс аватара."""
        self._avatar.pulse()


class _AvatarFrame(QWidget):
    """
    Круглый аватар персонажа. Внутри либо emoji, либо QPixmap.
    Поддерживает анимацию pulse() (scale 1.0 → 1.05 → 1.0).
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._border_color = QColor(ACCENT_PINK)
        self._scale: float = 1.0
        self._emoji = "🐸"
        self._pixmap = None

        # Анимация масштаба
        self._anim = QPropertyAnimation(self, b"_scale_prop", self)
        self._anim.setDuration(300)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutQuad)

    def _get_scale(self) -> float:
        return self._scale

    def _set_scale(self, v: float) -> None:
        self._scale = v
        self.update()

    _scale_prop = Property(float, _get_scale, _set_scale)

    def set_border_color(self, hex_color: str) -> None:
        self._border_color = QColor(hex_color)
        self.update()

    def set_image(self, path: str) -> None:
        from PySide6.QtGui import QPixmap
        self._pixmap = QPixmap(path)
        self.update()

    def pulse(self) -> None:
        self._anim.stop()
        self._anim.setKeyValueAt(0.0, 1.0)
        self._anim.setKeyValueAt(0.5, 1.06)
        self._anim.setKeyValueAt(1.0, 1.0)
        self._anim.start()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        r = min(w, h) / 2

        # Масштаб от центра
        p.translate(cx, cy)
        p.scale(self._scale, self._scale)
        p.translate(-cx, -cy)

        # Фоновый градиент круга
        grad = QLinearGradient(0, 0, w, h)
        grad.setColorAt(0.0, QColor(ACCENT_SOFT_PINK))
        grad.setColorAt(1.0, QColor(ACCENT_SOFT_ORANGE))

        path = QPainterPath()
        path.addEllipse(3, 3, w - 6, h - 6)

        p.setClipPath(path)
        p.fillPath(path, grad)
        p.setClipping(False)

        # Контент: изображение или emoji
        if self._pixmap and not self._pixmap.isNull():
            from PySide6.QtGui import QPixmap
            scaled = self._pixmap.scaled(
                int(w - 6), int(h - 6),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            p.setClipPath(path)
            p.drawPixmap(
                3 + (w - 6 - scaled.width()) // 2,
                3 + (h - 6 - scaled.height()) // 2,
                scaled,
            )
            p.setClipping(False)
        else:
            # Emoji-placeholder
            font = _font(int(r * 0.8))
            p.setFont(font)
            p.setPen(QColor(ACCENT_PINK))
            p.drawText(QRect(0, 0, w, h),
                       Qt.AlignmentFlag.AlignCenter,
                       self._emoji)

        # Рамка
        p.setPen(self._border_color)
        from PySide6.QtGui import QPen
        pen = QPen(self._border_color, 3)
        p.setPen(pen)
        p.drawEllipse(2, 2, w - 4, h - 4)
        p.end()


# ══════════════════════════════════════════════════════════════════════════════
# LOG WIDGET  — журнал выполнения
# ══════════════════════════════════════════════════════════════════════════════

class LogWidget(QWidget):
    """
    Полный виджет журнала: фильтры + текстовое поле + кнопки очистки/копирования.
    Соответствует колонке 4 из прототипа (.log-container).

    API:
        log.append_info("Текст")
        log.append_success("Готово!")
        log.append_warning("Внимание")
        log.append_error("Ошибка")
        log.append(text, level="info"|"success"|"warning"|"error")
        log.clear()
    """

    # HTML-цвета по уровню
    _LEVEL_COLORS = {
        "info":    TEXT_PRIMARY,
        "success": COLOR_SUCCESS,
        "warning": COLOR_WARNING,
        "error":   COLOR_ERROR,
    }

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._current_filter = "all"
        self._all_entries: list[tuple[str, str, str]] = []  # (time, text, level)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # ── Фильтры + кнопки ──────────────────────────────────────────────
        ctrl_layout = QHBoxLayout()
        ctrl_layout.setSpacing(4)

        self._filter_btns: list[FilterButton] = []
        filters = [
            ("Все",    "all",     "Показать всё"),
            ("Инфо",   "info",    "Информация"),
            ("Успех",  "success", "Успешные"),
            ("Пред.",  "warning", "Предупреждения"),
            ("Ошиб.",  "error",   "Ошибки"),
        ]
        for label, key, tip in filters:
            btn = FilterButton(label, key)
            btn.setToolTip(tip)
            btn.setChecked(key == "all")
            btn.toggled.connect(
                lambda checked, k=key, b=btn: self._on_filter(k, b, checked)
            )
            ctrl_layout.addWidget(btn)
            self._filter_btns.append(btn)

        ctrl_layout.addStretch()

        self._clear_btn = QPushButton("🧹")
        self._clear_btn.setFixedSize(32, 32)
        self._clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._clear_btn.setStyleSheet(QSS_BUTTON_ICON)
        self._clear_btn.setToolTip("Очистить журнал")
        self._clear_btn.clicked.connect(self.clear)

        self._copy_btn = QPushButton("📋")
        self._copy_btn.setFixedSize(32, 32)
        self._copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._copy_btn.setStyleSheet(QSS_BUTTON_ICON)
        self._copy_btn.setToolTip("Скопировать журнал")
        self._copy_btn.clicked.connect(self._copy_log)

        ctrl_layout.addWidget(self._clear_btn)
        ctrl_layout.addWidget(self._copy_btn)

        layout.addLayout(ctrl_layout)

        # ── Текстовое поле ─────────────────────────────────────────────────
        self._output = QTextEdit()
        self._output.setReadOnly(True)
        self._output.setStyleSheet(QSS_LOG_OUTPUT)
        self._output.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        layout.addWidget(self._output)

    # ── Публичное API ─────────────────────────────────────────────────────

    def append(self, text: str, level: str = "info") -> None:
        """Добавить запись в журнал."""
        from datetime import datetime
        ts = datetime.now().strftime("%H:%M:%S")
        self._all_entries.append((ts, text, level))
        if self._current_filter in ("all", level):
            self._render_entry(ts, text, level)

    def append_info(self, text: str)    -> None: self.append(text, "info")
    def append_success(self, text: str) -> None: self.append(text, "success")
    def append_warning(self, text: str) -> None: self.append(text, "warning")
    def append_error(self, text: str)   -> None: self.append(text, "error")

    def clear(self) -> None:
        self._all_entries.clear()
        self._output.clear()

    # ── Внутренние методы ─────────────────────────────────────────────────

    def _render_entry(self, ts: str, text: str, level: str) -> None:
        color = self._LEVEL_COLORS.get(level, TEXT_PRIMARY)
        html = (
            f'<span style="color:{TEXT_SECONDARY};">[{ts}]</span> '
            f'<span style="color:{color};">{text}</span><br/>'
        )
        cursor = self._output.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self._output.setTextCursor(cursor)
        self._output.insertHtml(html)
        self._output.ensureCursorVisible()

    def _on_filter(self, key: str, sender: FilterButton, checked: bool) -> None:
        if not checked:
            return
        # Снять все остальные
        for btn in self._filter_btns:
            if btn is not sender:
                btn.setChecked(False)
        self._current_filter = key
        self._redraw()

    def _redraw(self) -> None:
        self._output.clear()
        for ts, text, level in self._all_entries:
            if self._current_filter in ("all", level):
                self._render_entry(ts, text, level)

    def _copy_log(self) -> None:
        text = self._output.toPlainText()
        QApplication.clipboard().setText(text)
