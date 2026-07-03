#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
patch_feat5_vlm.py — FEAT-5: VLM (Florence-2) описания изображений.

Запуск из корня проекта:  python patch_feat5_vlm.py

Что делает:
  1. Создаёт core/vlm/ (__init__.py, manager.py, worker.py)
  2. core/database.py        — таблица image_descriptions + 3 метода
  3. config.py               — константы VLM + флаг vlm_translate
  4. ui/main_window.py       — чип «Описание фото» + этап VLM в цепочке STT→Export
  5. features/export/generator.py — описания в DOCX / JSON / MD / HTML

Скрипт идемпотентен: повторный запуск пропускает уже применённые правки.
Сохраняет исходные окончания строк (CRLF/LF).
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).parent
FAILED: list[str] = []
APPLIED: list[str] = []


# ──────────────────────────────────────────────────────────────────────────
# Инфраструктура патча
# ──────────────────────────────────────────────────────────────────────────

def _read(path: Path) -> tuple[str, bool]:
    raw = path.read_bytes().decode("utf-8")
    crlf = "\r\n" in raw
    return raw.replace("\r\n", "\n"), crlf


def _write(path: Path, text: str, crlf: bool) -> None:
    if crlf:
        text = text.replace("\n", "\r\n")
    path.write_bytes(text.encode("utf-8"))


def patch(rel_path: str, old: str, new: str, tag: str, count: int = 1) -> None:
    path = ROOT / rel_path
    if not path.exists():
        print(f"  ❌ {tag}: файл {rel_path} не найден")
        FAILED.append(tag)
        return
    text, crlf = _read(path)
    if new in text:
        print(f"  ⏭  {tag}: уже применён")
        return
    n = text.count(old)
    if n != count:
        print(f"  ❌ {tag}: найдено {n} вхождений OLD (ожидалось {count}) — "
              f"файл отличается от эталона, правка пропущена")
        FAILED.append(tag)
        return
    _write(path, text.replace(old, new), crlf)
    APPLIED.append(tag)
    print(f"  ✅ {tag}")


def create(rel_path: str, content: str, tag: str) -> None:
    path = ROOT / rel_path
    if path.exists():
        print(f"  ⏭  {tag}: {rel_path} уже существует, не перезаписываю")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content.encode("utf-8"))
    APPLIED.append(tag)
    print(f"  ✅ {tag}: создан {rel_path}")


# ══════════════════════════════════════════════════════════════════════════
# ШАГ 1. Новые файлы core/vlm/
# ══════════════════════════════════════════════════════════════════════════

VLM_INIT = '''"""core/vlm — распознавание изображений (FEAT-5, Florence-2)."""
'''

VLM_MANAGER = r'''"""
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
'''

VLM_WORKER = r'''"""
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
'''


# ══════════════════════════════════════════════════════════════════════════
# ШАГ 2. core/database.py
# ══════════════════════════════════════════════════════════════════════════

DB_SCHEMA_OLD = """CREATE TABLE IF NOT EXISTS cached_dialogs ("""

DB_SCHEMA_NEW = """CREATE TABLE IF NOT EXISTS image_descriptions (
    message_id  INTEGER NOT NULL,
    peer_id     INTEGER NOT NULL,
    description TEXT    NOT NULL,
    model_type  TEXT    NOT NULL DEFAULT 'florence2-base',
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (message_id, peer_id)
);

CREATE TABLE IF NOT EXISTS cached_dialogs ("""

DB_METHODS_OLD = """    def get_distinct_post_ids(
"""

