"""
features/update_archive/report_dialog.py — диалог отчёта об обновлении архива.

Шаг 1 (stub): показывает dict отчёта в виде формы.
Шаг 2+: заменит тексты на реальные данные.
"""

from __future__ import annotations

from typing import Any, Dict

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QLabel, QVBoxLayout,
)

from core.ui_shared.styles import (
    ACCENT_ORANGE, ACCENT_SOFT_ORANGE,
    BORDER_HEX, FONT_FAMILY, FONT_SIZE_BODY, FONT_SIZE_SMALL,
    RADIUS_MD, TEXT_PRIMARY, TEXT_SECONDARY,
)


# Человекочитаемые подписи для ключей отчёта
_LABELS: Dict[str, str] = {
    "chat_title":          "Чат",
    "updated_at":          "Время обновления",
    "new_posts":           "Новых постов",
    "new_comments":        "Новых комментариев",
    "new_media":           "Новых медиа",
    "transcribed_videos":  "Транскрибировано видео",
    "skipped":             "Пропущено",
    "duration_sec":        "Длительность (сек)",
    "stub":                "Режим",
}


class UpdateReportDialog(QDialog):
    """
    Диалог отчёта об обновлении архива.  # ── Update Archive stage 1 ──

    Args:
        report: dict с ключами chat_title, updated_at, new_posts, ...
        parent: родительский виджет.
    """

    def __init__(self, report: Dict[str, Any], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Обновление архива \u2014 отчёт")
        self.setModal(True)
        self.setMinimumWidth(420)

        self.setStyleSheet(self._stylesheet())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(12)

        # Заголовок
        title = QLabel("\N{CYCLONE} Архив обновлён")
        title.setStyleSheet(
            f"color: {ACCENT_ORANGE}; font-size: {FONT_SIZE_BODY + 4}px; "
            f"font-weight: bold; font-family: {FONT_FAMILY};"
        )
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        # Форма с данными
        form = QFormLayout()
        form.setSpacing(8)
        form.setContentsMargins(0, 0, 0, 0)

        for key, label_text in _LABELS.items():
            if key not in report:
                continue
            value = report[key]
            # stub=True -> показываем «Тестовый (stub)»
            if key == "stub":
                value = "Тестовый (stub)" if value else "Реальный"
            elif key == "duration_sec":
                try:
                    value = f"{float(value):.1f}"
                except (TypeError, ValueError):
                    value = str(value)
            else:
                value = str(value)

            lbl_key = QLabel(label_text)
            lbl_key.setStyleSheet(
                f"color: {TEXT_SECONDARY}; font-family: {FONT_FAMILY}; "
                f"font-size: {FONT_SIZE_SMALL}px;"
            )
            lbl_val = QLabel(value)
            lbl_val.setStyleSheet(
                f"color: {TEXT_PRIMARY}; font-family: {FONT_FAMILY}; "
                f"font-size: {FONT_SIZE_SMALL}px; font-weight: bold;"
            )
            form.addRow(lbl_key, lbl_val)

        layout.addLayout(form)

        # Кнопка закрытия
        btn_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btn_box.button(QDialogButtonBox.StandardButton.Close).setText("Закрыть")
        btn_box.rejected.connect(self.reject)
        btn_box.accepted.connect(self.accept)
        layout.addWidget(btn_box)

    @staticmethod
    def _stylesheet() -> str:
        return (
            f"QDialog {{ background: #1e1e2e; border: 1px solid {BORDER_HEX}; "
            f"border-radius: {RADIUS_MD}px; }}"
            "QLabel { background: transparent; }"
            f"QPushButton {{ background: {ACCENT_SOFT_ORANGE}; color: {TEXT_PRIMARY}; "
            f"border: 1px solid {ACCENT_ORANGE}; border-radius: 4px; "
            f"padding: 6px 16px; font-family: {FONT_FAMILY}; "
            f"font-size: {FONT_SIZE_SMALL}px; }}"
            f"QPushButton:hover {{ background: {ACCENT_ORANGE}; }}"
        )
