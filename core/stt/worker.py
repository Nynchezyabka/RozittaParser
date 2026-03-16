"""
core/stt/worker.py — STTWorker: QThread для пакетной транскрипции

Запускается из MainWindow после завершения ParseWorker.
Читает из БД все голосовые/видео сообщения без транскрипций,
транскрибирует через WhisperManager, сохраняет результат в БД.

Сигналы:
    log_message(str)          — строка лога для UI
    transcription_ready(int, str) — (message_id, text) — готова транскрипция
    progress(int)             — 0..100
    error(str)                — критическая ошибка
    finished()                — все транскрипции завершены
"""

from __future__ import annotations

import logging
from typing import List, Optional

from PySide6.QtCore import QThread, Signal

from core.database import DBManager
from core.exceptions import STTError
from core.stt.whisper_manager import WhisperManager

logger = logging.getLogger(__name__)


class STTWorker(QThread):
    """
    Пакетная STT-транскрипция голосовых и видео-сообщений.

    Usage:
        worker = STTWorker(db_path, chat_id, model_size="base")
        worker.log_message.connect(...)
        worker.progress.connect(progress_bar.setValue)
        worker.finished.connect(on_stt_done)
        worker.start()
    """

    log_message = Signal(str)
    transcription_ready = Signal(int, str)   # message_id, text
    progress = Signal(int)
    error = Signal(str)
    finished = Signal()

    # Типы файлов, которые транскрибируем
    STT_FILE_TYPES = ["voice", "video_note"]

    def __init__(
        self,
        db_path: str,
        chat_id: int,
        *,
        model_size: str = "small",
        language: str = "ru",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._db_path = db_path
        self._chat_id = chat_id
        self._model_size = model_size
        self._language = language

    # ------------------------------------------------------------------
    # QThread entry point
    # ------------------------------------------------------------------

    def run(self) -> None:
        try:
            self._transcribe_all()
        except STTError as exc:
            logger.error("STTWorker: STTError — %s", exc)
            self.error.emit(str(exc))
        except Exception as exc:
            logger.exception("STTWorker: неожиданная ошибка")
            self.error.emit(f"STT: неожиданная ошибка — {exc}")
        finally:
            # force=False — модель остаётся в памяти (Singleton).
            # Повторный запуск STT на следующем чате не будет ждать загрузки.
            try:
                WhisperManager.instance().unload(force=False)
            except Exception:
                pass
            self.finished.emit()

    # ------------------------------------------------------------------
    # Основная логика
    # ------------------------------------------------------------------

    def _transcribe_all(self) -> None:
        # ── Проверка: faster-whisper установлен? ──────────────────────────
        if not WhisperManager.is_available():
            self.log_message.emit(
                "⚠️ faster-whisper не установлен. STT недоступно."
            )
            self.log_message.emit(
                "💡 Для включения распознавания речи выполните в терминале:"
            )
            self.log_message.emit(
                "   pip install faster-whisper"
            )
            self.log_message.emit(
                "🔄 Пробую установить автоматически..."
            )
            ok = WhisperManager.install(log_callback=self.log_message.emit)
            if not ok:
                raise STTError(
                    "faster-whisper не установлен и автоустановка не удалась. "
                    "Установите вручную: pip install faster-whisper"
                )
            self.log_message.emit("🔄 Перезапустите приложение чтобы активировать STT.")
            # После pip install нужен перезапуск — importlib кэширует spec
            raise STTError(
                "faster-whisper установлен. Пожалуйста, перезапустите приложение."
            )

        with DBManager(self._db_path) as db:
            candidates = db.get_stt_candidates(
                self._chat_id, file_types=self.STT_FILE_TYPES
            )

        if not candidates:
            self.log_message.emit("🎙 STT: нет голосовых сообщений для распознавания")
            self.progress.emit(100)
            return

        total = len(candidates)
        self.log_message.emit(
            f"🎙 STT: найдено {total} голосовых сообщений — запускаем распознавание"
        )
        self.progress.emit(5)

        # WhisperManager использует Lazy Initialization: модель загружается
        # при первом вызове transcribe(), а не при instance().
        # Загрузка занимает 10–30 сек на CPU — сообщаем пользователю заранее.
        self.log_message.emit(
            f"🔄 STT: загружаю модель «{self._model_size}» (cpu/int8), подождите..."
        )
        mgr = WhisperManager.instance()
        done = 0
        errors = 0

        for row in candidates:
            msg_id: int = row["message_id"]
            media_path: str = row["media_path"]
            file_type: str = row["file_type"]

            if self.isInterruptionRequested():
                self.log_message.emit("⏹ STT: остановлено пользователем")
                break

            try:
                text = mgr.transcribe(
                    media_path,
                    language=self._language,
                    model_size=self._model_size,
                )
            except STTError as exc:
                errors += 1
                self.log_message.emit(
                    f"⚠️ STT: пропущен msg_id={msg_id} ({file_type}): {exc}"
                )
                done += 1
                self.progress.emit(5 + int(done / total * 90))
                continue

            if text:
                with DBManager(self._db_path) as db:
                    db.insert_transcription(
                        message_id=msg_id,
                        peer_id=self._chat_id,
                        text=text,
                        model_type=self._model_size,
                    )
                self.transcription_ready.emit(msg_id, text)
                self.log_message.emit(
                    f"✅ STT msg_id={msg_id}: «{text[:60]}{'…' if len(text) > 60 else ''}»"
                )
            else:
                self.log_message.emit(f"🔇 STT msg_id={msg_id}: тишина / пустой текст")

            done += 1
            self.progress.emit(5 + int(done / total * 90))

        self.progress.emit(100)
        summary = f"🎙 STT завершён: {done - errors}/{total} распознано"
        if errors:
            summary += f", {errors} ошибок"
        self.log_message.emit(summary)