DB_METHODS_NEW = '''    # ------------------------------------------------------------------
    # VLM: описания изображений (FEAT-5)
    # ------------------------------------------------------------------

    def insert_image_description(
            self,
            message_id: int,
            peer_id: int,
            description: str,
            model_type: str = "florence2-base",
    ) -> None:
        """
        Сохраняет описание изображения (VLM).

        Использует INSERT OR REPLACE — повторный вызов обновит текст.
        """
        sql = """
            INSERT OR REPLACE INTO image_descriptions
                (message_id, peer_id, description, model_type, created_at)
            VALUES
                (:message_id, :peer_id, :description, :model_type, datetime('now'))
        """
        for attempt in range(_MAX_RETRIES):
            try:
                with self._cursor() as cur:
                    cur.execute(sql, {
                        "message_id": message_id,
                        "peer_id": peer_id,
                        "description": description,
                        "model_type": model_type,
                    })
                return
            except sqlite3.OperationalError as exc:
                if "locked" in str(exc).lower() and attempt < _MAX_RETRIES - 1:
                    time.sleep(_RETRY_BASE_DELAY * (2 ** attempt))
                    continue
                raise

    def get_vlm_candidates(self, chat_id: int) -> List[sqlite3.Row]:
        """
        Возвращает сообщения чата с медиафайлами без описания изображения.

        Фильтрация по расширению (только изображения) выполняется на стороне
        вызывающего через core.utils.is_image_path — SQL отдаёт все сообщения
        с непустым media_path.

        Returns:
            Список sqlite3.Row (id, message_id, media_path, file_type).
        """
        sql = """
            SELECT m.id, m.message_id, m.media_path, m.file_type
            FROM messages m
            LEFT JOIN image_descriptions d
                ON d.message_id = m.message_id AND d.peer_id = m.chat_id
            WHERE m.chat_id = ?
              AND m.media_path IS NOT NULL
              AND d.message_id IS NULL
            ORDER BY m.date ASC
        """
        with self._cursor() as cur:
            cur.execute(sql, (chat_id,))
            return cur.fetchall()

    def get_image_descriptions_for_chat(self, chat_id: int) -> dict:
        """
        Возвращает словарь {message_id: description} всех описаний чата.

        Используется генераторами экспорта (DOCX/JSON/MD/HTML) для
        вставки описаний рядом с изображениями.
        """
        sql = """
            SELECT d.message_id, d.description
            FROM image_descriptions d
            JOIN messages m ON m.message_id = d.message_id AND m.chat_id = d.peer_id
            WHERE m.chat_id = ?
        """
        with self._cursor() as cur:
            cur.execute(sql, (chat_id,))
            return {row[0]: row[1] for row in cur.fetchall()}

    def get_distinct_post_ids(
'''


# ══════════════════════════════════════════════════════════════════════════
# ШАГ 3. config.py
# ══════════════════════════════════════════════════════════════════════════

CFG_CONST_OLD = """VALID_STT_MODELS: tuple[str, ...] = ("tiny", "base", "small", "medium", "large-v3")"""

CFG_CONST_NEW = """VALID_STT_MODELS: tuple[str, ...] = ("tiny", "base", "small", "medium", "large-v3")

# --- VLM (Florence-2, FEAT-5) ---
VLM_CAPTION_MODEL:   str = "microsoft/Florence-2-base"      # подписи (en)
VLM_TRANSLATE_MODEL: str = "Helsinki-NLP/opus-mt-en-ru"     # перевод en→ru"""

CFG_FIELD_OLD = """    stt_model:    str        = field(default=STT_MODEL_DEFAULT)
    stt_language: str        = field(default=STT_LANGUAGE_DEFAULT)"""

CFG_FIELD_NEW = """    stt_model:    str        = field(default=STT_MODEL_DEFAULT)
    stt_language: str        = field(default=STT_LANGUAGE_DEFAULT)
    vlm_translate: bool      = True    # FEAT-5: переводить описания картинок en→ru"""

CFG_LOAD_OLD = """            stt_model     = str(data.get("stt_model", STT_MODEL_DEFAULT)),
            stt_language  = str(data.get("stt_language", STT_LANGUAGE_DEFAULT)),"""

CFG_LOAD_NEW = """            stt_model     = str(data.get("stt_model", STT_MODEL_DEFAULT)),
            stt_language  = str(data.get("stt_language", STT_LANGUAGE_DEFAULT)),
            vlm_translate = bool(data.get("vlm_translate", True)),"""

