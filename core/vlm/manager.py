"""
core/vlm/manager.py — Singleton-обёртка над Florence-2 (+ перевод en→ru).

Архитектура повторяет core/stt/whisper_manager.py:
    - ленивая загрузка модели при первом describe()
    - is_available() / install() для опциональной зависимости
    - unload(force=False) — NO-OP, модель живёт между чатами

Важно про Florence-2:
    - Модель управляется task-токенами (<CAPTION>, <DETAILED_CAPTION>),
      свободные промпты НЕ поддерживаются.
    - Подписи генерируются ТОЛЬКО на английском, поэтому для русских
      описаний используется второй этап — MarianMT (Helsinki-NLP/opus-mt-en-ru).
      Если перевод недоступен/упал — сохраняем английскую подпись (graceful fallback).

Нет Qt-импортов. Чистый Python.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

from config import VLM_CAPTION_MODEL, VLM_TRANSLATE_MODEL

logger = logging.getLogger(__name__)

# Task-токен Florence-2: <CAPTION> — 1 предложение, <DETAILED_CAPTION> — 1-3.
_CAPTION_TASK = "<DETAILED_CAPTION>"

# Пакеты, необходимые для работы Florence-2 (trust_remote_code)
_REQUIRED_SPECS = ("transformers", "torch", "PIL", "einops", "timm")

_PIP_COMMAND = "pip install transformers torch pillow einops timm"


class VLMError(Exception):
    """Ошибка VLM-подсистемы (Florence-2 / перевод)."""


class VLMManager:
    """
    Singleton-менеджер Florence-2.

    Usage:
        mgr = VLMManager.instance()
        text = mgr.describe("photo_001.jpg", translate=True)
    """

    _instance: Optional["VLMManager"] = None
    _lock = threading.Lock()

    # ---------------------------------------------------------------
    # Доступность / установка (паттерн WhisperManager)
    # ---------------------------------------------------------------

    @classmethod
    def is_available(cls) -> bool:
        """Проверяет, установлены ли transformers/torch/PIL/einops/timm."""
        try:
            import importlib.util
            return all(
                importlib.util.find_spec(name) is not None
                for name in _REQUIRED_SPECS
            )
        except Exception:
            logger.exception("VLMManager: ошибка проверки зависимостей")
            return False

    @classmethod
    def install(cls, log_callback=None) -> bool:
        """
        Устанавливает зависимости VLM через pip в текущий Python.

        ВНИМАНИЕ: torch — тяжёлый пакет (сотни МБ), установка может
        занять 5-15 минут. В .exe автоустановка недоступна.
        """
        import subprocess, sys

        log = log_callback or (lambda s: logger.info(s))
        if getattr(sys, "frozen", False):
            log("⚠️ Автоустановка недоступна в .exe — установите вручную:")
            log(f"   {_PIP_COMMAND}")
            return False

        log("📦 Устанавливаю transformers + torch + pillow + einops + timm...")
        log("⏳ torch — тяжёлый пакет, это может занять 5-15 минут...")
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install",
                 "transformers", "torch", "pillow", "einops", "timm", "--quiet"],
                capture_output=True,
                text=True,
                timeout=1800,
            )
            if result.returncode == 0:
                log("✅ Зависимости VLM успешно установлены")
                return True
            log(f"❌ Ошибка установки:\n{result.stderr[-500:]}")
            return False
        except subprocess.TimeoutExpired:
            log("❌ Установка превысила лимит времени (30 мин)")
            return False
        except Exception as exc:
            log(f"❌ Не удалось запустить pip: {exc}")
            return False

    # ---------------------------------------------------------------
    # Singleton
    # ---------------------------------------------------------------

    @classmethod
    def instance(cls) -> "VLMManager":
        """Возвращает единственный экземпляр менеджера."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def __init__(self) -> None:
        self._model = None          # Florence-2
        self._processor = None
        self._mt_model = None       # MarianMT en→ru
        self._mt_tok = None
        self._model_lock = threading.Lock()

    # ---------------------------------------------------------------
    # Приватные методы
    # ---------------------------------------------------------------

    def _ensure_model(self) -> None:
        """Загружает Florence-2, если ещё не загружена."""
        if self._model is not None:
            return

        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoProcessor
        except ImportError as exc:
            raise VLMError(
                "Зависимости VLM не установлены. "
                f"Выполните: {_PIP_COMMAND}"
            ) from exc

        logger.info("VLMManager: загрузка Florence-2 '%s' (cpu)...", VLM_CAPTION_MODEL)
        t = time.perf_counter()
        try:
            self._model = AutoModelForCausalLM.from_pretrained(
                VLM_CAPTION_MODEL,
                trust_remote_code=True,
                torch_dtype=torch.float32,   # CPU
            )
            self._model.eval()
            self._processor = AutoProcessor.from_pretrained(
                VLM_CAPTION_MODEL,
                trust_remote_code=True,
            )
            logger.info(
                "✅ Florence-2 загружена за %.1fs", time.perf_counter() - t
            )
        except Exception as exc:
            self._model = None
            self._processor = None
            raise VLMError(
                f"Не удалось загрузить Florence-2 '{VLM_CAPTION_MODEL}': {exc}"
            ) from exc

    def _ensure_translator(self) -> None:
        """Загружает MarianMT en→ru, если ещё не загружена."""
        if self._mt_model is not None:
            return
        try:
            from transformers import MarianMTModel, MarianTokenizer
        except ImportError as exc:
            raise VLMError("transformers не установлен") from exc

        logger.info("VLMManager: загрузка переводчика '%s'...", VLM_TRANSLATE_MODEL)
        try:
            self._mt_tok = MarianTokenizer.from_pretrained(VLM_TRANSLATE_MODEL)
            self._mt_model = MarianMTModel.from_pretrained(VLM_TRANSLATE_MODEL)
            self._mt_model.eval()
        except Exception as exc:
            self._mt_tok = None
            self._mt_model = None
            raise VLMError(
                f"Не удалось загрузить модель перевода '{VLM_TRANSLATE_MODEL}': {exc}"
            ) from exc

    def _translate_en_ru(self, text: str) -> str:
        """Переводит английскую подпись на русский. Может бросить исключение."""
        import torch

        batch = self._mt_tok([text], return_tensors="pt",
                             truncation=True, max_length=512)
        with torch.no_grad():
            out = self._mt_model.generate(
                **batch, max_new_tokens=256, num_beams=4
            )
        return self._mt_tok.decode(out[0], skip_special_tokens=True).strip()

    # ---------------------------------------------------------------
    # Публичный API
    # ---------------------------------------------------------------

    def describe(self, image_path: str, *, translate: bool = True) -> str:
        """
        Генерирует краткое текстовое описание изображения.

        Args:
            image_path: Путь к файлу изображения (jpg/png/webp/...).
            translate:  Переводить ли описание en→ru (MarianMT).
                        При ошибке перевода возвращается английская подпись.

        Returns:
            Описание (1-3 предложения) или пустая строка.

        Raises:
            VLMError: зависимости не установлены или модель упала.
        """
        with self._model_lock:
            self._ensure_model()
            try:
                import torch
                from PIL import Image

                image = Image.open(image_path).convert("RGB")
                inputs = self._processor(
                    text=_CAPTION_TASK, images=image, return_tensors="pt"
                )
                with torch.no_grad():
                    generated_ids = self._model.generate(
                        input_ids=inputs["input_ids"],
                        pixel_values=inputs["pixel_values"],
                        max_new_tokens=192,
                        num_beams=3,
                        do_sample=False,
                    )
                raw = self._processor.batch_decode(
                    generated_ids, skip_special_tokens=False
                )[0]
                parsed = self._processor.post_process_generation(
                    raw, task=_CAPTION_TASK,
                    image_size=(image.width, image.height),
                )
                caption = (parsed.get(_CAPTION_TASK) or "").strip()
            except VLMError:
                raise
            except Exception as exc:
                raise VLMError(
                    f"Ошибка описания '{image_path}': {exc}"
                ) from exc

            if not caption:
                return ""

            if translate:
                try:
                    self._ensure_translator()
                    translated = self._translate_en_ru(caption)
                    if translated:
                        return translated
                except Exception as exc:
                    logger.warning(
                        "VLMManager: перевод не удался (%s) — "
                        "сохраняю английское описание", exc,
                    )
            return caption

    def unload(self, force: bool = False) -> None:
        """
        Выгружает модели из памяти.

        По умолчанию — NO-OP (паттерн WhisperManager): модели остаются
        в памяти между чатами, чтобы не платить за повторную загрузку.
        """
        if not force:
            return
        with self._model_lock:
            self._model = None
            self._processor = None
            self._mt_model = None
            self._mt_tok = None
            logger.info("VLMManager: модели выгружены (force=True)")
