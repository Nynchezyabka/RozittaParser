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
        # Ручная правка полей вызывает _on_date_changed() точно так же, как
        # клик по быстрой кнопке (см. _set_quick_range). Флаг отличает одно
        # от другого, чтобы не гасить подсветку только что нажатой кнопки.
        self._applying_quick_range: bool = False

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

        # Быстрые кнопки — подсвечена ровно одна, та что выбрана сейчас.
        # Без QButtonGroup: его exclusive-режим не позволяет программно снять
        # отметку с единственной выбранной кнопки (рассчитан на радиокнопки,
        # где одна всегда должна быть включена), а нам нужно уметь погасить
        # все при ручной правке полей. Подсветка — под explicit-контролем
        # через _highlight_quick_button().
        quick_row = QHBoxLayout()
        quick_row.setSpacing(4)
        self._quick_buttons: list[QPushButton] = []
        self._quick_button_days: dict[QPushButton, object] = {}
        for days, label in [(None, "Всё время")] + list(QUICK_RANGES):
            btn = QPushButton(label)
            btn.setFixedHeight(26)
            btn.setCheckable(True)
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
                f"QPushButton:checked {{"
                f"  background: {styles.ACCENT_SOFT_ORANGE};"
                f"  border: 1px solid {styles.ACCENT_ORANGE};"
                f"  color: {styles.ACCENT_ORANGE};"
                f"}}"
            )
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _, d=days: self._set_quick_range(d))
            if days is None:
                self._all_time_btn = btn
            self._quick_buttons.append(btn)
            self._quick_button_days[btn] = days
            quick_row.addWidget(btn)
        self._highlight_quick_button(None)  # по умолчанию — «за всё время»
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

        # Период теперь виден по подсветке кнопки — отдельная строка
        # «Диапазон: N дней» только съедала место. Предупреждение о
        # некорректном диапазоне («От» позже «До») оставлено — это не
        # информационная надпись, а сигнал о нерабочих датах; по умолчанию
        # скрыто и места не занимает.
        self.range_info = QLabel("")
        self.range_info.setAlignment(Qt.AlignCenter)
        self.range_info.setStyleSheet(
            f"color: {styles.ACCENT_CORAL}; font-size: {styles.FONT_TINY}px;"
        )
        self.range_info.setVisible(False)
        layout.addWidget(self.range_info)

        return page

    def _on_dates_toggled(self, checked: bool) -> None:
        self._dates_box.setVisible(checked)
        self._dates_toggle.setText(
            "Указать точные даты  ▾" if checked else "Указать точные даты  ▸"
        )
        # Пересчёт вверх по цепочке, но БЕЗ adjustSize(): на QMainWindow это
        # вызывает resize() до sizeHint() и стягивает окно к minimumSize()
        # (баг: окно менялось само по себе при открытии/закрытии блока дат).
        # updateGeometry() пересчитывает sizeHint и просит layout родителя
        # переразложиться, не трогая фактический размер окна. Останавливаемся
        # на уровне окна — выше поднимать геометрию незачем.
        w = self
        while w is not None:
            w.updateGeometry()
            if w.isWindow():
                break
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

    _NO_QUICK_MATCH = object()  # ни одна быстрая кнопка не подходит диапазону

    def _highlight_quick_button(self, days) -> None:
        """
        Подсветить кнопку, отвечающую периоду days; остальные — погасить.

        Проставляется абсолютно, а не переключением: сколько раз ни жми
        уже подсвеченную кнопку, результат не изменится. days=_NO_QUICK_MATCH
        гасит все — состояние для ручной правки полей.
        """
        for btn, d in self._quick_button_days.items():
            btn.setChecked(d == days)

    def _on_date_changed(self) -> None:
        """Проверить диапазон, снять неактуальную подсветку, испустить сигнал."""

        # Правка дат руками означает конкретный период, а не «всё время».
        self._all_time = False
        if not self._applying_quick_range:
            # Ручная правка полей — это не один из быстрых периодов, ни одна
            # кнопка сейчас выбранному диапазону не соответствует.
            self._highlight_quick_button(self._NO_QUICK_MATCH)

        start_q = self.start_date_edit.date()
        end_q = self.end_date_edit.date()
        days = start_q.daysTo(end_q)

        is_invalid = days < 0
        self.range_info.setVisible(is_invalid)
        if is_invalid:
            self.range_info.setText("⚠️ Начальная дата позже конечной!")

        start, end = self.get_date_range()
        self.date_changed.emit(start, end)

    def _set_quick_range(self, days) -> None:
        """Установить быстрый диапазон дат. days=None — «за всё время»."""

        self._highlight_quick_button(days)

        if days is None:
            self._all_time = True
            self.range_info.setVisible(False)
            self.date_changed.emit(None, None)
            return

        self._all_time = False
        end = QDate.currentDate()
        start = end.addDays(-days)
        # _on_date_changed() гасит подсветку при РУЧНОЙ правке полей — но не
        # должен гасить ту, что мы только что явно выставили строкой выше.
        self._applying_quick_range = True
        try:
            # Блокируем сигналы чтобы не дублировать date_changed
            self.start_date_edit.blockSignals(True)
            self.end_date_edit.blockSignals(True)
            self.start_date_edit.setDate(start)
            self.end_date_edit.setDate(end)
            self.start_date_edit.blockSignals(False)
            self.end_date_edit.blockSignals(False)
            self._on_date_changed()
        finally:
            self._applying_quick_range = False

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