CFG_SAVE_OLD = """        "stt_model":     cfg.stt_model,
        "stt_language":  cfg.stt_language,"""

CFG_SAVE_NEW = """        "stt_model":     cfg.stt_model,
        "stt_language":  cfg.stt_language,
        "vlm_translate": cfg.vlm_translate,"""


# ══════════════════════════════════════════════════════════════════════════
# ШАГ 4. ui/main_window.py
# ══════════════════════════════════════════════════════════════════════════

MW_CHIP_OLD = """        self._stt_voice = ChipButton("🎤", "Голосовые", "voice", True)
        self._stt_round = ChipButton("📹", "Кружочки", "video_note", True)

        chips_row.addWidget(self._stt_voice)
        chips_row.addWidget(self._stt_round)"""

MW_CHIP_NEW = """        self._stt_voice = ChipButton("🎤", "Голосовые", "voice", True)
        self._stt_round = ChipButton("📹", "Кружочки", "video_note", True)
        # FEAT-5: описания изображений (Florence-2), по умолчанию выключено
        self._vlm_chip  = ChipButton("🖼", "Описание фото", "vlm", False)

        chips_row.addWidget(self._stt_voice)
        chips_row.addWidget(self._stt_round)
        chips_row.addWidget(self._vlm_chip)"""

MW_CHAIN_OLD = """    def _on_stt_finished(self, collect_result) -> None:
        fmts = self._settings_screen.get_export_formats()
        label = " + ".join(f.upper() for f in fmts)
        self._set_status("busy", f"Генерация {label}...")
        self._rozetta.set_tip("Создаю документ...")
        self._run_export(collect_result)"""

MW_CHAIN_NEW = """    def _on_stt_finished(self, collect_result) -> None:
        # FEAT-5: этап VLM (описания изображений) между STT и экспортом
        vlm_chip = getattr(self._settings_screen, "_vlm_chip", None)
        if vlm_chip is not None and vlm_chip.isActive():
            self._set_status("busy", "Описание изображений...")
            self._rozetta.set_tip("Описываю изображения...")
            self._run_vlm(collect_result)
            return
        self._start_export_stage(collect_result)

    def _start_export_stage(self, collect_result) -> None:
        fmts = self._settings_screen.get_export_formats()
        label = " + ".join(f.upper() for f in fmts)
        self._set_status("busy", f"Генерация {label}...")
        self._rozetta.set_tip("Создаю документ...")
        self._run_export(collect_result)"""

MW_VLM_OLD = """                command = "pip install faster-whisper",
            )"""

MW_VLM_NEW = """                command = "pip install faster-whisper",
            )

    # ──────────────────────────────────────────────────────────────────────
    # VLM (FEAT-5): описания изображений
    # ──────────────────────────────────────────────────────────────────────

    def _run_vlm(self, collect_result) -> None:
        from core.vlm.worker import VLMWorker
        from core.utils import sanitize_filename
        from config import DB_FILENAME

        chat_id = getattr(collect_result, "chat_id", None)
        if chat_id is None:
            self._start_export_stage(collect_result)
            return

        db_path = getattr(collect_result, "db_path", "") or ""
        if not db_path:
            chat_title = getattr(collect_result, "chat_title", "") or ""
            chat_dir = os.path.join(str(self._cfg.output_dir), sanitize_filename(chat_title))
            db_path = os.path.join(chat_dir, DB_FILENAME)

        self._last_collect_result = collect_result
        self._update_progress(0)
        worker = VLMWorker(
            db_path=db_path,
            chat_id=chat_id,
            translate=getattr(self._cfg, "vlm_translate", True),
        )
        worker.log_message.connect(self._log.append_info, Qt.UniqueConnection)
        worker.progress.connect(self._update_progress, Qt.UniqueConnection)
        worker.error.connect(self._on_vlm_error, Qt.UniqueConnection)
        worker.finished.connect(self._on_vlm_finished_slot, Qt.UniqueConnection)
        self._start_worker(worker)

    def _on_vlm_finished_slot(self) -> None:
        \"\"\"Именованный слот для VLMWorker.finished (Qt.UniqueConnection требует не-лямбду).\"\"\"

        self._start_export_stage(self._last_collect_result)

    def _on_vlm_error(self, message: str) -> None:
        self._log.append_error(f"⚠️ VLM ошибка (экспорт продолжается): {message}")
        # Если проблема в отсутствии библиотек — показываем диалог с командой
        if "transformers" in message.lower() or "torch" in message.lower():
            self._auth_screen._show_install_dialog(
                title   = "Требуются библиотеки для VLM",
                text    = (
                    "Для описания изображений нужны библиотеки "
                    "<b>transformers</b>, <b>torch</b>, <b>pillow</b>, "
                    "<b>einops</b>, <b>timm</b>.<br><br>"
                    "Установите их командой и перезапустите приложение:"
                ),
                command = "pip install transformers torch pillow einops timm",
            )"""


