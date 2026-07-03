#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
diag_vlm.py — диагностика загрузки Florence-2 (FEAT-5).

Запуск из корня проекта (в venv):
    python diag_vlm.py                      — только проверка загрузки модели
    python diag_vlm.py path\\to\\photo.jpg   — загрузка + описание картинки

Скрипт НЕ трогает файлы проекта. Печатает:
  1. Версии transformers / torch / timm / einops
  2. Попытка A: обычная загрузка (как сейчас в manager.py)
  3. Попытка B: загрузка с workaround'ом flash_attn (канонический фикс для CPU)
  4. Если передан путь к картинке и загрузка удалась — тестовое описание

Пришли Claude ПОЛНЫЙ вывод.
"""

from __future__ import annotations

import sys
import traceback

MODEL_ID = "microsoft/Florence-2-base"


def print_versions() -> None:
    print("=" * 70)
    print("ВЕРСИИ")
    print("=" * 70)
    print(f"python       : {sys.version.split()[0]}")
    for pkg in ("transformers", "torch", "timm", "einops", "PIL"):
        try:
            mod = __import__(pkg)
            ver = getattr(mod, "__version__", "?")
            print(f"{pkg:<13}: {ver}")
        except ImportError as exc:
            print(f"{pkg:<13}: НЕ УСТАНОВЛЕН ({exc})")


def try_load(use_workaround: bool):
    """Пытается загрузить Florence-2. Возвращает (model, processor) или None."""
    import torch
    from transformers import AutoModelForCausalLM, AutoProcessor

    def _load():
        model = AutoModelForCausalLM.from_pretrained(
            MODEL_ID, trust_remote_code=True, torch_dtype=torch.float32,
        )
        model.eval()
        processor = AutoProcessor.from_pretrained(MODEL_ID, trust_remote_code=True)
        return model, processor

    if not use_workaround:
        return _load()

    # Канонический workaround для CPU: remote-код Florence-2 требует
    # flash_attn — вырезаем его из списка импортов динамического модуля.
    from unittest.mock import patch
    from transformers.dynamic_module_utils import get_imports

    def fixed_get_imports(filename):
        imports = get_imports(filename)
        if "flash_attn" in imports:
            imports.remove("flash_attn")
        return imports

    with patch("transformers.dynamic_module_utils.get_imports", fixed_get_imports):
        return _load()


def try_describe(model, processor, image_path: str) -> None:
    import torch
    from PIL import Image

    print(f"\nОписываю {image_path} ...")
    image = Image.open(image_path).convert("RGB")
    task = "<DETAILED_CAPTION>"
    inputs = processor(text=task, images=image, return_tensors="pt")
    with torch.no_grad():
        ids = model.generate(
            input_ids=inputs["input_ids"],
            pixel_values=inputs["pixel_values"],
            max_new_tokens=192,
            num_beams=3,
            do_sample=False,
        )
    raw = processor.batch_decode(ids, skip_special_tokens=False)[0]
    parsed = processor.post_process_generation(
        raw, task=task, image_size=(image.width, image.height)
    )
    print(f"✅ ОПИСАНИЕ: {parsed.get(task)}")


def main() -> int:
    print_versions()
    image_path = sys.argv[1] if len(sys.argv) > 1 else None
    loaded = None

    print("\n" + "=" * 70)
    print("ПОПЫТКА A: обычная загрузка (текущий код manager.py)")
    print("=" * 70)
    try:
        loaded = try_load(use_workaround=False)
        print("✅ Попытка A: модель загрузилась БЕЗ workaround'а")
    except Exception:
        print("❌ Попытка A упала. Полный traceback:")
        traceback.print_exc()

    if loaded is None:
        print("\n" + "=" * 70)
        print("ПОПЫТКА B: загрузка с workaround'ом flash_attn")
        print("=" * 70)
        try:
            loaded = try_load(use_workaround=True)
            print("✅ Попытка B: модель загрузилась С workaround'ом "
                  "(значит, фикс — вырезать flash_attn в manager.py)")
        except Exception:
            print("❌ Попытка B тоже упала. Полный traceback:")
            traceback.print_exc()

    if loaded is not None and image_path:
        print("\n" + "=" * 70)
        print("ТЕСТ ОПИСАНИЯ")
        print("=" * 70)
        try:
            try_describe(*loaded, image_path)
        except Exception:
            print("❌ Генерация описания упала. Полный traceback:")
            traceback.print_exc()

    print("\nГотово. Пришли Claude ВЕСЬ вывод выше.")
    return 0


if __name__ == "__main__":
    sys.exit(main())