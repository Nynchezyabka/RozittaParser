"""
core/stt/whisper_manager.py — Singleton-обёртка над faster-whisper

faster-whisper сам декодирует .ogg, .oga, .mp4 и большинство форматов
через встроенный ffmpeg — конвертировать в WAV не требуется.

Улучшения качества распознавания:
    - initial_prompt  — контекст, помогающий модели понять язык и расставить пунктуацию
    - vad_filter=True — VAD отсекает тишину → меньше мусора и галлюцинаций
    - condition_on_previous_text=False — предотвращает зацикливание между сегментами
    - no_speech_threshold=0.6 — стандартный порог; сегменты ниже него → тишина
    - Постобработка: нормализация пробелов + удаление повторяющихся фраз (галлюцинации)
    - Дефолтная модель: "small" (качество лучше base, скорость приемлема для CPU)

Нет Qt-импортов. Чистый Python.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from typing import Optional

from core.exceptions import STTError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Контекстные промпты — помогают Whisper правильно расставить пунктуацию
# и не путать язык при коротких высказываниях
# ---------------------------------------------------------------------------

_INITIAL_PROMPTS: dict[str, str] = {
    "ru": (
        "Это расшифровка голосового сообщения. "
        "Текст написан на русском языке с пунктуацией: запятые, точки, вопросительные знаки."
    ),
    "en": (
        "This is a voice message transcription in English, "
        "with proper punctuation: commas, periods, question marks."
    ),
}

# ---------------------------------------------------------------------------
# Скомпилированные регулярные выражения для постобработки
# ---------------------------------------------------------------------------

_RE_SPACES      = re.compile(r"\s+")
# Одно слово, повторённое 3 и более раз подряд: "спасибо спасибо спасибо"
_RE_WORD_REPEAT = re.compile(r"\b(\w+)(?:\s+\1){2,}\b", re.IGNORECASE)
# Короткая фраза (2–5 слов), повторённая 3 и более раз подряд
_RE_PHRASE_REPEAT = re.compile(
    r"(\b(?:\w+\s+){1,4}\w+)\s+(?:\1\s*){2,}",
    re.IGNORECASE,
)


class WhisperManager:
    """
    Singleton-менеджер faster-whisper.

    Загружает модель один раз и переиспользует между вызовами.

    Usage:
        mgr = WhisperManager.instance()
        text = mgr.transcribe("voice_001.ogg")
    """

    _instance: Optional["WhisperManager"] = None
    _lock = threading.Lock()

    # ---------------------------------------------------------------
    # Singleton
    # ---------------------------------------------------------------

    @classmethod
    def is_available(cls) -> bool:
        """
        Проверяет, установлен ли faster-whisper И может ли он быть импортирован.

        find_spec() возвращает не-None даже если сам пакет сломан (например,
        ctranslate2 отсутствует или несовместима версия). Поэтому делаем
        пробный import и логируем реальную причину, если он падает.
        """
        try:
            import faster_whisper  # noqa: F401  # pylint: disable=import-outside-toplevel
            return True
        except ImportError as exc:
            logger.warning(
                "WhisperManager.is_available: faster_whisper import failed — %s. "
                "Установлен пакет? pip show faster-whisper. "
                "Зависимость ctranslate2: pip show ctranslate2.",
                exc,
            )
            return False
        except Exception as exc:
            logger.warning(
                "WhisperManager.is_available: неожиданная ошибка импорта faster_whisper — %s",
                exc,
            )
            return False

    @classmethod
    def install(cls, log_callback=None) -> bool:
        """
        Устанавливает faster-whisper через pip в текущий Python.

        Args:
            log_callback: необязательный callable(str) для вывода прогресса.

        Returns:
            True если установка прошла успешно, False при ошибке.
        """
        import subprocess, sys

        log = log_callback or (lambda s: logger.info(s))
        # В .exe sys.executable указывает на сам .exe — запустит второй экземпляр
        if getattr(sys, "frozen", False):
            log("⚠️ Автоустановка недоступна в .exe — установите вручную:")
            log("   pip install faster-whisper")
            return False
        log("📦 Устанавливаю faster-whisper (ctranslate2 + зависимости)...")
        log("⏳ Это может занять 1–3 минуты, подождите...")

        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", "faster-whisper", "--quiet"],
                capture_output=True,
                text=True,
                timeout=300,
            )
            if result.returncode == 0:
                log("✅ faster-whisper успешно установлен")
                return True
            else:
                log(f"❌ Ошибка установки faster-whisper:\n{result.stderr[-500:]}")
                return False
        except subprocess.TimeoutExpired:
            log("❌ Установка превысила лимит времени (5 мин)")
            return False
        except Exception as exc:
            log(f"❌ Не удалось запустить pip: {exc}")
            return False


    @classmethod
    def instance(cls) -> "WhisperManager":
        """Возвращает единственный экземпляр менеджера."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def __init__(self) -> None:
        self._model = None
        self._model_size: Optional[str] = None
        self._model_lock = threading.Lock()

    # ---------------------------------------------------------------
    # Приватные методы
    # ---------------------------------------------------------------

    def _ensure_model(self, model_size: str = "small") -> None:
        """Загружает модель, если ещё не загружена или изменился размер."""
        if self._model is not None and self._model_size == model_size:
            return

        try:
            from faster_whisper import WhisperModel  # type: ignore
        except ImportError as exc:
            raise STTError(
                f"faster-whisper не может быть импортирован: {exc}. "
                "Проверьте: pip show faster-whisper  и  pip show ctranslate2. "
                "Если ctranslate2 отсутствует: pip install ctranslate2"
            ) from exc

        logger.info("WhisperManager: загрузка модели '%s' (cpu/int8)...", model_size)
        t = time.perf_counter()
        try:
            self._model = WhisperModel(
                model_size,
                device="cpu",
                compute_type="int8",
            )
            self._model_size = model_size
            logger.info(
                "✅ Whisper '%s' загружен за %.1fs",
                model_size, time.perf_counter() - t,
            )
        except Exception as exc:
            raise STTError(f"Не удалось загрузить модель Whisper '{model_size}': {exc}") from exc

    @staticmethod
    def _postprocess(text: str) -> str:
        """
        Постобработка распознанного текста:
          1. Нормализация пробелов (множественные → одинарный).
          2. Удаление повторяющихся одиночных слов (3+ раз подряд).
          3. Удаление повторяющихся коротких фраз (3+ раз подряд) — галлюцинации.
        """
        if not text:
            return text
        text = _RE_SPACES.sub(" ", text).strip()
        text = _RE_WORD_REPEAT.sub(r"\1", text)
        text = _RE_PHRASE_REPEAT.sub(r"\1", text)
        return _RE_SPACES.sub(" ", text).strip()

    # ---------------------------------------------------------------
    # Публичный API
    # ---------------------------------------------------------------

    def transcribe(
        self,
        file_path: str,
        *,
        language: str = "ru",
        beam_size: int = 5,
        model_size: str = "small",
    ) -> str:
        """
        Транскрибирует аудио/видео файл.

        faster-whisper принимает .ogg, .oga, .mp4 и большинство форматов напрямую.

        Args:
            file_path:  Путь к аудио/видео файлу.
            language:   Код языка ('ru', 'en', '' — автоопределение).
            beam_size:  Параметр beam search (5 — баланс качества и скорости).
            model_size: Размер модели ('tiny','base','small','medium','large-v3').
                        По умолчанию 'small' — оптимум для русского на CPU.

        Returns:
            Распознанный текст после постобработки (пустая строка если тишина).

        Raises:
            STTError: faster-whisper не установлен или произошла ошибка.
        """
        lang = language or None
        prompt = _INITIAL_PROMPTS.get(language, None) if language else None

        with self._model_lock:
            self._ensure_model(model_size)
            try:
                segments, info = self._model.transcribe(
                    file_path,
                    language=lang,
                    beam_size=beam_size,
                    initial_prompt=prompt,
                    # Предотвращает зацикливание: каждый сегмент обрабатывается независимо
                    condition_on_previous_text=False,
                    # VAD отсекает тишину → меньше мусора и «галлюцинаций»
                    vad_filter=True,
                    vad_parameters={"min_silence_duration_ms": 500},
                    # Сегменты с вероятностью речи ниже порога → пропускаются
                    no_speech_threshold=0.6,
                )
                raw_text = " ".join(seg.text.strip() for seg in segments).strip()
                text = self._postprocess(raw_text)
                logger.debug(
                    "WhisperManager: %s → %d симв. (lang=%s, prob=%.2f)",
                    file_path, len(text), info.language, info.language_probability,
                )
                return text
            except Exception as exc:
                raise STTError(
                    f"Ошибка транскрибации '{file_path}': {exc}",
                    media_path=file_path,
                ) from exc

    def unload(self, force: bool = False) -> None:
        """
        Выгружает модель из памяти (освобождает RAM/VRAM).

        По умолчанию — NO-OP: модель остаётся в памяти между чатами,
        чтобы не платить 40+ секунд за повторную загрузку.

        Args:
            force: True — принудительно освободить память.
                   Используй только при завершении приложения
                   или явной смене модели.
        """
        if not force:
            return
        with self._model_lock:
            self._model = None
            self._model_size = None
            logger.info("WhisperManager: модель выгружена (force=True)")