# ══════════════════════════════════════════════════════════════════════════
# ШАГ 5. features/export/generator.py
# ══════════════════════════════════════════════════════════════════════════

# --- 5.1 DOCX: поле в __init__ ---------------------------------------------
GEN_DOCX_INIT_OLD = """        # Транскрипции: {message_id: text} — загружаются в generate()
        self._transcriptions: Dict[int, str] = {}"""

GEN_DOCX_INIT_NEW = """        # Транскрипции: {message_id: text} — загружаются в generate()
        self._transcriptions: Dict[int, str] = {}
        # Описания изображений (VLM, FEAT-5): {message_id: text}
        self._img_descriptions: Dict[int, str] = {}"""

# --- 5.2 DOCX: загрузка описаний в generate() ------------------------------
GEN_DOCX_LOAD_OLD = """        try:
            self._transcriptions = self._db.get_transcriptions_for_chat(chat_id)
            if self._transcriptions:
                self._log(f"🎙 STT: загружено {len(self._transcriptions)} транскрипций")
        except Exception:
            self._transcriptions = {}"""

GEN_DOCX_LOAD_NEW = """        try:
            self._transcriptions = self._db.get_transcriptions_for_chat(chat_id)
            if self._transcriptions:
                self._log(f"🎙 STT: загружено {len(self._transcriptions)} транскрипций")
        except Exception:
            self._transcriptions = {}

        # Описания изображений (VLM, FEAT-5)
        try:
            self._img_descriptions = self._db.get_image_descriptions_for_chat(chat_id)
            if self._img_descriptions:
                self._log(f"🖼 VLM: загружено {len(self._img_descriptions)} описаний изображений")
        except Exception:
            self._img_descriptions = {}"""

# --- 5.3 DOCX: подпись под картинкой (группа частей, part_id) --------------
GEN_DOCX_IMG_A_OLD = """                        img_run.add_picture(abs_path, width=Inches(_IMAGE_WIDTH_INCHES))
                        if is_comment:
                            img_p.paragraph_format.left_indent = Inches(_COMMENT_INDENT_INCHES)"""

GEN_DOCX_IMG_A_NEW = """                        img_run.add_picture(abs_path, width=Inches(_IMAGE_WIDTH_INCHES))
                        if is_comment:
                            img_p.paragraph_format.left_indent = Inches(_COMMENT_INDENT_INCHES)
                        img_desc = self._img_descriptions.get(part_id)
                        if img_desc:
                            desc_p   = doc.add_paragraph()
                            desc_run = desc_p.add_run(f"🖼 Описание: {img_desc}")
                            desc_run.italic          = True
                            desc_run.font.size       = Pt(10)
                            desc_run.font.color.rgb  = RGBColor(80, 80, 80)
                            if is_comment:
                                desc_p.paragraph_format.left_indent = Inches(_COMMENT_INDENT_INCHES)"""

