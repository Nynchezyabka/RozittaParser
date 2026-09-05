"""
features/vlm/ui.py — VlmWorker: описание изображений в отдельном потоке.

Весь Qt подсистемы живёт здесь. Форма повторяет core/stt/worker.py: тот же
набор сигналов, та же пакетная обработка, тот же способ остановки.

Работу делает не этот класс, а компонент (COMPONENTS.md). Воркер только
готовит задание, зовёт ComponentManager и раскладывает результат по БД:
запись в SQLite делает главное приложение и никто больше — компонент про
базу Розитты не знает вовсе.
"""

from __future__ import annotations

import logging
import os
from typing import List, Optional

from PySide6.QtCore import QThread, Signal

from core.components.manager import ComponentManager
from core.database import DBManager
from core.exceptions import (
    ComponentCancelled,
    ComponentError,
    ComponentProtocolError,
    RegistryError,
)

logger = logging.getLogger(__name__)

COMPONENT_NAME = "vlm"

# Потолок на задание: минута на картинку, но не меньше десяти минут.
# Формула из COMPONENTS.md §6; замер CM-0 даёт 33 секунды на процессоре,
# так что минута — двукратный запас, а нижняя граница нужна для коротких
# пачек, где сама загрузка весов занимает больше самой работы.
_SEC_PER_IMAGE = 60
_MIN_TIMEOUT = 600


class VlmWorker(QThread):
    """
    Пакетное описание изображений чата.

    Usage:
        worker = VlmWorker(db_path, chat_id, components_dir, registry_url)
        worker.log_message.connect(...)
        worker.progress.connect(progress_bar.setValue)
        worker.finished.connect(on_done)
        worker.start()
    """

    log_message     = Signal(str)
    progress        = Signal(int)
    error           = Signal(str)
    character_state = Signal(str)
    finished        = Signal()

    def __init__(
        self,
        db_path:        str,
        chat_id:        int,
        components_dir: str,
        registry_url:   str,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._db_path = db_path
        self._chat_id = chat_id
        self._manager = ComponentManager(components_dir, registry_url)
        self._cancelled = False

    def cancel(self) -> None:
        """
        Просит остановиться. Опрашивается между картинками.

        Не terminate(): компонент — отдельный процесс, и убивать его на
        полуслове значило бы потерять уже описанные картинки, которые ещё
        не доехали до БД.
        """
        self._cancelled = True

    # ── Поток ────────────────────────────────────────────────────────────

    def run(self) -> None:
        try:
            self._describe()
        except ComponentCancelled:
            self.log_message.emit("⏹ Описание изображений остановлено")
        except ComponentProtocolError as exc:
            self.error.emit(str(exc))
        except (ComponentError, RegistryError) as exc:
            self.error.emit(str(exc))
        except Exception as exc:                      # noqa: BLE001
            logger.exception("VlmWorker: непредвиденный сбой")
            self.error.emit(f"Описание изображений не удалось: {exc}")
        finally:
            self.finished.emit()

    def _describe(self) -> None:
        comp = self._manager.get_installed(COMPONENT_NAME)
        if comp is None:
            # Не ошибка: функцию включили, компонент не поставили. Диалог
            # скачивания — забота интерфейса, воркер просто не делает ничего.
            self.log_message.emit(
                "🖼 Компонент описания изображений не установлен — пропускаю")
            return
        if not comp.is_runnable:
            self.error.emit(
                "Компонент описания изображений повреждён (возможно, его "
                "удалил антивирус). Переустановите его в настройках."
            )
            return

        with DBManager(self._db_path) as db:
            candidates = db.get_vlm_candidates(self._chat_id)
            paths = [row["media_path"] for row in candidates
                     if row["media_path"] and os.path.isfile(row["media_path"])]
            by_path = {row["media_path"]: row["message_id"]
                       for row in candidates if row["media_path"]}

            missing = len(candidates) - len(paths)
            if missing:
                self.log_message.emit(
                    f"🖼 Пропускаю {missing} картинок: файлов нет на диске")
            if not paths:
                self.log_message.emit("🖼 Нечего описывать")
                return

            self.character_state.emit("process")
            self.log_message.emit(f"🖼 Описываю изображения: {len(paths)} шт.")
            self.progress.emit(0)

            result = self._manager.run(
                comp,
                {"task": "describe_images", "model": "base",
                 "language": "ru", "images": paths},
                progress_cb=self._on_progress,
                cancel_flag=lambda: self._cancelled,
                timeout_sec=max(_MIN_TIMEOUT, _SEC_PER_IMAGE * len(paths)),
            )
            saved = self._save(db, result, by_path)

        self.progress.emit(100)
        self.character_state.emit("success")
        self.log_message.emit(f"✅ Описано изображений: {saved}")

    def _on_progress(self, done: int, total: int) -> None:
        if total > 0:
            self.progress.emit(min(int(done / total * 100), 99))

    def _save(self, db: DBManager, result: dict, by_path: dict) -> int:
        """
        Раскладывает результат по БД.

        Описания пишутся по одному, а не пачкой: прогон на пятистах
        картинках может занять часы, и оборвавшись на середине он должен
        оставить сделанное, а не откатить всё.
        """
        descriptions = result.get("descriptions") or {}
        errors = result.get("errors") or {}
        model = result.get("model") or "base"
        saved = 0

        for path, text in descriptions.items():
            message_id = by_path.get(path)
            if message_id is None or not text:
                continue
            db.insert_image_description(
                message_id=message_id, peer_id=self._chat_id,
                description=text, model_type=f"qwen3vl-4b/{model}",
            )
            saved += 1

        if errors:
            self.log_message.emit(
                f"⚠️ Не удалось описать: {len(errors)} шт.")
            for path, reason in list(errors.items())[:5]:
                logger.info("не описано %s: %s", path, reason)
        return saved


def needs_component(components_dir: str, registry_url: str) -> bool:
    """
    Установлен ли компонент. Интерфейс спрашивает это до запуска выгрузки.

    Спрашивать после парсинга было бы поздно: человек ушёл заваривать чай,
    вернулся — а его ждёт вопрос про скачивание трёх гигабайт.
    """
    comp = ComponentManager(components_dir, registry_url).get_installed(
        COMPONENT_NAME)
    return comp is None or not comp.is_runnable
