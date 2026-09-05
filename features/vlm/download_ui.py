"""
features/vlm/download_ui.py — скачивание компонента с прогрессом.

Отдельный модуль, а не ещё двести строк в main_window.py: скачивание нужно
будет и другим компонентам (в спеке следом идёт STT видео), и переиспользовать
его из окна на четыре тысячи строк было бы нечем.

Здесь два класса: воркер, который качает, и диалог, который за ним смотрит.
Оба знают только имя компонента — ничего специфичного для описания картинок.
"""

from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from core.components.manager import ComponentManager
from core.exceptions import ComponentCancelled, ComponentError

logger = logging.getLogger(__name__)


class ComponentDownloadWorker(QThread):
    """Качает и ставит компонент. Весь Qt здесь, менеджер остаётся чистым."""

    progress  = Signal(int, int)     # скачано, всего (в байтах)
    log       = Signal(str)
    done      = Signal()
    failed    = Signal(str)

    def __init__(self, components_dir: str, registry_url: str,
                 name: str, parent=None) -> None:
        super().__init__(parent)
        self._manager = ComponentManager(components_dir, registry_url)
        self._name = name
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        try:
            self.log.emit("Получаю список компонентов…")
            registry = self._manager.fetch_registry()
            version, info = self._manager.pick_version(registry, self._name)
            self.log.emit(f"Скачиваю версию {version}…")
            self._manager.download(
                self._name, version, info,
                progress_cb=self.progress.emit,
                cancel_flag=lambda: self._cancelled,
            )
        except ComponentCancelled:
            self.failed.emit("")            # пустая строка = отменено, не сбой
        except ComponentError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:            # noqa: BLE001
            logger.exception("скачивание компонента %s", self._name)
            self.failed.emit(str(exc))
        else:
            self.done.emit()


class ComponentDownloadDialog(QDialog):
    """
    Окно скачивания компонента.

    Одно окно на две стадии — вопрос и прогресс, — а не два подряд: человек
    нажал «Скачать» и остаётся на месте, вместо того чтобы смотреть, как
    одно окно захлопывается и открывается другое.

    Отмена доступна всегда и убирает за собой: полуустановленная папка
    опаснее отсутствующей, и об этом заботится сам ComponentManager.
    """

    def __init__(self, components_dir: str, registry_url: str,
                 name: str = "vlm", size_hint: str = "~3 ГБ",
                 title: str = "Распознавание изображений",
                 parent=None) -> None:
        super().__init__(parent)
        self._worker: Optional[ComponentDownloadWorker] = None
        self._components_dir = components_dir
        self._registry_url = registry_url
        self._name = name

        self.setWindowTitle("Загрузка компонента")
        self.setModal(True)
        self.setMinimumWidth(430)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(10)

        header = QLabel(f"Компонент «{title}»")
        header.setStyleSheet("font-size: 16px; font-weight: 500;")
        root.addWidget(header)

        self._text = QLabel(
            f"Функция требует загружаемый компонент ({size_hint}). "
            f"Он скачивается один раз и остаётся на диске.\n\n"
            f"Скачать сейчас?"
        )
        self._text.setWordWrap(True)
        root.addWidget(self._text)

        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setVisible(False)
        root.addWidget(self._bar)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setVisible(False)
        root.addWidget(self._status)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self._cancel_btn = QPushButton("Отмена")
        self._cancel_btn.clicked.connect(self._on_cancel)
        buttons.addWidget(self._cancel_btn)
        self._ok_btn = QPushButton("Скачать")
        self._ok_btn.setDefault(True)
        self._ok_btn.clicked.connect(self._on_start)
        buttons.addWidget(self._ok_btn)
        root.addLayout(buttons)

    # ── Стадии ───────────────────────────────────────────────────────────

    def _on_start(self) -> None:
        self._ok_btn.setEnabled(False)
        self._text.setText("Компонент скачивается. Окно можно не закрывать.")
        self._bar.setVisible(True)
        self._bar.setValue(0)
        self._status.setVisible(True)
        self._status.setText("Подключаюсь…")

        self._worker = ComponentDownloadWorker(
            self._components_dir, self._registry_url, self._name, parent=self)
        self._worker.progress.connect(self._on_progress, Qt.UniqueConnection)
        self._worker.log.connect(self._status.setText, Qt.UniqueConnection)
        self._worker.done.connect(self._on_done, Qt.UniqueConnection)
        self._worker.failed.connect(self._on_failed, Qt.UniqueConnection)
        self._worker.start()

    def _on_progress(self, done: int, total: int) -> None:
        if total > 0:
            self._bar.setValue(min(int(done / total * 100), 100))
            self._status.setText(
                f"Скачано {done / 1e6:.0f} из {total / 1e6:.0f} МБ")
        else:
            # Размер неизвестен — показываем хотя бы объём, а не ноль.
            self._bar.setRange(0, 0)
            self._status.setText(f"Скачано {done / 1e6:.0f} МБ")

    def _on_done(self) -> None:
        self.accept()

    def _on_failed(self, message: str) -> None:
        if not message:                     # отменено пользователем
            self.reject()
            return
        self._bar.setVisible(False)
        self._text.setText("Не удалось скачать компонент.")
        self._status.setText(message)
        self._ok_btn.setEnabled(True)
        self._ok_btn.setText("Повторить")

    def _on_cancel(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._status.setText("Останавливаю…")
            self._worker.cancel()
            return                          # закроемся по сигналу failed
        self.reject()

    def closeEvent(self, event) -> None:
        """
        Крестик работает как «Отмена».

        Закрыть окно и оставить поток качать три гигабайта в фоне — верный
        способ получить занятый диск и непонятную ошибку через полчаса.
        """
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(5000)
        super().closeEvent(event)
