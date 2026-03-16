"""
FILE: core/ui_shared/styles.py

Цветовые константы и QSS для Rozitta Parser.
Источник: Rozitta_prototype.html (CSS-переменные :root).

Структура:
  - Константы цветов (строки HEX/RGBA)
  - Константы размеров (радиусы, паддинги)
  - Готовые QSS-блоки для каждого типа виджета
  - apply_style(widget, style_name) — утилита применения стиля

ВАЖНО: Этот файл НЕ импортирует никакой бизнес-логики.
Допустимы только импорты PySide6.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget

# ══════════════════════════════════════════════════════════════════════════════
# ЦВЕТОВЫЕ КОНСТАНТЫ
# Источник: :root { } из Rozitta_prototype.html
# ══════════════════════════════════════════════════════════════════════════════

# Фоны
BG_PRIMARY        = "#2B2B2B"          # --bg-primary
BG_SURFACE        = "rgba(255,255,255,0.05)"   # --surface (glassmorphism)
BG_SURFACE_HOVER  = "rgba(255,255,255,0.08)"   # --surface-hover
BG_DARK_OVERLAY   = "rgba(0,0,0,0.3)"          # фон полей ввода
BG_DARK_OVERLAY2  = "rgba(0,0,0,0.2)"          # фон секций
BG_DARK_OVERLAY3  = "rgba(0,0,0,0.1)"          # фон списка чатов

# Qt не поддерживает rgba() напрямую — используем аналоги через QColor
# Для QSS виджетов применяются hex-эквиваленты с opacity через alpha
SURFACE_HEX       = "#0D0D0D"          # ~rgba(255,255,255,0.05) на #2B2B2B
SURFACE_HOVER_HEX = "#141414"          # ~rgba(255,255,255,0.08) на #2B2B2B
OVERLAY_HEX       = "#1A1A1A"          # rgba(0,0,0,0.3) на #2B2B2B → ~#1F1F1F
OVERLAY2_HEX      = "#242424"          # rgba(0,0,0,0.2) на #2B2B2B

# Акценты
ACCENT_ORANGE       = "#FF9500"        # --accent-orange
ACCENT_PINK         = "#FF6BC9"        # --accent-pink
ACCENT_SOFT_ORANGE  = "#3D2400"        # --accent-soft-orange (rgba(255,149,0,0.15))
ACCENT_SOFT_PINK    = "#3D1A30"        # --accent-soft-pink   (rgba(255,107,201,0.15))

# Акценты для hover
ACCENT_ORANGE_HOVER = "#E08600"        # btn-primary:hover
ACCENT_PINK_HOVER   = "#FF45BB"        # accent-pink hover

# Семантические цвета
COLOR_ERROR   = "#FF4D4D"             # --error
COLOR_WARNING = "#FFAA00"             # --warning
COLOR_SUCCESS = "#00C853"             # --success
COLOR_DM      = "#0066FF"             # dm/диалог синий

# Текст
TEXT_PRIMARY   = "#F0F0F0"            # --text-primary
TEXT_SECONDARY = "#CCCCCC"            # --text-secondary
TEXT_DISABLED  = "#888888"            # disabled состояния

# Границы
BORDER_LIGHT = "rgba(255,255,255,0.1)"   # --border-light
BORDER_HEX   = "#1A1A1A"                 # hex-аналог для QSS

# Специальные
TRANSPARENT = "transparent"

# ══════════════════════════════════════════════════════════════════════════════
# РАЗМЕРНЫЕ КОНСТАНТЫ
# ══════════════════════════════════════════════════════════════════════════════

RADIUS_LG  = 16    # --radius (большие карточки, панели)
RADIUS_MD  = 10    # --radius-sm (кнопки, инпуты, мелкие элементы)
RADIUS_SM  = 8     # дополнительный уровень для иконок
RADIUS_XS  = 6     # теги, бейджи

PADDING_LG  = 20   # карточки
PADDING_MD  = 12   # секции
PADDING_SM  = 8    # элементы списка
PADDING_XS  = 4    # иконки

FONT_FAMILY = "Inter"
FONT_SIZE_H1    = 20   # заголовок приложения
FONT_SIZE_H2    = 16   # card-title
FONT_SIZE_BODY  = 14   # основной текст (QSS в pt, браузер в px ≈ равны)
FONT_SIZE_SMALL = 12   # мета-информация
FONT_SIZE_XS    = 11   # бейджи, счётчики

# ── Псевдонимы (calendar.py и другие legacy-потребители) ──────────────────
PAD_SMALL    = PADDING_SM
PAD_TINY     = PADDING_XS
PAD_MD       = PADDING_MD
PAD_LG       = PADDING_LG

RADIUS_SMALL = RADIUS_SM
RADIUS_TINY  = RADIUS_XS

FONT_BODY    = FONT_SIZE_BODY
FONT_SMALL   = FONT_SIZE_SMALL
FONT_TINY    = FONT_SIZE_XS

TEXT_LIGHT   = TEXT_SECONDARY
TEXT_MUTED   = TEXT_DISABLED

ACCENT_AMBER    = COLOR_WARNING   # #FFAA00 — янтарный
ACCENT_CORAL    = COLOR_ERROR     # #FF4D4D — коралловый
ACCENT_LAVENDER = "#9B8FD9"       # лавандовый

# ══════════════════════════════════════════════════════════════════════════════
# PALETTE — QSS строки для QPalette (применяется к QApplication)
# ══════════════════════════════════════════════════════════════════════════════

APPLICATION_STYLE_FUSION = "Fusion"   # базовый стиль Qt для кастомизации

# ══════════════════════════════════════════════════════════════════════════════
# QSS БЛОКИ
# Каждый блок — самодостаточная строка для конкретного типа виджета.
# Используются в apply_style() и напрямую в setStyleSheet().
# ══════════════════════════════════════════════════════════════════════════════

# ── Главное окно / фон приложения ─────────────────────────────────────────
QSS_MAIN_WINDOW = f"""
    QMainWindow, QDialog {{
        background-color: {BG_PRIMARY};
        color: {TEXT_PRIMARY};
        font-family: {FONT_FAMILY};
        font-size: {FONT_SIZE_BODY}px;
    }}
    QWidget {{
        background-color: transparent;
        color: {TEXT_PRIMARY};
        font-family: {FONT_FAMILY};
    }}
