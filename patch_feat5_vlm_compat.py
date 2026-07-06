#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
patch_feat5_vlm_compat.py — FEAT-5: фикс совместимости Florence-2 + transformers.

Запуск из корня проекта:  python patch_feat5_vlm_compat.py

Проблема:
  microsoft/Florence-2-base использует remote-код (trust_remote_code=True),
  который в __init__ обращается к self.forced_bos_token_id. В transformers>=5.0
  этот атрибут убран из PretrainedConfig (переехал в GenerationConfig) →
  AttributeError при from_pretrained → воркер падает на каждом кандидате.

Решение (путь A — даунгрейд):
  Закрепить transformers==4.41.2 — последняя стабильная версия, где
  PretrainedConfig.forced_bos_token_id ещё существует как атрибут.
  faster-whisper от этого НЕ страдает: он не импортирует transformers
  в рантайме (только extras для CLI-конверсии HF→CT2).

Дополнительно:
  Добавляем sentencepiece — он нужен MarianTokenizer'у (Helsinki-NLP/opus-mt-en-ru)
  в core/vlm/translator.py / manager.py, но отсутствует в requirements.txt
  и в install() менеджера. На 4.41.2 без него переводчик упадёт с ImportError.

Что делает патч (3 правки, идемпотентен):
  1. requirements.txt        — новый блок VLM-зависимостей с pin 4.41.2
  2. core/vlm/manager.py     — pin в _PIP_COMMAND / _REQUIRED_SPECS / install()
  3. CLAUDE.md               — новое правило #21 (Florence-2 + transformers pin)

Сам core/vlm/manager.py (логика from_pretrained) НЕ трогается — там всё корректно.
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
# ШАГ 1. requirements.txt — VLM-блок
# ══════════════════════════════════════════════════════════════════════════

REQ_OLD = """\
# ── Распознавание речи STT (опционально, тяжёлая зависимость ~500 МБ) ─────────
# Раскомментируйте для расшифровки голосовых и кружочков:
faster-whisper
"""

REQ_NEW = """\
# ── Распознавание речи STT (опционально, тяжёлая зависимость ~500 МБ) ─────────
# Раскомментируйте для расшифровки голосовых и кружочков:
faster-whisper

# ── Распознавание изображений VLM (опционально, тяжёлая зависимость ~2 ГБ) ────
# Раскомментируйте для описания фото (FEAT-5, Florence-2 + перевод en→ru):
# ⚠️ transformers>=5.x ломает remote-код microsoft/Florence-2-base
#    (атрибут forced_bos_token_id убран из PretrainedConfig в 5.x) — pin 4.41.2.
# ⚠️ sentencepiece нужен MarianTokenizer'у (Helsinki-NLP/opus-mt-en-ru).
transformers==4.41.2
torch
pillow
einops
timm
sentencepiece
"""


# ══════════════════════════════════════════════════════════════════════════
# ШАГ 2. core/vlm/manager.py — pin в _PIP_COMMAND / _REQUIRED_SPECS
# ══════════════════════════════════════════════════════════════════════════

# 2a. Константы модуля
MGR_CONST_OLD = """\
# Пакеты, необходимые для работы Florence-2 (trust_remote_code)
_REQUIRED_SPECS = ("transformers", "torch", "PIL", "einops", "timm")

_PIP_COMMAND = "pip install transformers torch pillow einops timm"
"""

MGR_CONST_NEW = """\
# Пакеты, необходимые для работы Florence-2 (trust_remote_code)
# ⚠️ transformers>=5.x ломает remote-код microsoft/Florence-2-base
#    (forced_bos_token_id убран из PretrainedConfig в 5.x) — pin 4.41.2.
# ⚠️ sentencepiece нужен MarianTokenizer'у (Helsinki-NLP/opus-mt-en-ru).
_REQUIRED_SPECS = ("transformers", "torch", "PIL", "einops", "timm", "sentencepiece")

_PIP_COMMAND = "pip install 'transformers==4.41.2' torch pillow einops timm sentencepiece"
"""

# 2b. install() — список пакетов в subprocess.run
MGR_INSTALL_OLD = """\
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
"""

MGR_INSTALL_NEW = """\
        log("📦 Устанавливаю transformers==4.41.2 + torch + pillow + einops + "
            "timm + sentencepiece...")
        log("⏳ torch — тяжёлый пакет, это может занять 5-15 минут...")
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install",
                 "transformers==4.41.2", "torch", "pillow", "einops", "timm",
                 "sentencepiece", "--quiet"],
                capture_output=True,
                text=True,
                timeout=1800,
            )
"""


