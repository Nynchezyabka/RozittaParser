#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
patch_feat5_vlm_flashattn.py — FEAT-5: canonical flash_attn workaround for Florence-2.

Запуск из корня проекта:  python patch_feat5_vlm_flashattn.py

Предварительное условие:
  patch_feat5_vlm_compat.py уже применён (transformers==4.41.2 + sentencepiece).

Проблема:
  После даунгрейда transformers до 4.41.2 загрузка Florence-2 проходит этап
  forced_bos_token_id, но падает на следующем шаге: remote-код
  modeling_florence2.py декларирует `import flash_attn`, а flash_attn —
  GPU-only (требует CUDA build, на CPU/Windows не ставится).
  transformers.dynamic_module_utils.check_imports() бросает ImportError
  до того, как модель начнёт загружаться.

  diag_vlm.py попытка B уже подтвердила, что workaround работает:
  модель загружается и генерирует описание.

Решение:
  Канонический workaround для Florence-2 на CPU: пропатчить
  transformers.dynamic_module_utils.get_imports так, чтобы он не возвращал
  'flash_attn' в списке нужных пакетов. Это позволяет remote-коду
  загрузиться. Сама модель flash_attn не использует при inference на
  float32 CPU — вырезание безопасно.

Что делает патч (2 правки, идемпотентен):
  1. core/vlm/manager.py — добавляет модульный хелпер _patch_flash_attn_imports()
     между _PIP_COMMAND и class VLMError.
  2. core/vlm/manager.py — оборачивает from_pretrained в _ensure_model()
     в `with _patch_flash_attn_imports():`.

Переводчик (MarianMT) НЕ требует workaround — Helsinki-NLP/opus-mt-en-ru
использует нативную реализацию transformers, без remote-кода.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).parent
FAILED: list[str] = []
APPLIED: list[str] = []


# ──────────────────────────────────────────────────────────────────────────
# Инфраструктура патча (повторяет patch_feat5_vlm.py — сохраняет CRLF/LF)
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


# ══════════════════════════════════════════════════════════════════════════
# ШАГ 1. core/vlm/manager.py — добавление хелпера _patch_flash_attn_imports()
# ══════════════════════════════════════════════════════════════════════════

# OLD: текущее состояние после patch_feat5_vlm_compat.py
# NEW: вставляем хелпер между _PIP_COMMAND и class VLMError
MGR_HELPER_OLD = """\
_PIP_COMMAND = "pip install 'transformers==4.41.2' torch pillow einops timm sentencepiece"


class VLMError(Exception):
    \"\"\"Ошибка VLM-подсистемы (Florence-2 / перевод).\"\"\"
"""

MGR_HELPER_NEW = """\
_PIP_COMMAND = "pip install 'transformers==4.41.2' torch pillow einops timm sentencepiece"


def _patch_flash_attn_imports():
    \"\"\"
    Контекстный менеджер: вырезает 'flash_attn' из списка импортов remote-кода.

    Florence-2 (microsoft/Florence-2-base) в modeling_florence2.py декларирует
    `import flash_attn`. flash_attn — GPU-only (требует CUDA build), на CPU/Windows
    не ставится. Без этого workaround transformers.dynamic_module_utils.check_imports()
    бросает ImportError ДО того, как модель начнёт загружаться.

    Сама модель flash_attn не использует при inference на CPU (мы на float32),
    поэтому вырезание безопасно.

    Канонический фикс — повторяет логику diag_vlm.py (попытка B).
    Применяется через `with _patch_flash_attn_imports():` вокруг from_pretrained.

    Возвращает: unittest.mock.patch context manager (или nullcontext, если
    transformers ещё не установлен — тогда _ensure_model() позже бросит
    VLMError с понятным сообщением).
    \"\"\"
    from unittest.mock import patch
    try:
        from transformers.dynamic_module_utils import get_imports
    except ImportError:
        # transformers не установлен — _ensure_model() бросит VLMError.
        from contextlib import nullcontext
        return nullcontext()

    def _fixed_get_imports(filename):
        imports = get_imports(filename)
        if "flash_attn" in imports:
            imports.remove("flash_attn")
        return imports

    return patch(
        "transformers.dynamic_module_utils.get_imports", _fixed_get_imports
    )


class VLMError(Exception):
    \"\"\"Ошибка VLM-подсистемы (Florence-2 / перевод).\"\"\"
"""


# ══════════════════════════════════════════════════════════════════════════
# ШАГ 2. core/vlm/manager.py — обернуть from_pretrained в with _patch...
# ══════════════════════════════════════════════════════════════════════════

MGR_LOAD_OLD = """\
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
"""

MGR_LOAD_NEW = """\
        try:
            # flash_attn — GPU-only, на CPU/Windows не ставится. Remote-код
            # Florence-2 декларирует его в импортах, без workaround from_pretrained
            # падает с ImportError. См. _patch_flash_attn_imports().
            with _patch_flash_attn_imports():
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
"""


# ══════════════════════════════════════════════════════════════════════════
# main
# ══════════════════════════════════════════════════════════════════════════

def main() -> int:
    print("=" * 70)
    print("patch_feat5_vlm_flashattn.py — FEAT-5: flash_attn workaround")
    print("=" * 70)
    print("Предварительное условие: patch_feat5_vlm_compat.py уже применён.")
    print()

    print("[1/2] core/vlm/manager.py — хелпер _patch_flash_attn_imports()")
    patch("core/vlm/manager.py", MGR_HELPER_OLD, MGR_HELPER_NEW,
          "MGR: хелпер _patch_flash_attn_imports")

    print("\n[2/2] core/vlm/manager.py — обернуть from_pretrained в with")
    patch("core/vlm/manager.py", MGR_LOAD_OLD, MGR_LOAD_NEW,
          "MGR: with _patch_flash_attn_imports() в _ensure_model")

    print("\n" + "=" * 70)
    if FAILED:
        print(f"⚠️ Применено: {len(APPLIED)}, ПРОПУЩЕНО: {len(FAILED)}")
        for t in FAILED:
            print(f"   ❌ {t}")
        print("\nВозможные причины:")
        print("  - patch_feat5_vlm_compat.py ещё не применён "
              "(нет пина 4.41.2 в _PIP_COMMAND)")
        print("  - Файл уже содержит правки от другой сессии")
        print("Пришли Claude вывод скрипта + фрагмент core/vlm/manager.py "
              "(строки 30-50 и 140-170).")
        return 1

    print(f"✅ Все правки применены ({len(APPLIED)}). Дальше:")
    print("   1. python -m py_compile core/vlm/manager.py")
    print("   2. python diag_vlm.py")
    print("      Теперь Попытка A должна пройти БЕЗ workaround'а "
          "(он встроен в manager.py, но diag_vlm.py тестирует отдельно).")
    print("   3. python diag_vlm.py <путь\\\\к\\\\фото.jpg>  — тестовое описание")
    print("   4. Smoke-тест по правилу #18:")
    print("      - чат с 2-3 фото → чип «🖼 Описание фото» → парсинг")
    print("      - экспорт во все 4 формата → [Описание: ...] под каждым фото")
    print("      - повторный запуск → лог VLM «нет новых изображений» (кэш)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