"""

# ── Карточка (glassmorphism панель) ───────────────────────────────────────
QSS_CARD = f"""
    ModernCard, QFrame#card {{
        background-color: {OVERLAY_HEX};
        border: 1px solid {BORDER_HEX};
        border-radius: {RADIUS_LG}px;
    }}
"""

# ── Поля ввода (LineEdit, PasswordEdit) ───────────────────────────────────
QSS_INPUT = f"""
    QLineEdit {{
        background-color: {OVERLAY_HEX};
        border: 1px solid {BORDER_HEX};
        border-radius: {RADIUS_MD}px;
        padding: 8px 12px;
        color: {TEXT_PRIMARY};
        font-family: {FONT_FAMILY};
        font-size: {FONT_SIZE_BODY}px;
        selection-background-color: {ACCENT_ORANGE};
        selection-color: #ffffff;
    }}
    QLineEdit:focus {{
        border: 1px solid {ACCENT_ORANGE};
        background-color: #1F1A0D;
    }}
    QLineEdit:disabled {{
        color: {TEXT_DISABLED};
        border-color: #333333;
    }}
    QLineEdit::placeholder {{
        color: {TEXT_SECONDARY};
    }}
"""

# ── ComboBox ──────────────────────────────────────────────────────────────
QSS_COMBOBOX = f"""
    QComboBox {{
        background-color: {OVERLAY_HEX};
        border: 1px solid {BORDER_HEX};
        border-radius: {RADIUS_MD}px;
        padding: 8px 12px;
        color: {TEXT_PRIMARY};
        font-size: {FONT_SIZE_BODY}px;
    }}
    QComboBox:focus {{
        border-color: {ACCENT_ORANGE};
    }}
    QComboBox::drop-down {{
        border: none;
        width: 24px;
    }}
    QComboBox::down-arrow {{
        image: none;
        border-left: 4px solid transparent;
        border-right: 4px solid transparent;
        border-top: 5px solid {TEXT_SECONDARY};
        margin-right: 8px;
    }}
    QComboBox QAbstractItemView {{
        background-color: {BG_PRIMARY};
        border: 1px solid {BORDER_HEX};
        border-radius: {RADIUS_MD}px;
        color: {TEXT_PRIMARY};
        selection-background-color: {ACCENT_SOFT_ORANGE};
        selection-color: {ACCENT_ORANGE};
        padding: 4px;
    }}
