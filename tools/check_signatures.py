#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/check_signatures.py — проверка @staticmethod / self по AST.

Заменяет таблицу BUG-20 в CLAUDE.md. Таблица дублировала в тексте то, что
живёт в коде, и протухла: к августу 2026 два вердикта из четырёх были
перевёрнуты (DocxGenerator._add_message_to_doc значился как «0 обращений
к self», хотя их 3; JsonGenerator._make_record — как «5 обращений», хотя 0).
Скрипт считает заново при каждом запуске и протухнуть не может.

Ищет методы, объявленные с `self`, без @staticmethod/@classmethod и ни
разу не обращающиеся к `self` в теле. Дальше делит их на два уровня:

  СЛОМАНО   — метод где-то вызывают через класс: `ParserService._method(x)`.
              Такой вызов падает с TypeError: первый аргумент уходит в
              `self`. Именно так жил BUG-20: прод звал через `self.`, а
              тесты через класс, и падали только тесты.

  КАНДИДАТ  — вызовов через класс нет, ничего не падает. Чисто
              стилистическая мелочь: можно навесить @staticmethod, а можно
              не трогать. Показывается только с флагом --all, чтобы
              разница между «сломано» и «можно причесать» не размывалась.

Использование:
    python tools/check_signatures.py           # только реальные поломки
    python tools/check_signatures.py --all     # плюс кандидаты
    python tools/check_signatures.py --all features/

Код возврата: 0 — поломок нет, 1 — есть (годится для CI).
"""

from __future__ import annotations

import ast
import io
import re
import sys
from pathlib import Path

SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules",
             "build", "dist"}

# Вендоренные файлы: чужой код, правится обновлением, а не нами.
SKIP_FILES = {"socks.py", "sockshandler.py"}

EXEMPT_DECORATORS = {"staticmethod", "classmethod", "property",
                     "abstractmethod", "cached_property"}


def _decorator_names(fn) -> set:
    names = set()
    for d in fn.decorator_list:
        node = d.func if isinstance(d, ast.Call) else d
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
    return names


def _uses_self(fn) -> bool:
    return any(
        isinstance(n, ast.Name) and n.id == "self"
        for n in ast.walk(fn)
    )


def collect_candidates(files: list) -> list:
    """[(путь, класс, метод, строка)] — self в сигнатуре, но не в теле."""
    out = []
    for path in files:
        try:
            tree = ast.parse(io.open(path, encoding="utf-8").read())
        except (SyntaxError, UnicodeDecodeError) as exc:
            print(f"⚠️  {path}: не разобрать ({exc})", file=sys.stderr)
            continue
        for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
            for fn in cls.body:
                if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                args = [a.arg for a in fn.args.args]
                if not args or args[0] != "self":
                    continue
                if _decorator_names(fn) & EXEMPT_DECORATORS:
                    continue
                if _uses_self(fn):
                    continue
                out.append((path, cls.name, fn.name, fn.lineno))
    return out


def find_class_calls(files: list, cls_name: str, fn_name: str) -> list:
    """Где метод зовут через класс: `ClassName._method(`. → [(путь, строка)]"""
    pattern = re.compile(rf"\b{re.escape(cls_name)}\.{re.escape(fn_name)}\s*\(")
    hits = []
    for path in files:
        try:
            for i, line in enumerate(io.open(path, encoding="utf-8"), 1):
                if pattern.search(line):
                    hits.append((path, i))
        except UnicodeDecodeError:
            continue
    return hits


def main(argv: list) -> int:
    args = [a for a in argv[1:] if not a.startswith("--")]
    show_all = "--all" in argv

    root = Path(args[0]) if args else Path(".")
    if not root.exists():
        print(f"❌ {root} не найден")
        return 1

    scan_files = sorted(
        p for p in root.rglob("*.py")
        if not any(part in SKIP_DIRS for part in p.parts)
        and p.name not in SKIP_FILES
        and "tests" not in p.parts
    )
    # Вызовы ищем шире — включая тесты: именно там зовут через класс.
    all_files = sorted(
        p for p in Path(".").rglob("*.py")
        if not any(part in SKIP_DIRS for part in p.parts)
        and p.name not in SKIP_FILES
    )

    broken, candidates = [], []
    for path, cls_name, fn_name, lineno in collect_candidates(scan_files):
        hits = find_class_calls(all_files, cls_name, fn_name)
        (broken if hits else candidates).append(
            (path, cls_name, fn_name, lineno, hits)
        )

    if broken:
        print("СЛОМАНО — вызывается через класс, падает с TypeError:\n")
        for path, cls_name, fn_name, lineno, hits in broken:
            print(f"  {path}:{lineno}")
            print(f"    {cls_name}.{fn_name} — `self` в сигнатуре, "
                  "но в теле не используется")
            print("    → нужен @staticmethod, `self` из параметров убрать")
            shown = hits[:3]
            for hp, hl in shown:
                print(f"      зовут через класс: {hp}:{hl}")
            if len(hits) > len(shown):
                print(f"      … и ещё {len(hits) - len(shown)}")
            print()

    if show_all and candidates:
        print("КАНДИДАТЫ — ничего не падает, чисто стилистически:\n")
        for path, cls_name, fn_name, lineno, _ in candidates:
            print(f"  {path}:{lineno}  {cls_name}.{fn_name}")
        print()

    if broken:
        print(f"❌ сломано: {len(broken)}"
              + (f", кандидатов: {len(candidates)}" if candidates else ""))
        print("   Вызовы через self._method(...) продолжат работать "
              "после правки — менять их не нужно.")
        return 1

    print(f"✅ чисто: проверено файлов {len(scan_files)}, "
          "сломанных сигнатур нет")
    if candidates and not show_all:
        print(f"   ({len(candidates)} стилистических кандидатов — "
              "показать: --all)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