# --- 5.4 DOCX: подпись под картинкой (одиночное сообщение, msg_id) ---------
GEN_DOCX_IMG_B_OLD = """                    img_run.add_picture(abs_path, width=Inches(_IMAGE_WIDTH_INCHES))
                    if is_comment:
                        img_p.paragraph_format.left_indent = Inches(_COMMENT_INDENT_INCHES)"""

GEN_DOCX_IMG_B_NEW = """                    img_run.add_picture(abs_path, width=Inches(_IMAGE_WIDTH_INCHES))
                    if is_comment:
                        img_p.paragraph_format.left_indent = Inches(_COMMENT_INDENT_INCHES)
                    img_desc = self._img_descriptions.get(msg_id)
                    if img_desc:
                        desc_p   = doc.add_paragraph()
                        desc_run = desc_p.add_run(f"🖼 Описание: {img_desc}")
                        desc_run.italic          = True
                        desc_run.font.size       = Pt(10)
                        desc_run.font.color.rgb  = RGBColor(80, 80, 80)
                        if is_comment:
                            desc_p.paragraph_format.left_indent = Inches(_COMMENT_INDENT_INCHES)"""

# --- 5.5 JSON: _make_record — новый опциональный параметр -------------------
GEN_JSON_REC_OLD = """    def _make_record(self, row, stt_text: Optional[str]) -> dict:
        return {
            "message_id": row[_COL_MESSAGE_ID],
            "date":       row[_COL_DATE] or None,
            "sender_id":  row[_COL_USER_ID],
            "username":   row[_COL_USERNAME] or None,
            "text":       row[_COL_TEXT] or None,
            "media_path": row[_COL_MEDIA_PATH] or None,
            "stt_text":   stt_text,
        }"""

GEN_JSON_REC_NEW = """    def _make_record(self, row, stt_text: Optional[str], img_text: Optional[str] = None) -> dict:
        return {
            "message_id": row[_COL_MESSAGE_ID],
            "date":       row[_COL_DATE] or None,
            "sender_id":  row[_COL_USER_ID],
            "username":   row[_COL_USERNAME] or None,
            "text":       row[_COL_TEXT] or None,
            "media_path": row[_COL_MEDIA_PATH] or None,
            "stt_text":   stt_text,
            "image_description": img_text,
        }"""

# --- 5.6 JSON: загрузка img_map в основном пути -----------------------------
GEN_JSON_MAP_OLD = """        stt_map:   dict[int, str] = self._db.get_transcriptions_for_chat(chat_id)"""

GEN_JSON_MAP_NEW = """        stt_map:   dict[int, str] = self._db.get_transcriptions_for_chat(chat_id)
        img_map:   dict[int, str] = self._db.get_image_descriptions_for_chat(chat_id)"""

# --- 5.7 Общий threads-блок (JSON/MD/HTML _generate_threads, 3 вхождения) ---
GEN_THREADS_MAP_OLD = """        stt_map: dict[int, str] = {}
        try:
            stt_map = self._db.get_transcriptions_for_chat(chat_id)
        except Exception:
            pass"""

GEN_THREADS_MAP_NEW = """        stt_map: dict[int, str] = {}
        img_map: dict[int, str] = {}
        try:
            stt_map = self._db.get_transcriptions_for_chat(chat_id)
        except Exception:
            pass
        try:
            img_map = self._db.get_image_descriptions_for_chat(chat_id)
        except Exception:
            pass"""

# --- 5.8 JSON/threads + основные пути: вызовы _make_record (3 вхождения) ----
GEN_MAKEREC_CALL_OLD = """self._make_record(row, stt_map.get(msg_id))"""
GEN_MAKEREC_CALL_NEW = """self._make_record(row, stt_map.get(msg_id), img_map.get(msg_id))"""

# --- 5.9 MD+HTML: загрузка img_map в основных путях (2 вхождения) -----------
GEN_MDHTML_MAP_OLD = """        stt_map:    dict[int, str] = self._db.get_transcriptions_for_chat(chat_id)"""