"""

# ── Кнопки ────────────────────────────────────────────────────────────────
QSS_BUTTON_BASE = f"""
    QPushButton {{
        background-color: {OVERLAY_HEX};
        border: 1px solid {BORDER_HEX};
        border-radius: {RADIUS_MD}px;
        padding: 8px 16px;
        color: {TEXT_PRIMARY};
        font-family: {FONT_FAMILY};
        font-size: {FONT_SIZE_BODY}px;
        font-weight: 500;
    }}
    QPushButton:hover {{
        background-color: {OVERLAY2_HEX};
    }}
    QPushButton:pressed {{
        background-color: {OVERLAY_HEX};
    }}
    QPushButton:disabled {{
        color: {TEXT_DISABLED};
        border-color: #333333;
    }}
"""

QSS_BUTTON_PRIMARY = f"""
    QPushButton {{
        background-color: {ACCENT_ORANGE};
        border: 1px solid {ACCENT_ORANGE};
        border-radius: {RADIUS_MD}px;
        padding: 10px 16px;
        color: #ffffff;
        font-family: {FONT_FAMILY};
        font-size: {FONT_SIZE_BODY}px;
        font-weight: 600;
    }}
    QPushButton:hover {{
        background-color: {ACCENT_ORANGE_HOVER};
        border-color: {ACCENT_ORANGE_HOVER};
    }}
    QPushButton:pressed {{
        background-color: #C07400;
    }}
    QPushButton:disabled {{
        background-color: #5A3500;
        border-color: #5A3500;
        color: #888888;
    }}
"""

QSS_BUTTON_SECONDARY = f"""
    QPushButton {{
        background-color: {ACCENT_SOFT_PINK};
        border: 1px solid {ACCENT_PINK};
        border-radius: {RADIUS_MD}px;
        padding: 8px 16px;
        color: {ACCENT_PINK};
        font-family: {FONT_FAMILY};
        font-size: {FONT_SIZE_BODY}px;
        font-weight: 500;
    }}
    QPushButton:hover {{
        background-color: rgba(255,107,201,0.25);
    }}
    QPushButton:pressed {{
        background-color: {ACCENT_PINK};
        color: {BG_PRIMARY};
    }}
    QPushButton:disabled {{
        background-color: #2A1020;
        border-color: #5A2050;
        color: #5A2050;
    }}
"""

QSS_BUTTON_ICON = f"""
    QPushButton {{
        background-color: {OVERLAY_HEX};
        border: 1px solid {BORDER_HEX};
        border-radius: {RADIUS_MD}px;
        padding: 6px 10px;
        color: {TEXT_SECONDARY};
        font-size: {FONT_SIZE_BODY}px;
        min-width: 32px;
        min-height: 32px;
    }}
    QPushButton:hover {{
        background-color: {OVERLAY2_HEX};
        color: {TEXT_PRIMARY};
    }}
"""

# ── Список чатов (QListWidget) ────────────────────────────────────────────
QSS_CHAT_LIST = f"""
    QListWidget {{
        background-color: {BG_DARK_OVERLAY3};
        border: none;
        border-radius: {RADIUS_MD}px;
        padding: 4px;
        outline: none;
    }}
    QListWidget::item {{
        border-radius: {RADIUS_MD}px;
        padding: 0;
        margin: 2px 0;
    }}
    QListWidget::item:hover {{
        background-color: {OVERLAY2_HEX};
    }}
    QListWidget::item:selected {{
        background-color: {ACCENT_SOFT_ORANGE};
        border-left: 3px solid {ACCENT_ORANGE};
    }}
    QScrollBar:vertical {{
        width: 6px;
        background: transparent;
        margin: 0;
    }}
    QScrollBar::handle:vertical {{
        background: {ACCENT_ORANGE};
        border-radius: 3px;
        min-height: 20px;
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0;
    }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
        background: transparent;
    }}
