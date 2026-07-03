"""
core/vlm/worker.py — VLMWorker: QThread для пакетного описания изображений.

Запускается из MainWindow после завершения STT-этапа (или сразу после
парсинга, если STT выключен). Читает из БД все сообщения с изображениями
без описаний, прогоняет через VLMManager (Florence-2), сохраняет в БД
после КАЖДОГО файла (защита от потери данных при падении — как в STT).

Сигналы:
    log_message(str)              — строка лога для UI
    description_ready(int, str)   — (message_id, text) — готово описание
    progress(int)                 — 0..100
    error(str)                    — критическая ошибка
    finished()                    — все описания завершены

Qt-код разрешён в этом файле (аналогично core/stt/worker.py).
"""

from __future__ import annotations

import logging
import os

from PySide6.QtCore import QThread, Signal

from core.database import DBManager
from core.utils import is_image_path
from core.vlm.manager import VLMManager, VLMError

logger = logging.getLogger(__name__)


class VLMWorker(QThread):
    """
    Пакетное описание изображений чата.

    Usage:
        worker = VLMWorker(db_path, chat_id, translate=True)
        worker.log_message.connect(...)
        worker.progress.connect(progress_bar.setValue)
        worker.finished.connect(on_vlm_done)
        worker.start()
    """

    log_message = Signal(str)
    description_ready = Signal(int, str)   # message_id, text
    progress = Signal(int)
    error = Signal(str)
    finished = Signal()

    def __init__(
        self,
        db_path: str,
        chat_id: int,
        *,
        translate: bool = True,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._db_path = db_path
        self._chat_id = chat_id
        self._translate = translate

    # ------------------------------------------------------------------
    # QThread entry point
    # ------------------------------------------------------------------

    def run(self) -> None:
        try:
            self._describe_all()
        except VLMError as exc:
            logger.error("VLMWorker: VLMError — %s", exc)
            self.error.emit(str(exc))
        except Exception as exc:
            logger.exception("VLMWorker: неожиданная ошибка")
            self.error.emit(f"VLM: неожиданная ошибка — {exc}")
        finally:
            # force=False — модель остаётся в памяти (Singleton),
            # повторный запуск на следующем чате не будет ждать загрузки.
            try:
                VLMManager.instance().unload(force=False)
            except Exception as e:
                logging.exception("Exception while unloading VLMManager: %s", e)
            self.finished.emit()

    # ------------------------------------------------------------------
    # Основная логика
    # ------------------------------------------------------------------

    def _describe_all(self) -> None:
        # ── Проверка: зависимости установлены? ───────────────────────────
        if not VLMManager.is_available():
            self.log_message.emit(
                "⚠️ Библиотеки VLM (transformers/torch) не установлены."
            )
            self.log_message.emit(
                "💡 Для описания изображений выполните в терминале:"
            )
            self.log_message.emit(
                "   pip install transformers torch pillow einops timm"
            )
            self.log_message.emit("🔄 Пробую установить автоматически...")
            ok = VLMManager.install(log_callback=self.log_message.emit)
            if not ok:
                raise VLMError(
                    "Зависимости VLM не установлены и автоустановка не удалась. "
                    "Установите вручную: pip install transformers torch pillow einops timm"
                )
            # После pip install нужен перезапуск — importlib кэширует spec
            raise VLMError(
                "Зависимости VLM установлены. Пожалуйста, перезапустите приложение."
            )

        with DBManager(self._db_path) as db:
            rows = db.get_vlm_candidates(self._chat_id)

        # SQL отдаёт все сообщения с media_path — фильтруем изображения здесь
        candidates = [
            row for row in rows
            if row["media_path"]
            and is_image_path(row["media_path"])
            and os.path.exists(row["media_path"])
        ]

        if not candidates:
            self.log_message.emit("🖼 VLM: нет новых изображений для описания")
            self.progress.emit(100)
            return

        total = len(candidates)
        self.log_message.emit(
            f"🖼 VLM: найдено {total} изображений — запускаю распознавание"
        )
        self.progress.emit(5)
        self.log_message.emit(
            "🔄 VLM: загружаю Florence-2 (при первом запуске модель "
            "скачивается с HuggingFace, ~0.5 ГБ — один раз)..."
        )

        mgr = VLMManager.instance()
        done = 0
        errors = 0

        for row in candidates:
            msg_id: int = row["message_id"]
            media_path: str = row["media_path"]

            if self.isInterruptionRequested():
                self.log_message.emit("⏹ VLM: остановлено пользователем")
                break

            try:
                text = mgr.describe(media_path, translate=self._translate)
            except VLMError as exc:
                errors += 1
                self.log_message.emit(
                    f"⚠️ VLM: пропущен msg_id={msg_id}: {exc}"
                )
                done += 1
                self.progress.emit(5 + int(done / total * 90))
                continue

            if text:
                # Сохраняем после каждого файла — защита от потери данных
                with DBManager(self._db_path) as db:
                    db.insert_image_description(
                        message_id=msg_id,
                        peer_id=self._chat_id,
                        description=text,
                        model_type="florence2-base",
                    )
                self.description_ready.emit(msg_id, text)
                self.log_message.emit(
                    f"✅ VLM msg_id={msg_id}: «{text[:60]}{'…' if len(text) > 60 else ''}»"
                )
            else:
                self.log_message.emit(
                    f"🔇 VLM msg_id={msg_id}: пустое описание"
                )

            done += 1
            self.progress.emit(5 + int(done / total * 90))

        self.progress.emit(100)
        summary = f"🖼 VLM завершён: {done - errors}/{total} описано"
        if errors:
            summary += f", {errors} ошибок"
        self.log_message.emit(summary)
