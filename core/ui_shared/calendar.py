"""
ui_shared/calendar.py.
Виджет выбора диапазона дат.

Рефакторинг оригинального calendar_widget.py:
  - Стили заменены на токены из ui_shared/styles.py
  - Убраны inline-цвета, используются константы
  - Сигнатура и логика DateRangeWidget сохранены полностью
"""

from __future__ import annotations
import logging
from datetime import datetime, date as date_type
from typing import Optional, Tuple

from PySide6.QtCore import Qt, QDate, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QDateEdit,
)

from core.ui_shared import styles

logger = logging.getLogger(__name__)

# Быстрые периоды (дни → метка)
QUICK_RANGES: list[tuple[int, str]] = [
    (7, "7д"),
    (30, "30д"),
    (90, "3м"),
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
        # «За всё время» умел выдавать только ползунок на максимуме. Ползунка
        # больше нет, поэтому состояние живёт здесь: кнопка «Всё время» его
        # включает, любая другая кнопка и правка полей — гасят.
        self._all_time: bool = True

        self._build_ui()

    # ─────────────────────────────────────────────
    # Построение UI
    # ─────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(styles.PAD_SMALL)

        # RD-9: одна страница вместо стопки из двух. Ползунок глубины дублировал
        # быстрые кнопки, а понятие «режим» приходилось объяснять подписью.
        root.addWidget(self._build_dates_page())

    def _build_dates_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, styles.PAD_TINY, 0, 0)
        layout.setSpacing(styles.PAD_SMALL)

        # Быстрые кнопки
        quick_row = QHBoxLayout()
        quick_row.setSpacing(4)
        for days, label in [(None, "Всё время")] + list(QUICK_RANGES):
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
            if days is None:
                self._all_time_btn = btn
            quick_row.addWidget(btn)
        layout.addLayout(quick_row)

        self._dates_toggle = QPushButton("Указать точные даты  ▸")
        self._dates_toggle.setCheckable(True)
        self._dates_toggle.setCursor(Qt.PointingHandCursor)
        self._dates_toggle.setStyleSheet(
            f"QPushButton {{"
            f"  background: transparent; border: none; text-align: left;"
            f"  color: {styles.TEXT_MUTED}; font-size: {styles.FONT_TINY}px;"
            f"  padding: 2px 0;"
            f"}}"
            f"QPushButton:hover {{ color: white; }}"
        )
        self._dates_toggle.toggled.connect(self._on_dates_toggled)
        layout.addWidget(self._dates_toggle)

        self._dates_box = QWidget()
        box = QVBoxLayout(self._dates_box)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(styles.PAD_TINY)
        box.addLayout(self._build_date_row("От:", "start"))
        box.addLayout(self._build_date_row("До:", "end"))
        self._dates_box.setVisible(False)
        layout.addWidget(self._dates_box)

        # Инфо о диапазоне
        self.range_info = QLabel("За всё время")
        self.range_info.setAlignment(Qt.AlignCenter)
        self.range_info.setStyleSheet(
            f"color: {styles.TEXT_DISABLED}; font-size: {styles.FONT_TINY}px;"
        )
        layout.addWidget(self.range_info)

        return page

    def _on_dates_toggled(self, checked: bool) -> None:
        self._dates_box.setVisible(checked)
        self._dates_toggle.setText(
            "Указать точные даты  ▾" if checked else "Указать точные даты  ▸"
        )
        # Пересчёт вверх по цепочке: иначе карточка держит прежнюю высоту.
        w = self
        while w is not None:
            w.adjustSize()
            w = w.parentWidget()

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

    def _on_date_changed(self) -> None:
        """Обновить подпись диапазона и испустить сигнал."""

        # Правка дат руками означает конкретный период, а не «всё время».
        self._all_time = False
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

    def _set_quick_range(self, days) -> None:
        """Установить быстрый диапазон дат. days=None — «за всё время»."""

        if days is None:
            self._all_time = True
            self.range_info.setText("За всё время")
            self.date_changed.emit(None, None)
            return

        self._all_time = False
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

        if self._all_time:
            return None, None

        start_q = self.start_date_edit.date()
        end_q = self.end_date_edit.date()

        start_py: date_type = start_q.toPython()
        end_py: date_type = end_q.toPython()

        start_dt = datetime.combine(start_py, datetime.min.time())
        end_dt = datetime.combine(end_py, datetime.max.time())

        return start_dt, end_dt