"""

# ── ScrollArea (общий) ────────────────────────────────────────────────────
QSS_SCROLL_AREA = f"""
    QScrollArea {{
        background-color: transparent;
        border: none;
    }}
    QScrollArea > QWidget > QWidget {{
        background-color: transparent;
    }}
    QScrollBar:vertical {{
        width: 6px;
        background: transparent;
        margin: 0;
    }}
    QScrollBar::handle:vertical {{
        background: {ACCENT_ORANGE};
        border-radius: 3px;
        min-height: 20px;
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0;
    }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
        background: transparent;
    }}
    QScrollBar:horizontal {{
        height: 6px;
        background: transparent;
    }}
    QScrollBar::handle:horizontal {{
        background: {ACCENT_ORANGE};
        border-radius: 3px;
        min-width: 20px;
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0;
    }}
"""

# ── Лог (QTextEdit / QPlainTextEdit) ─────────────────────────────────────
QSS_LOG_OUTPUT = f"""
    QTextEdit, QPlainTextEdit {{
        background-color: {OVERLAY2_HEX};
        border: none;
        border-radius: {RADIUS_MD}px;
        color: {TEXT_PRIMARY};
        font-family: "JetBrains Mono", "Consolas", "Courier New", monospace;
        font-size: {FONT_SIZE_SMALL}px;
        padding: 12px;
        selection-background-color: {ACCENT_ORANGE};
    }}
    QTextEdit QScrollBar:vertical {{
        width: 6px;
        background: transparent;
    }}
    QTextEdit QScrollBar::handle:vertical {{
        background: {ACCENT_ORANGE};
        border-radius: 3px;
    }}
    QTextEdit QScrollBar::add-line:vertical,
    QTextEdit QScrollBar::sub-line:vertical {{
        height: 0;
    }}
"""

# ── Заголовки секций (QLabel) ─────────────────────────────────────────────
QSS_LABEL_TITLE = f"""
    QLabel {{
        color: {TEXT_PRIMARY};
        font-family: {FONT_FAMILY};
        font-size: {FONT_SIZE_H2}px;
        font-weight: 600;
        background: transparent;
    }}
"""

QSS_LABEL_SECTION = f"""
    QLabel {{
        color: {ACCENT_ORANGE};
        font-family: {FONT_FAMILY};
        font-size: {FONT_SIZE_BODY}px;
        font-weight: 600;
        background: transparent;
    }}
"""

QSS_LABEL_SECONDARY = f"""
    QLabel {{
        color: {TEXT_SECONDARY};
        font-family: {FONT_FAMILY};
        font-size: {FONT_SIZE_SMALL}px;
        background: transparent;
    }}
"""

QSS_LABEL_HINT = f"""
    QLabel {{
        color: {TEXT_SECONDARY};
        font-family: {FONT_FAMILY};
        font-size: {FONT_SIZE_XS}px;
        background: transparent;
    }}
"""

# ── Медиа-кнопки (активная / неактивная) ──────────────────────────────────
QSS_MEDIA_BUTTON = f"""
    QPushButton[active="false"] {{
        background-color: {OVERLAY2_HEX};
        border: 1px solid {BORDER_HEX};
        border-radius: {RADIUS_MD}px;
        color: {TEXT_SECONDARY};
        padding: 8px 4px;
        font-size: {FONT_SIZE_SMALL}px;
        font-weight: 500;
    }}
    QPushButton[active="true"] {{
        background-color: {ACCENT_SOFT_ORANGE};
        border: 1px solid {ACCENT_ORANGE};
        border-radius: {RADIUS_MD}px;
        color: {ACCENT_ORANGE};
        padding: 8px 4px;
        font-size: {FONT_SIZE_SMALL}px;
        font-weight: 500;
    }}
    QPushButton:hover {{
        background-color: {OVERLAY_HEX};
    }}
"""

# ── Чипы (recognition chips, split buttons) ───────────────────────────────
QSS_CHIP_INACTIVE = f"""
    QPushButton {{
        background-color: {OVERLAY2_HEX};
        border: 1px solid {BORDER_HEX};
        border-radius: 30px;
        padding: 5px 12px;
        color: {TEXT_SECONDARY};
        font-size: {FONT_SIZE_SMALL}px;
    }}
    QPushButton:hover {{
        background-color: {OVERLAY_HEX};
    }}