GEN_MDHTML_MAP_NEW = """        stt_map:    dict[int, str] = self._db.get_transcriptions_for_chat(chat_id)
        img_map:    dict[int, str] = self._db.get_image_descriptions_for_chat(chat_id)"""

# --- 5.10 MD: сигнатура _format_message -------------------------------------
GEN_MD_SIG_OLD = '''    def _format_message(self, row, stt_text: Optional[str]) -> str:
        """Форматирует одно сообщение в Markdown-блок."""'''

GEN_MD_SIG_NEW = '''    def _format_message(self, row, stt_text: Optional[str], img_text: Optional[str] = None) -> str:
        """Форматирует одно сообщение в Markdown-блок."""'''

# --- 5.11 MD: тело _format_message (raw-строки: \n остаётся литералом) ------
GEN_MD_BODY_OLD = r'''        if stt_text:
            lines.append(f"\n*(STT: {stt_text.strip()})*")
        lines.append("\n---\n")'''

GEN_MD_BODY_NEW = r'''        if stt_text:
            lines.append(f"\n*(STT: {stt_text.strip()})*")
        if img_text:
            lines.append(f"\n*[Изображение: {img_text.strip()}]*")
        lines.append("\n---\n")'''

# --- 5.12 MD: вызов в основном пути ------------------------------------------
GEN_MD_CALL1_OLD = """                lines.append(self._format_message(row, stt_map.get(row[_COL_MESSAGE_ID])))"""
GEN_MD_CALL1_NEW = """                lines.append(self._format_message(row, stt_map.get(row[_COL_MESSAGE_ID]), img_map.get(row[_COL_MESSAGE_ID])))"""

# --- 5.13 MD: вызов в пути с ai_split ----------------------------------------
GEN_MD_CALL2_OLD = """            stt     = stt_map.get(msg_id)
            block   = self._format_message(row, stt)"""

GEN_MD_CALL2_NEW = """            stt     = stt_map.get(msg_id)
            img     = img_map.get(msg_id)
            block   = self._format_message(row, stt, img)"""

# --- 5.14 MD: threads-путь (инлайн-рендер) -----------------------------------
GEN_MD_THREADS_OLD = """            stt = stt_map.get(msg_id)
            if stt:
                lines.append(f"{indent}*(STT: {stt.strip()})*")"""

GEN_MD_THREADS_NEW = """            stt = stt_map.get(msg_id)
            if stt:
                lines.append(f"{indent}*(STT: {stt.strip()})*")
            img = img_map.get(msg_id)
            if img:
                lines.append(f"{indent}*[Изображение: {img.strip()}]*")"""

# --- 5.15 HTML: сигнатура _format_message ------------------------------------
GEN_HTML_SIG_OLD = """    def _format_message(self, row, stt_text: Optional[str], row_dict: dict) -> str:"""
GEN_HTML_SIG_NEW = """    def _format_message(self, row, stt_text: Optional[str], row_dict: dict, img_text: Optional[str] = None) -> str:"""

# --- 5.16 HTML: рендер описания (в слот stt_block, шаблон не меняем) ---------
GEN_HTML_BLOCK_OLD = r'''        # STT — курсив с левой полосой
        stt_block = ""
        if stt_text:
            stt_block = (
                f'<div class="msg-stt">🎙 {html_lib.escape(stt_text.strip())}</div>\n      '
            )'''

GEN_HTML_BLOCK_NEW = r'''        # STT — курсив с левой полосой
        stt_block = ""
        if stt_text:
            stt_block = (
                f'<div class="msg-stt">🎙 {html_lib.escape(stt_text.strip())}</div>\n      '
            )
        # Описание изображения (VLM, FEAT-5) — рендерим в том же слоте шаблона
        if img_text:
            stt_block += (
                f'<div class="msg-imgdesc">🖼 {html_lib.escape(img_text.strip())}</div>\n      '
            )'''

