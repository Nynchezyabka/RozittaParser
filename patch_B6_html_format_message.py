#!/usr/bin/env python3
"""
Patch B6: HtmlGenerator._format_message() — missing `self` parameter.

PROBLEM:
  HtmlGenerator._format_message() signature has no `self`:
    def _format_message(row, stt_text, row_dict) -> str:  ← 3 params
  
  But callers use it as instance method:
    self._format_message(row, stt, row_dict)  ← passes 4 args (self + 3)
  
  Error: "HtmlGenerator._format_message() takes 3 positional arguments
          but 4 were given"
  
  Same pattern as C2 fix (_should_download missing self).

FIX:
  Add `self` to the signature:
    def _format_message(self, row, stt_text, row_dict) -> str:

AFFECTED:
  - features/export/generator.py: HtmlGenerator._format_message()
"""
import sys, os

FILE = os.path.join(os.path.dirname(__file__), "features", "export", "generator.py")


def _read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _write(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _check_exists(text, marker, description):
    if marker not in text:
        print(f"❌ Проверка не пройдена: {description}")
        print(f"   Ищем: {marker!r}")
        sys.exit(1)
    print(f"✅ Проверка: {description}")


def _check_absent(text, marker, description):
    if marker in text:
        print(f"❌ Проверка не пройдена: {description} (уже присутствует)")
        sys.exit(1)
    print(f"✅ Проверка: {description} (отсутствует — ок)")


def _apply_patch(text, old, new, description):
    if old not in text:
        snippet = old[:200].replace("\n", "\\n")
        print(f"❌ Патч [{description}]: блок не найден")
        print(f"   Ищем первые 200 символов: {snippet!r}")
        sys.exit(1)
    if text.count(old) > 1:
        print(f"❌ Патч [{description}]: блок найден {text.count(old)} раз (ожидался 1)")
        sys.exit(1)
    result = text.replace(old, new, 1)
    print(f"✅ Патч [{description}]: применён")
    return result


# ── Read ──────────────────────────────────────────────────────────
src = _read(FILE)

# ═══════════════════════════════════════════════════════════════════
# Pre-checks
# ═══════════════════════════════════════════════════════════════════

# Баг: HTML _format_message без self
_check_exists(
    src,
    "def _format_message(row, stt_text: Optional[str], row_dict: dict) -> str:",
    "bug: HTML _format_message без self существует",
)

# Правильный вариант ещё не применён
_check_absent(
    src,
    "def _format_message(self, row, stt_text: Optional[str], row_dict: dict) -> str:",
    "fix: HTML _format_message с self (ещё не применён)",
)

# Контекст: убедимся что это именно HtmlGenerator (после return [str(out_path)] из _write_html)
_check_exists(
    src,
    "        out_path.write_text(html, encoding=\"utf-8\")\n        return [str(out_path)]\n    def _format_message(row, stt_text:",
    "контекст: HtmlGenerator._format_message идёт сразу после _write_html return",
)

# ═══════════════════════════════════════════════════════════════════
# Patch: add self parameter
# ═══════════════════════════════════════════════════════════════════

OLD = """\
        out_path.write_text(html, encoding="utf-8")
        return [str(out_path)]
    def _format_message(row, stt_text: Optional[str], row_dict: dict) -> str:
        \"\"\"Форматирует одно сообщение в HTML-блок по структуре макета.\"\"\""""

NEW = """\
        out_path.write_text(html, encoding="utf-8")
        return [str(out_path)]

    def _format_message(self, row, stt_text: Optional[str], row_dict: dict) -> str:
        \"\"\"Форматирует одно сообщение в HTML-блок по структуре макета.\"\"\""""

src = _apply_patch(src, OLD, NEW, "B6: add self to HtmlGenerator._format_message")

# ═══════════════════════════════════════════════════════════════════
# Post-checks
# ═══════════════════════════════════════════════════════════════════

_check_exists(
    src,
    "def _format_message(self, row, stt_text: Optional[str], row_dict: dict) -> str:",
    "fix: HTML _format_message с self применён",
)

_check_absent(
    src,
    "def _format_message(row, stt_text: Optional[str], row_dict: dict) -> str:",
    "bug: старая сигнатура без self удалена",
)

# Проверим, что Markdown-версия не задета (у неё уже self)
_check_exists(
    src,
    "def _format_message(self, row, stt_text: Optional[str]) -> str:",
    "Markdown _format_message(self, ...) — не тронут",
)

# ── Write ─────────────────────────────────────────────────────────
_write(FILE, src)
print(f"\n📝 Файл {FILE} обновлён")
print("✅ Патч B6 (HTML _format_message) применён успешно")