"""

QSS_CHIP_ACTIVE = f"""
    QPushButton {{
        background-color: {ACCENT_SOFT_ORANGE};
        border: 1px solid {ACCENT_ORANGE};
        border-radius: 30px;
        padding: 5px 12px;
        color: {ACCENT_ORANGE};
        font-size: {FONT_SIZE_SMALL}px;
        font-weight: 500;
    }}
"""

# ── Теги пользователей ────────────────────────────────────────────────────
QSS_USER_TAG = f"""
    QPushButton {{
        background-color: {ACCENT_SOFT_PINK};
        border: 1px solid {ACCENT_PINK};
        border-radius: 20px;
        padding: 3px 12px;
        color: {TEXT_SECONDARY};
        font-size: {FONT_SIZE_SMALL}px;
    }}
    QPushButton:checked {{
        background-color: {ACCENT_PINK};
        color: {BG_PRIMARY};
        font-weight: 600;
    }}
    QPushButton:hover {{
        background-color: rgba(255,107,201,0.25);
    }}
"""

# ── Toggle Switch (QCheckBox стилизованный) ───────────────────────────────
QSS_TOGGLE = f"""
    QCheckBox {{
        color: {TEXT_PRIMARY};
        font-size: {FONT_SIZE_BODY}px;
        spacing: 8px;
    }}
    QCheckBox::indicator {{
        width: 40px;
        height: 20px;
        border-radius: 10px;
        background-color: {OVERLAY_HEX};
        border: 1px solid {BORDER_HEX};
    }}
    QCheckBox::indicator:checked {{
        background-color: {ACCENT_ORANGE};
        border-color: {ACCENT_ORANGE};
        image: none;
    }}
"""

# ── Разделитель ───────────────────────────────────────────────────────────
QSS_SEPARATOR = f"""
    QFrame[frameShape="4"],
    QFrame[frameShape="5"] {{
        color: {BORDER_HEX};
        background-color: {BORDER_HEX};
        border: none;
        max-height: 1px;
    }}
"""

# ── Фильтр-кнопки (log filter) ────────────────────────────────────────────
QSS_FILTER_BUTTON = f"""
    QPushButton {{
        background-color: transparent;
        border: 1px solid {BORDER_HEX};
        border-radius: {RADIUS_MD}px;
        padding: 3px 6px;
        color: {TEXT_SECONDARY};
        font-size: {FONT_SIZE_XS}px;
        min-width: 0px;
    }}
    QPushButton:hover {{
        color: {TEXT_PRIMARY};
        border-color: {TEXT_SECONDARY};
    }}
    QPushButton:checked {{
        background-color: {ACCENT_SOFT_ORANGE};
        border-color: {ACCENT_ORANGE};
        color: {ACCENT_ORANGE};
    }}
"""

# ── Stepper (навигация шагов) ─────────────────────────────────────────────
QSS_STEPPER_STEP_INACTIVE = f"""
    QLabel {{
        color: {TEXT_SECONDARY};
        font-size: {FONT_SIZE_BODY}px;
        font-weight: 500;
        background: transparent;
    }}
"""

QSS_STEPPER_STEP_ACTIVE = f"""
    QLabel {{
        color: {ACCENT_ORANGE};
        font-size: {FONT_SIZE_BODY}px;
        font-weight: 500;
        background: transparent;
    }}
"""

QSS_STEPPER_NUMBER_INACTIVE = f"""
    QLabel {{
        background-color: {OVERLAY2_HEX};
        border: 1px solid {BORDER_HEX};
        border-radius: 12px;
        color: {TEXT_SECONDARY};
        font-size: {FONT_SIZE_SMALL}px;
        font-weight: 500;
        min-width: 24px;
        max-width: 24px;
        min-height: 24px;
        max-height: 24px;
        qproperty-alignment: AlignCenter;
    }}
"""

QSS_STEPPER_NUMBER_ACTIVE = f"""
    QLabel {{
        background-color: {ACCENT_ORANGE};
        border: 1px solid {ACCENT_ORANGE};
        border-radius: 12px;
        color: #ffffff;
        font-size: {FONT_SIZE_SMALL}px;
        font-weight: 600;
        min-width: 24px;
        max-width: 24px;
        min-height: 24px;
        max-height: 24px;
        qproperty-alignment: AlignCenter;
    }}