# --- 5.17 HTML: вызовы _format_message ---------------------------------------
GEN_HTML_CALL1_OLD = """                blocks.append(self._format_message(row, stt_map.get(row[_COL_MESSAGE_ID]), row_dict))"""
GEN_HTML_CALL1_NEW = """                blocks.append(self._format_message(row, stt_map.get(row[_COL_MESSAGE_ID]), row_dict, img_map.get(row[_COL_MESSAGE_ID])))"""

GEN_HTML_CALL2_OLD = """            stt    = stt_map.get(msg_id)
            block  = self._format_message(row, stt, row_dict)"""

GEN_HTML_CALL2_NEW = """            stt    = stt_map.get(msg_id)
            img    = img_map.get(msg_id)
            block  = self._format_message(row, stt, row_dict, img)"""

# --- 5.18 HTML: threads-путь --------------------------------------------------
GEN_HTML_THREADS_OLD = """            stt_block = ""
            stt = stt_map.get(msg_id)
            if stt:
                stt_block = (
                    f'<div class="msg-stt">🎙 {html_lib.escape(stt.strip())}</div>'
                )"""

GEN_HTML_THREADS_NEW = """            stt_block = ""
            stt = stt_map.get(msg_id)
            if stt:
                stt_block = (
                    f'<div class="msg-stt">🎙 {html_lib.escape(stt.strip())}</div>'
                )
            img = img_map.get(msg_id)
            if img:
                stt_block += (
                    f'<div class="msg-imgdesc">🖼 {html_lib.escape(img.strip())}</div>'
                )"""

# --- 5.19 HTML: CSS для .msg-imgdesc ------------------------------------------
GEN_HTML_CSS_OLD = """  .msg-stt {{ margin-top: 6px; font-size: 0.82rem; color: #90a0b0; font-style: italic; padding-left: 4px; border-left: 2px solid #3a4a5a; }}"""

GEN_HTML_CSS_NEW = """  .msg-stt {{ margin-top: 6px; font-size: 0.82rem; color: #90a0b0; font-style: italic; padding-left: 4px; border-left: 2px solid #3a4a5a; }}
  .msg-imgdesc {{ margin-top: 6px; font-size: 0.82rem; color: #a0b090; font-style: italic; padding-left: 4px; border-left: 2px solid #4a5a3a; }}"""


# ══════════════════════════════════════════════════════════════════════════
# Применение
# ══════════════════════════════════════════════════════════════════════════