# ══════════════════════════════════════════════════════════════════════════
# ШАГ 3. CLAUDE.md — новое правило #21
# ══════════════════════════════════════════════════════════════════════════

CLAUDE_OLD = """\
**Греп-проверка перед коммитом:**

```bash
# Найти все методы без self в signature (потенциальные баги):
grep -n "^    def [^_]" features/parser/api.py features/export/generator.py
# Проверить что у каждого либо есть self, либо есть @staticmethod строкой выше
```

---

## 🔄 Основные потоки выполнения
"""

CLAUDE_NEW = """\
**Греп-проверка перед коммитом:**

```bash
# Найти все методы без self в signature (потенциальные баги):
grep -n "^    def [^_]" features/parser/api.py features/export/generator.py
# Проверить что у каждого либо есть self, либо есть @staticmethod строкой выше
```

### 21. Florence-2 + transformers — pin 4.41.2 (FEAT-5)

`microsoft/Florence-2-base` использует remote-код (`trust_remote_code=True`),
который в `Florence2LanguageConfig.__init__` обращается к
`self.forced_bos_token_id`. В `transformers>=5.0` этот атрибут убран из
`PretrainedConfig` (переехал в `GenerationConfig`) → `AttributeError` при
`from_pretrained` → воркер падает на каждом кандидате, описания не появляются.

**Требование:** в окружении с VLM должен стоять `transformers==4.41.2`.
Не обновлять `transformers` выше 4.41.2 без явного регрессионного теста
Florence-2 (`diag_vlm.py` — должна пройти «Попытка A» без workaround'а).

**Безопасность пина для других компонентов:**
- `faster-whisper` не использует `transformers` в рантайме (только опционально
  для CLI-конверсии HF→CT2 через `extra="conversion"`) — пин не ломает STT.
- `telethon`, `PySide6`, `python-docx`, `cryptg`, `pyaes` — не зависят от
  `transformers` вообще.
- `ctranslate2` (используется faster-whisper) — тоже не зависит.

**Дополнительно:** для `MarianTokenizer` (`Helsinki-NLP/opus-mt-en-ru`,
переводчик en→ru в `core/vlm/manager.py`) требуется `sentencepiece` —
он есть в `requirements.txt` и в `VLMManager.install()`.

---

## 🔄 Основные потоки выполнения
"""


# ══════════════════════════════════════════════════════════════════════════
# main
# ══════════════════════════════════════════════════════════════════════════

def main() -> int:
    print("=" * 70)
    print("patch_feat5_vlm_compat.py — FEAT-5: фикс совместимости Florence-2")
    print("=" * 70)

    print("\n[1/3] requirements.txt — VLM-блок с pin transformers==4.41.2")
    patch("requirements.txt", REQ_OLD, REQ_NEW, "REQ: VLM-блок")

    print("\n[2/3] core/vlm/manager.py — pin в константах и install()")
    patch("core/vlm/manager.py", MGR_CONST_OLD, MGR_CONST_NEW,
          "MGR: _PIP_COMMAND / _REQUIRED_SPECS")
    patch("core/vlm/manager.py", MGR_INSTALL_OLD, MGR_INSTALL_NEW,
          "MGR: install() список пакетов")

    print("\n[3/3] CLAUDE.md — новое правило #21 (Florence-2 + transformers pin)")
    patch("CLAUDE.md", CLAUDE_OLD, CLAUDE_NEW, "CLAUDE: правило #21")

    print("\n" + "=" * 70)
    if FAILED:
        print(f"⚠️ Применено: {len(APPLIED)}, ПРОПУЩЕНО: {len(FAILED)}")
        for t in FAILED:
            print(f"   ❌ {t}")
        print("\nПришли Claude вывод скрипта + фрагменты файлов для ручной правки.")
        return 1

    print(f"✅ Все правки применены ({len(APPLIED)}). Дальше:")
    print("   1. pip install 'transformers==4.41.2' torch pillow einops timm sentencepiece")
    print("   2. pip check   (должно быть 'No broken requirements')")
    print("   3. python -m py_compile core/vlm/manager.py")
    print("   4. python diag_vlm.py                    (Попытка A должна пройти БЕЗ workaround)")
    print("   5. python diag_vlm.py <путь\\к\\фото.jpg>  (тестовое описание)")
    print("   6. Smoke-тест по правилу #18:")
    print("      - чат с 2-3 фото → чип «🖼 Описание фото» → парсинг")
    print("      - экспорт во все 4 формата → проверить [Описание: ...] под каждым фото")
    print("      - повторный запуск → лог VLM должен показать «нет новых изображений» (кэш)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