"""

# ── Заголовок секции в коллапсируемом блоке ───────────────────────────────
QSS_SECTION_HEADER = f"""
    QWidget#sectionHeader {{
        background-color: transparent;
        border-radius: {RADIUS_MD}px;
    }}
    QWidget#sectionHeader:hover {{
        background-color: {OVERLAY2_HEX};
    }}
"""

# ── Элемент чата (ChatItemWidget) ─────────────────────────────────────────
# Применяется как setStyleSheet() родителя с явными селекторами дочерних QLabel.
# Это единственный надёжный способ при динамическом _refresh_style().
QSS_CHAT_ITEM_NORMAL = f"""
    ChatItemWidget {{
        background-color: transparent;
        border: none;
        border-radius: {RADIUS_MD}px;
    }}
    ChatItemWidget:hover {{
        background-color: {OVERLAY2_HEX};
    }}
    ChatItemWidget QLabel#chatTitle {{
        color: {TEXT_PRIMARY};
        font-size: {FONT_SIZE_BODY}px;
        font-weight: 500;
        background: transparent;
    }}
    ChatItemWidget QLabel#chatMeta {{
        color: {TEXT_SECONDARY};
        font-size: {FONT_SIZE_XS}px;
        background: transparent;
    }}
    ChatItemWidget QLabel#chatCount {{
        color: {ACCENT_ORANGE};
        font-size: {FONT_SIZE_XS}px;
        background: transparent;
    }}
"""

QSS_CHAT_ITEM_SELECTED = f"""
    ChatItemWidget {{
        background-color: {ACCENT_SOFT_ORANGE};
        border: none;
        border-left: 3px solid {ACCENT_ORANGE};
        border-radius: 0 {RADIUS_MD}px {RADIUS_MD}px 0;
    }}
    ChatItemWidget QLabel#chatTitle {{
        color: {TEXT_PRIMARY};
        font-size: {FONT_SIZE_BODY}px;
        font-weight: 600;
        background: transparent;
    }}
    ChatItemWidget QLabel#chatMeta {{
        color: {TEXT_SECONDARY};
        font-size: {FONT_SIZE_XS}px;
        background: transparent;
    }}
    ChatItemWidget QLabel#chatCount {{
        color: {ACCENT_ORANGE};
        font-size: {FONT_SIZE_XS}px;
        background: transparent;
    }}
"""

# ── Иконки типов чатов (цвет фона и текста) ───────────────────────────────
CHAT_ICON_COLORS: dict[str, tuple[str, str]] = {
    "channel": (f"rgba(255,149,0,0.2)", ACCENT_ORANGE),
    "group":   (f"rgba(255,107,201,0.2)", ACCENT_PINK),
    "forum":   (f"rgba(255,107,201,0.2)", ACCENT_PINK),
    "private": (f"rgba(0,200,83,0.2)", COLOR_SUCCESS),
    "dm":      (f"rgba(0,102,255,0.2)", COLOR_DM),
}

def chat_icon_qss(chat_type: str) -> str:
    """Возвращает QSS для иконки QLabel по типу чата."""
    bg, fg = CHAT_ICON_COLORS.get(chat_type, (OVERLAY2_HEX, TEXT_SECONDARY))
    return f"""
        QLabel {{
            background-color: {bg};
            color: {fg};
            border-radius: {RADIUS_SM}px;
            font-size: {FONT_SIZE_BODY}px;
            min-width: 28px;
            max-width: 28px;
            min-height: 28px;
            max-height: 28px;
            qproperty-alignment: AlignCenter;
        }}
    """

# ── Бейдж (relation badge) ────────────────────────────────────────────────
QSS_BADGE_PINK = f"""
    QLabel {{
        background-color: {ACCENT_SOFT_PINK};
        color: {ACCENT_PINK};
        font-size: {FONT_SIZE_XS}px;
        padding: 2px 6px;
        border-radius: 20px;
        border: 1px solid {ACCENT_PINK};
    }}
"""

QSS_BADGE_ORANGE = f"""
    QLabel {{
        background-color: {ACCENT_SOFT_ORANGE};
        color: {ACCENT_ORANGE};
        font-size: {FONT_SIZE_XS}px;
        padding: 2px 6px;
        border-radius: 20px;
    }}