def main() -> int:
    print("=" * 70)
    print("FEAT-5: VLM (Florence-2) — применение патча")
    print("=" * 70)

    print("\n[1/5] Новые файлы core/vlm/")
    create("core/vlm/__init__.py", VLM_INIT, "vlm/__init__.py")
    create("core/vlm/manager.py", VLM_MANAGER, "vlm/manager.py")
    create("core/vlm/worker.py", VLM_WORKER, "vlm/worker.py")

    print("\n[2/5] core/database.py")
    patch("core/database.py", DB_SCHEMA_OLD, DB_SCHEMA_NEW, "DB: таблица image_descriptions")
    patch("core/database.py", DB_METHODS_OLD, DB_METHODS_NEW, "DB: 3 VLM-метода")

    print("\n[3/5] config.py")
    patch("config.py", CFG_CONST_OLD, CFG_CONST_NEW, "CFG: константы моделей")
    patch("config.py", CFG_FIELD_OLD, CFG_FIELD_NEW, "CFG: поле vlm_translate")
    patch("config.py", CFG_LOAD_OLD, CFG_LOAD_NEW, "CFG: load_config")
    patch("config.py", CFG_SAVE_OLD, CFG_SAVE_NEW, "CFG: save_config")

    print("\n[4/5] ui/main_window.py")
    patch("ui/main_window.py", MW_CHIP_OLD, MW_CHIP_NEW, "MW: чип «Описание фото»")
    patch("ui/main_window.py", MW_CHAIN_OLD, MW_CHAIN_NEW, "MW: этап VLM в цепочке")
    patch("ui/main_window.py", MW_VLM_OLD, MW_VLM_NEW, "MW: _run_vlm / слоты")

    print("\n[5/5] features/export/generator.py")
    g = "features/export/generator.py"
    patch(g, GEN_DOCX_INIT_OLD,    GEN_DOCX_INIT_NEW,    "DOCX: поле __init__")
    patch(g, GEN_DOCX_LOAD_OLD,    GEN_DOCX_LOAD_NEW,    "DOCX: загрузка описаний")
    patch(g, GEN_DOCX_IMG_A_OLD,   GEN_DOCX_IMG_A_NEW,   "DOCX: подпись (grouped)")
    patch(g, GEN_DOCX_IMG_B_OLD,   GEN_DOCX_IMG_B_NEW,   "DOCX: подпись (single)")
    patch(g, GEN_JSON_REC_OLD,     GEN_JSON_REC_NEW,     "JSON: _make_record")
    patch(g, GEN_JSON_MAP_OLD,     GEN_JSON_MAP_NEW,     "JSON: img_map (main)")
    patch(g, GEN_THREADS_MAP_OLD,  GEN_THREADS_MAP_NEW,  "JSON/MD/HTML: img_map (threads ×3)", count=3)
    patch(g, GEN_MAKEREC_CALL_OLD, GEN_MAKEREC_CALL_NEW, "JSON: вызовы _make_record ×3", count=3)
    patch(g, GEN_MDHTML_MAP_OLD,   GEN_MDHTML_MAP_NEW,   "MD+HTML: img_map (main ×2)", count=2)
    patch(g, GEN_MD_SIG_OLD,       GEN_MD_SIG_NEW,       "MD: сигнатура _format_message")
    patch(g, GEN_MD_BODY_OLD,      GEN_MD_BODY_NEW,      "MD: тело _format_message")
    patch(g, GEN_MD_CALL1_OLD,     GEN_MD_CALL1_NEW,     "MD: вызов (main)")
    patch(g, GEN_MD_CALL2_OLD,     GEN_MD_CALL2_NEW,     "MD: вызов (ai_split)")
    patch(g, GEN_MD_THREADS_OLD,   GEN_MD_THREADS_NEW,   "MD: threads-рендер")
    patch(g, GEN_HTML_SIG_OLD,     GEN_HTML_SIG_NEW,     "HTML: сигнатура _format_message")
    patch(g, GEN_HTML_BLOCK_OLD,   GEN_HTML_BLOCK_NEW,   "HTML: рендер описания")
    patch(g, GEN_HTML_CALL1_OLD,   GEN_HTML_CALL1_NEW,   "HTML: вызов (main)")
    patch(g, GEN_HTML_CALL2_OLD,   GEN_HTML_CALL2_NEW,   "HTML: вызов (ai_split)")
    patch(g, GEN_HTML_THREADS_OLD, GEN_HTML_THREADS_NEW, "HTML: threads-рендер")
    patch(g, GEN_HTML_CSS_OLD,     GEN_HTML_CSS_NEW,     "HTML: CSS .msg-imgdesc")

    print("\n" + "=" * 70)
    if FAILED:
        print(f"⚠️ Применено: {len(APPLIED)}, ПРОПУЩЕНО из-за несовпадений: {len(FAILED)}")
        for t in FAILED:
            print(f"   ❌ {t}")
        print("Пришли Claude вывод скрипта + фрагменты файлов для ручной правки.")
        return 1
    print(f"✅ Все правки применены ({len(APPLIED)}). Дальше:")
    print("   1. python -m py_compile core/database.py config.py "
          "ui/main_window.py features/export/generator.py core/vlm/manager.py core/vlm/worker.py")
    print("   2. Smoke-тест (правило #18) + сценарий VLM: чат с 2-3 фото → "
          "чип «Описание фото» → парсинг → проверить описания во всех 4 форматах")
    return 0


if __name__ == "__main__":
    sys.exit(main())
