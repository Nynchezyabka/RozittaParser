"""
ui_shared/calendar.py
Виджет выбора диапазона дат.

Рефакторинг оригинального calendar_widget.py:
  - Стили заменены на токены из ui_shared/styles.py
  - Убраны inline-цвета, используются константы
  - Сигнатура и логика DateRangeWidget сохранены полностью
"""
from __future__ import annotations
import logging
from datetime import datetime, timedelta, date as date_type
from typing import Optional, Tuple

from PySide6.QtCore import Qt, QDate, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QCalendarWidget, QDateEdit, QStackedWidget,
    QSlider,
)

from core.ui_shared import styles

logger = logging.getLogger(__name__)

# Быстрые периоды (дни → метка)
QUICK_RANGES: list[tuple[int, str]] = [
    (7,   "7д"),
    (30,  "30д"),
    (90,  "3м"),
    (180, "6м"),
]


class DateRangeWidget(QWidget):
    """
    Виджет выбора диапазона дат.

    Два режима:
        - Глубина (слайдер, дни назад от сегодня)
        - Диапазон (QDateEdit «от» / «до» с быстрыми кнопками)

    Signals
    -------
    date_changed : Signal(object, object)
        Испускается при любом изменении дат.
        Аргументы: (start_datetime | None, end_datetime | None)
        None, None означает «за всё время».
    """

    date_changed = Signal(object, object)

    # Порог «за всё время» совпадает с DAYS_LIMIT_ALL_TIME из config.py
    ALL_TIME_DAYS = 365

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.current_mode: str = "slider"  # "slider" | "dates"

        self._build_ui()

    # ─────────────────────────────────────────────
    # Построение UI
    # ─────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(styles.PAD_SMALL)

        # Шапка: заголовок + переключатель
        root.addLayout(self._build_header())

        # Стек: слайдер / календарь
        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_slider_page())   # index 0
        self.stack.addWidget(self._build_dates_page())    # index 1
        root.addWidget(self.stack)

    def _build_header(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        self.mode_label = QLabel("Режим: Глубина (дни)")
        self.mode_label.setStyleSheet(
            f"color: {styles.ACCENT_ORANGE}; "
            f"font-weight: bold; font-size: {styles.FONT_SMALL}px;"
        )

        self.toggle_btn = QPushButton("📆 Выбрать даты")
        self.toggle_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: rgba(166,130,255, 70);"
            f"  border: 1px solid rgba(166,130,255, 120);"
            f"  border-radius: {styles.RADIUS_TINY}px;"
            f"  padding: 4px 10px;"
            f"  color: white;"
            f"  font-size: {styles.FONT_SMALL}px;"
            f"}}"
            f"QPushButton:hover {{"
            f"  background: rgba(166,130,255, 120);"
            f"}}"
        )
        self.toggle_btn.setCursor(Qt.PointingHandCursor)
        self.toggle_btn.clicked.connect(self._toggle_mode)

        layout.addWidget(self.mode_label)
        layout.addStretch()
        layout.addWidget(self.toggle_btn)
        return layout

    def _build_slider_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, styles.PAD_TINY, 0, 0)
        layout.setSpacing(styles.PAD_TINY)

        # Значение слайдера
        self.depth_value = QLabel("30 дней")
        self.depth_value.setAlignment(Qt.AlignCenter)
        self.depth_value.setStyleSheet(
            f"color: {styles.ACCENT_AMBER}; "
            f"font-size: {styles.FONT_BODY + 2}px; "
            f"font-weight: bold;"
        )
        layout.addWidget(self.depth_value)

        # Слайдер
        self.days_slider = QSlider(Qt.Horizontal)
        self.days_slider.setMinimum(1)
        self.days_slider.setMaximum(self.ALL_TIME_DAYS)
        self.days_slider.setValue(30)
        self.days_slider.valueChanged.connect(self._on_slider_changed)
        layout.addWidget(self.days_slider)

        # Метки мин/макс
        labels_row = QHBoxLayout()
        lbl_min = QLabel("1 день")
        lbl_min.setStyleSheet(
            f"color: {styles.TEXT_DISABLED}; font-size: {styles.FONT_TINY}px;"
        )
        lbl_max = QLabel("Всё время")
        lbl_max.setStyleSheet(
            f"color: {styles.TEXT_DISABLED}; font-size: {styles.FONT_TINY}px;"
        )
        lbl_max.setAlignment(Qt.AlignRight)
        labels_row.addWidget(lbl_min)
        labels_row.addStretch()
        labels_row.addWidget(lbl_max)
        layout.addLayout(labels_row)

        return page

    def _build_dates_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, styles.PAD_TINY, 0, 0)
        layout.setSpacing(styles.PAD_SMALL)

        # Быстрые кнопки
        quick_row = QHBoxLayout()
        quick_row.setSpacing(4)
        for days, label in QUICK_RANGES:
            btn = QPushButton(label)
            btn.setFixedHeight(26)
            btn.setStyleSheet(
                f"QPushButton {{"
                f"  background: rgba(255,255,255,15);"
                f"  border: 1px solid rgba(255,255,255,30);"
                f"  border-radius: {styles.RADIUS_TINY}px;"
                f"  color: {styles.TEXT_MUTED};"
                f"  font-size: {styles.FONT_TINY}px;"
                f"}}"
                f"QPushButton:hover {{"
                f"  background: rgba(166,130,255,50);"
                f"  color: white;"
                f"}}"
            )
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _, d=days: self._set_quick_range(d))
            quick_row.addWidget(btn)
        layout.addLayout(quick_row)

        # Поле «От»
        layout.addLayout(self._build_date_row("От:", "start"))

        # Поле «До»
        layout.addLayout(self._build_date_row("До:", "end"))

        # Инфо о диапазоне
        self.range_info = QLabel("Диапазон: 30 дней")
        self.range_info.setAlignment(Qt.AlignCenter)
        self.range_info.setStyleSheet(
            f"color: {styles.TEXT_DISABLED}; font-size: {styles.FONT_TINY}px;"
        )
        layout.addWidget(self.range_info)

        return page

    def _build_date_row(self, label_text: str, field: str) -> QHBoxLayout:
        """Строит строку 'От:' или 'До:' с QDateEdit."""
        row = QHBoxLayout()
        row.setSpacing(styles.PAD_SMALL)

        lbl = QLabel(label_text)
        lbl.setFixedWidth(28)
        lbl.setStyleSheet(
            f"color: {styles.TEXT_MUTED}; font-size: {styles.FONT_SMALL}px;"
        )

        date_edit = QDateEdit()
        date_edit.setCalendarPopup(True)
        date_edit.setDisplayFormat("dd.MM.yyyy")

        if field == "start":
            date_edit.setDate(QDate.currentDate().addDays(-30))
            self.start_date_edit = date_edit
        else:
            date_edit.setDate(QDate.currentDate())
            self.end_date_edit = date_edit

        date_edit.dateChanged.connect(self._on_date_changed)

        # Стиль через QSS (применится из GLOBAL_STYLE, но перекроем border-radius)
        date_edit.setStyleSheet(
            f"QDateEdit {{"
            f"  background: rgba(0,0,0,100);"
            f"  border: 1px solid rgba(255,255,255,26);"
            f"  border-radius: {styles.RADIUS_SMALL}px;"
            f"  padding: 6px 10px;"
            f"  color: {styles.TEXT_LIGHT};"
            f"  font-size: {styles.FONT_SMALL}px;"
            f"}}"
            f"QDateEdit:focus {{"
            f"  border-color: {styles.ACCENT_LAVENDER};"
            f"}}"
        )

        row.addWidget(lbl)
        row.addWidget(date_edit, stretch=1)
        return row

    # ─────────────────────────────────────────────
    # Обработчики событий
    # ─────────────────────────────────────────────

    def _toggle_mode(self) -> None:
        """Переключение между режимами слайдер ↔ выбор дат."""
        if self.current_mode == "slider":
            self.current_mode = "dates"
            self.stack.setCurrentIndex(1)
            self.mode_label.setText("Режим: Выбор дат")
            self.toggle_btn.setText("📊 Глубина (дни)")
        else:
            self.current_mode = "slider"
            self.stack.setCurrentIndex(0)
            self.mode_label.setText("Режим: Глубина (дни)")
            self.toggle_btn.setText("📆 Выбрать даты")
        # Испускаем сигнал с текущими значениями
        start, end = self.get_date_range()
        self.date_changed.emit(start, end)

    def _on_slider_changed(self, value: int) -> None:
        """Обновить текст значения слайдера и испустить сигнал."""
        if value >= self.ALL_TIME_DAYS:
            self.depth_value.setText("За всё время")
        else:
            self.depth_value.setText(f"{value} дней")
        start, end = self.get_date_range()
        self.date_changed.emit(start, end)

    def _on_date_changed(self) -> None:
        """Обновить подпись диапазона и испустить сигнал."""
        start_q = self.start_date_edit.date()
        end_q = self.end_date_edit.date()
        days = start_q.daysTo(end_q)

        if days < 0:
            self.range_info.setText("⚠️ Начальная дата позже конечной!")
            self.range_info.setStyleSheet(
                f"color: {styles.ACCENT_CORAL}; font-size: {styles.FONT_TINY}px;"
            )
        else:
            self.range_info.setText(f"Диапазон: {days} дней")
            self.range_info.setStyleSheet(
                f"color: {styles.TEXT_DISABLED}; font-size: {styles.FONT_TINY}px;"
            )

        start, end = self.get_date_range()
        self.date_changed.emit(start, end)

    def _set_quick_range(self, days: int) -> None:
        """Установить быстрый диапазон дат."""
        end = QDate.currentDate()
        start = end.addDays(-days)
        # Блокируем сигналы чтобы не дублировать date_changed
        self.start_date_edit.blockSignals(True)
        self.end_date_edit.blockSignals(True)
        self.start_date_edit.setDate(start)
        self.end_date_edit.setDate(end)
        self.start_date_edit.blockSignals(False)
        self.end_date_edit.blockSignals(False)
        self._on_date_changed()

    # ─────────────────────────────────────────────
    # Публичный API
    # ─────────────────────────────────────────────

    def get_date_range(self) -> Tuple[Optional[datetime], Optional[datetime]]:
        """
        Вернуть выбранный диапазон как (start_datetime, end_datetime).

        Возвращает (None, None) для режима «За всё время» (слайдер ≥ ALL_TIME_DAYS).
        Timezone-aware: naive datetime (без tzinfo) — caller сам добавит tz при необходимости.
        """
        if self.current_mode == "slider":
            days = self.days_slider.value()
            if days >= self.ALL_TIME_DAYS:
                return None, None
            end_dt = datetime.now()
            start_dt = end_dt - timedelta(days=days)
            return start_dt, end_dt

        # Режим выбора дат
        start_q = self.start_date_edit.date()
        end_q = self.end_date_edit.date()

        start_py: date_type = start_q.toPython()
        end_py:   date_type = end_q.toPython()

        start_dt = datetime.combine(start_py, datetime.min.time())
        end_dt   = datetime.combine(end_py,   datetime.max.time())

        return start_dt, end_dt

    def set_days(self, days: int) -> None:
        """Программно установить значение слайдера (не переключая режим)."""
        self.days_slider.setValue(min(days, self.ALL_TIME_DAYS))

    def get_days(self) -> int:
        """Вернуть значение слайдера в днях."""
        return self.days_slider.value()