"""

# ── Кнопка-ссылка «ветки» ─────────────────────────────────────────────────
QSS_TOPIC_LINK = f"""
    QPushButton {{
        background-color: transparent;
        border: 1px solid {ACCENT_PINK};
        border-radius: 20px;
        padding: 1px 8px;
        color: {ACCENT_PINK};
        font-size: {FONT_SIZE_XS}px;
    }}
    QPushButton:hover {{
        background-color: {ACCENT_PINK};
        color: {BG_PRIMARY};
    }}
"""

# ── ProgressBar ───────────────────────────────────────────────────────────
QSS_PROGRESS = f"""
    QProgressBar {{
        background-color: {OVERLAY_HEX};
        border: 1px solid {BORDER_HEX};
        border-radius: {RADIUS_XS}px;
        text-align: center;
        color: {TEXT_PRIMARY};
        font-size: {FONT_SIZE_SMALL}px;
        height: 8px;
    }}
    QProgressBar::chunk {{
        background: qlineargradient(
            x1:0, y1:0, x2:1, y2:0,
            stop:0 {ACCENT_PINK},
            stop:1 {ACCENT_ORANGE}
        );
        border-radius: {RADIUS_XS}px;
    }}
"""

# ── DateEdit / DateRangePicker ────────────────────────────────────────────
QSS_DATE_EDIT = f"""
    QDateEdit {{
        background-color: {OVERLAY_HEX};
        border: 1px solid {BORDER_HEX};
        border-radius: {RADIUS_MD}px;
        padding: 6px 10px;
        color: {TEXT_PRIMARY};
        font-size: {FONT_SIZE_BODY}px;
    }}
    QDateEdit:focus {{
        border-color: {ACCENT_ORANGE};
    }}
    QDateEdit::drop-down {{
        border: none;
        width: 20px;
    }}
    QDateEdit::down-arrow {{
        image: none;
        border-left: 4px solid transparent;
        border-right: 4px solid transparent;
        border-top: 5px solid {TEXT_SECONDARY};
        margin-right: 6px;
    }}
    QCalendarWidget {{
        background-color: {BG_PRIMARY};
        color: {TEXT_PRIMARY};
    }}
    QCalendarWidget QWidget {{
        background-color: {BG_PRIMARY};
        color: {TEXT_PRIMARY};
        alternate-background-color: {OVERLAY_HEX};
    }}
    QCalendarWidget QToolButton {{
        color: {TEXT_PRIMARY};
        background-color: {OVERLAY_HEX};
        border-radius: {RADIUS_XS}px;
        padding: 4px;
    }}
    QCalendarWidget QToolButton:hover {{
        background-color: {ACCENT_SOFT_ORANGE};
        color: {ACCENT_ORANGE};
    }}
    QCalendarWidget QAbstractItemView:enabled {{
        color: {TEXT_PRIMARY};
        background-color: {BG_PRIMARY};
        selection-background-color: {ACCENT_ORANGE};
        selection-color: #ffffff;
    }}
    QCalendarWidget QAbstractItemView:disabled {{
        color: {TEXT_DISABLED};
    }}
