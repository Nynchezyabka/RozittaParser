#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
patch_ref4_dead_thread_pairs.py — REF-4: мёртвый дубликат get_thread_pairs.

В core/database.py класс DBManager содержит ДВА определения get_thread_pairs.
Python молча использует последнее (собирает только исходящие ответы участника —
соответствует спеке FEAT-1 и решению 2026-07-06). Первое (двунаправленное:
+ входящие ответы участнику) — мёртвый код ~185 строк, источник будущей
путаницы. Патч удаляет ПЕРВОЕ определение.

Примечание: идея «входящего направления» отклонена осознанно; если
понадобится — реализовывать заново, не воскрешать (см. REF-4 в
PROJECT_ANALYSIS.md).

Файл: core/database.py. Поведение НЕ меняется (удаляется неиспользуемое).
Запуск из корня проекта:  python patch_ref4_dead_thread_pairs.py
Идемпотентен.
"""

import py_compile
import shutil
import sys
from pathlib import Path

TARGET = Path("core/database.py")
BACKUP_SUFFIX = ".bak_ref4"

MARKER = "    def get_thread_pairs("
# Токен, который есть ТОЛЬКО в мёртвой (первой) версии — защита от удаления живой
DEAD_TOKEN = "Исходящее направление"


def main() -> int:
    if not TARGET.exists():
        print(f"❌ Не найден {TARGET}. Запускайте из корня проекта.")
        return 1

    with open(TARGET, "r", encoding="utf-8", newline="") as f:
        raw = f.read()
    eol = "\r\n" if "\r\n" in raw else "\n"
    text = raw.replace("\r\n", "\n")

    count = text.count(MARKER)
    if count == 1:
        if DEAD_TOKEN in text:
            print("❌ Осталось одно определение, но оно содержит маркер мёртвой "
                  "версии — удалена не та копия?! Проверьте вручную. Файл не изменён.")
            return 1
        print("⏭️  Уже применён: get_thread_pairs определён один раз. Файл не изменён.")
        return 0
    if count != 2:
        print(f"❌ Найдено {count} определений get_thread_pairs (ожидалось 2). "
              "Файл отличается от ожидаемого, изменения НЕ записаны.")
        return 1

    first = text.find(MARKER)
    second = text.find(MARKER, first + 1)
    dead_block = text[first:second]

    # Защита: удаляем именно двунаправленную (мёртвую) версию
    if DEAD_TOKEN not in dead_block:
        print("❌ Первое определение НЕ похоже на мёртвую версию "
              f"(нет токена «{DEAD_TOKEN}»). Порядок методов отличается от "
              "ожидаемого — изменения НЕ записаны, нужен ручной разбор.")
        return 1
    if DEAD_TOKEN in text[second:]:
        print("❌ Маркер мёртвой версии найден и во втором определении — "
              "неоднозначно, изменения НЕ записаны.")
        return 1

    deleted_lines = dead_block.count("\n")
    text = text[:first] + text[second:]
    # Один пустой ряд между соседними методами (перед def его могло не быть)
    if not text[:first].endswith("\n\n"):
        text = text[:first] + "\n" + text[first:]

    print(f"✅ Удалено мёртвое первое определение get_thread_pairs "
          f"({deleted_lines} строк)")

    backup = TARGET.with_suffix(TARGET.suffix + BACKUP_SUFFIX)
    shutil.copy2(TARGET, backup)
    print(f"💾 Бэкап: {backup}")

    if eol != "\n":
        text = text.replace("\n", eol)
    with open(TARGET, "w", encoding="utf-8", newline="") as f:
        f.write(text)

    try:
        py_compile.compile(str(TARGET), doraise=True)
        print(f"✅ py_compile OK: {TARGET}")
    except py_compile.PyCompileError as exc:
        print(f"❌ py_compile FAILED: {exc}")
        print(f"↩️  Откат из бэкапа {backup}")
        shutil.copy2(backup, TARGET)
        return 1

    print("\n🎉 REF-4 закрыт. Быстрая проверка: экспорт с фильтром по участнику")
    print("   в режиме «Все ветки» — поведение должно быть ИДЕНТИЧНО прежнему.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