"""

# ══════════════════════════════════════════════════════════════════════════════
# УТИЛИТА ПРИМЕНЕНИЯ СТИЛЯ
# ══════════════════════════════════════════════════════════════════════════════

# Реестр именованных стилей
_STYLE_REGISTRY: dict[str, str] = {
    "main_window":        QSS_MAIN_WINDOW,
    "card":               QSS_CARD,
    "input":              QSS_INPUT,
    "combobox":           QSS_COMBOBOX,
    "button":             QSS_BUTTON_BASE,
    "button_primary":     QSS_BUTTON_PRIMARY,
    "button_secondary":   QSS_BUTTON_SECONDARY,
    "button_icon":        QSS_BUTTON_ICON,
    "chat_list":          QSS_CHAT_LIST,
    "scroll_area":        QSS_SCROLL_AREA,
    "log_output":         QSS_LOG_OUTPUT,
    "label_title":        QSS_LABEL_TITLE,
    "label_section":      QSS_LABEL_SECTION,
    "label_secondary":    QSS_LABEL_SECONDARY,
    "label_hint":         QSS_LABEL_HINT,
    "media_button":       QSS_MEDIA_BUTTON,
    "chip_inactive":      QSS_CHIP_INACTIVE,
    "chip_active":        QSS_CHIP_ACTIVE,
    "user_tag":           QSS_USER_TAG,
    "toggle":             QSS_TOGGLE,
    "separator":          QSS_SEPARATOR,
    "filter_button":      QSS_FILTER_BUTTON,
    "chat_item_normal":   QSS_CHAT_ITEM_NORMAL,
    "chat_item_selected": QSS_CHAT_ITEM_SELECTED,
    "badge_pink":         QSS_BADGE_PINK,
    "badge_orange":       QSS_BADGE_ORANGE,
    "topic_link":         QSS_TOPIC_LINK,
    "progress":           QSS_PROGRESS,
    "date_edit":          QSS_DATE_EDIT,
}


def apply_style(widget: "QWidget", style_name: str) -> None:
    """
    Применяет именованный QSS-стиль к виджету.

    Пример:
        apply_style(my_button, "button_primary")
        apply_style(self.log_edit, "log_output")
    """
    qss = _STYLE_REGISTRY.get(style_name)
    if qss is None:
        raise ValueError(
            f"Unknown style '{style_name}'. "
            f"Available: {sorted(_STYLE_REGISTRY)}"
        )
    widget.setStyleSheet(qss)


def get_style(style_name: str) -> str:
    """
    Возвращает QSS-строку по имени без применения.
    Удобно для объединения стилей:
        combined = get_style("button") + get_style("button_primary")
    """
    qss = _STYLE_REGISTRY.get(style_name)
    if qss is None:
        raise ValueError(f"Unknown style '{style_name}'.")
    return qss


def combine_styles(*style_names: str) -> str:
    """
    Объединяет несколько именованных стилей в одну QSS-строку.
    Порядок важен: более специфичный стиль — последний.

    Пример:
        widget.setStyleSheet(combine_styles("button", "button_primary"))
    """
    return "\n".join(get_style(name) for name in style_names)


def setup_application_style(app: "QApplication") -> None:
    """
    Настраивает базовый стиль QApplication.
    Вызывать ОДИН РАЗ в main.py после создания app, до показа окон.

    Пример:
        app = QApplication(sys.argv)
        setup_application_style(app)
    """
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QPalette, QColor

    app.setStyle(APPLICATION_STYLE_FUSION)

    # Базовая тёмная палитра для всего приложения
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window,          QColor(BG_PRIMARY))
    palette.setColor(QPalette.ColorRole.WindowText,      QColor(TEXT_PRIMARY))
    palette.setColor(QPalette.ColorRole.Base,            QColor(OVERLAY_HEX))
    palette.setColor(QPalette.ColorRole.AlternateBase,   QColor(OVERLAY2_HEX))
    palette.setColor(QPalette.ColorRole.Text,            QColor(TEXT_PRIMARY))
    palette.setColor(QPalette.ColorRole.BrightText,      QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.Button,          QColor(OVERLAY_HEX))
    palette.setColor(QPalette.ColorRole.ButtonText,      QColor(TEXT_PRIMARY))
    palette.setColor(QPalette.ColorRole.Highlight,       QColor(ACCENT_ORANGE))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(TEXT_SECONDARY))
    palette.setColor(QPalette.ColorRole.Link,            QColor(ACCENT_ORANGE))
    palette.setColor(QPalette.ColorRole.LinkVisited,     QColor(ACCENT_PINK))

    # Отключённые виджеты
    palette.setColor(QPalette.ColorGroup.Disabled,
                     QPalette.ColorRole.Text,       QColor(TEXT_DISABLED))
    palette.setColor(QPalette.ColorGroup.Disabled,
                     QPalette.ColorRole.ButtonText, QColor(TEXT_DISABLED))

    app.setPalette(palette)

    # Глобальный базовый QSS (фон + шрифт)
    app.setStyleSheet(f"""
        QWidget {{
            font-family: {FONT_FAMILY};
            font-size: {FONT_SIZE_BODY}px;
            color: {TEXT_PRIMARY};
        }}
        QToolTip {{
            background-color: {BG_PRIMARY};
            color: {TEXT_PRIMARY};
            border: 1px solid {BORDER_HEX};
            border-radius: {RADIUS_XS}px;
            padding: 4px 8px;
            font-size: {FONT_SIZE_SMALL}px;
        }}
    """)
