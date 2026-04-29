"""
patch_2_date_fix.py
===================
Исправляет передачу дат из ui/main_window.py в CollectParams.

Корень проблемы
───────────────
В SettingsPanel.get_params() (или аналогичном методе) даты передаются как
объекты datetime.date, а CollectParams.date_from / date_to ожидает datetime.
Когда date_from/date_to содержат date, ensure_aware_utc() падает или возвращает
некорректное значение → весь диапазон сдвигается → msgs=0.

Дополнительно: при выборе пресета «N дней» date_to не должен передаваться
вообще (None), иначе он ограничивает выборку снизу.

Что делает скрипт
─────────────────
PATCH 1 — ищет паттерн «start_dt.date()» и «end_dt.date()» в методе,
          который передаёт даты в ParseParams/CollectParams,
          и заменяет на datetime.combine(...).

PATCH 2 — ищет место, где end_dt или date_to передаётся в ParseParams
          при режиме «N дней» (days_limit > 0), и обнуляет его до None.

PATCH 3 — добавляет однострочный диагностический print сразу после вызова
          get_date_range() (легко найти по тексту в логах, удалить потом).

Запуск из корня проекта:
    python patch_2_date_fix.py
"""
import re, sys, ast
from pathlib import Path

TARGET = Path("ui/main_window.py")
if not TARGET.exists():
    print(f"ABORT: {TARGET} не найден. Запустите из корня проекта.")
    sys.exit(1)

src = TARGET.read_text(encoding="utf-8")
original = src
applied = 0

# ── Убеждаемся, что datetime.time импортирован ──────────────────────────────
# В main_window.py скорее всего уже есть «from datetime import datetime»;
# нам нужна ещё «time» (для datetime.min.time()).
# Добавляем «time» в тот же import если его там нет.
if re.search(r'from datetime import[^\n]*\btime\b', src):
    print("INFO: 'time' уже импортирован из datetime")
else:
    # Заменяем «from datetime import datetime» → «from datetime import datetime, time»
    patched, n = re.subn(
        r'(from datetime import )(datetime\b)',
        r'\1datetime, time',
        src, count=1
    )
    if n:
        src = patched
        print("OK: добавили 'time' в 'from datetime import ...'")
    else:
        # Альтернативный вариант: «import datetime» — добавим alias
        print("WARN: не удалось добавить импорт 'time' автоматически — "
              "добавьте вручную: from datetime import time")

# ── PATCH 1: date() → datetime.combine() ────────────────────────────────────
# Ищем паттерны вида:
#   date_from = start_dt.date()
#   date_from = start_dt.date() if start_dt else None
# и аналогично для date_to / end_dt

# Вариант A: date_from = start_dt.date()
p1a_old = r'(date_from\s*=\s*)(\w+)\.date\(\)'
p1a_new = r'\1datetime.combine(\2, time.min) if \2 is not None else None'
patched, n = re.subn(p1a_old, p1a_new, src)
if n:
    src = patched
    print(f"OK: PATCH 1a: date_from = X.date() → datetime.combine (x{n})")
    applied += 1
else:
    # Вариант B: date_from = start_dt.date() if start_dt else None
    p1b_old = r'(date_from\s*=\s*)(\w+)\.date\(\)\s+if\s+\2\s+else\s+None'
    p1b_new = r'\1datetime.combine(\2, time.min) if \2 is not None else None'
    patched, n = re.subn(p1b_old, p1b_new, src)
    if n:
        src = patched
        print(f"OK: PATCH 1b (if/else form): date_from → datetime.combine (x{n})")
        applied += 1
    else:
        print("WARN: PATCH 1a/1b — start_dt.date() pattern not found")

p2a_old = r'(date_to\s*=\s*)(\w+)\.date\(\)'
p2a_new = r'\1datetime.combine(\2, time.max) if \2 is not None else None'
patched, n = re.subn(p2a_old, p2a_new, src)
if n:
    src = patched
    print(f"OK: PATCH 1c: date_to = X.date() → datetime.combine (x{n})")
else:
    p2b_old = r'(date_to\s*=\s*)(\w+)\.date\(\)\s+if\s+\2\s+else\s+None'
    p2b_new = r'\1datetime.combine(\2, time.max) if \2 is not None else None'
    patched, n = re.subn(p2b_old, p2b_new, src)
    if n:
        src = patched
        print(f"OK: PATCH 1d (if/else form): date_to → datetime.combine (x{n})")
    else:
        print("WARN: PATCH 1c/1d — end_dt.date() pattern not found")

# ── PATCH 2: при режиме «N дней» date_to должен быть None ───────────────────
# Стратегия: ищем CollectParams/ParseParams(... date_to=date_to ...)
# вместе с days_limit > 0, и добавляем условие.
#
# Самый надёжный способ — найти место формирования CollectParams и добавить
# гвард после вычисления date_to.
#
# Ищем конструкцию вида:
#   days_limit = N   или   days_limit = self._settings...
# и следующую за ней строку date_to = ...
# Если days_limit != 0 и date_to получен из виджета — обнуляем date_to.

GUARD_COMMENT = "# [DATE_FIX] date_to=None при режиме days_limit"
if GUARD_COMMENT not in src:
    # Ищем любое присваивание days_limit, за которым идёт date_to
    pattern_days = re.compile(
        r'([ \t]*)(days_limit\s*=\s*.+?\n)'
        r'((?:[ \t]+\w+\s*=\s*.+?\n)*?)'
        r'([ \t]*date_to\s*=\s*)(.+?)(\n)',
        re.MULTILINE,
    )
    def replace_days_guard(m):
        indent   = m.group(1)
        dl_line  = m.group(2)
        middle   = m.group(3)
        dt_pre   = m.group(4)
        dt_val   = m.group(5)
        newline  = m.group(6)
        guard = (
            f"{indent}{GUARD_COMMENT}\n"
            f"{indent}_days_nonzero = (days_limit or 0) != 0\n"
            f"{dt_pre}({dt_val} if not _days_nonzero else None){newline}"
        )
        return dl_line + middle + guard

    patched, n = pattern_days.subn(replace_days_guard, src, count=1)
    if n:
        src = patched
        print("OK: PATCH 2: добавлен guard date_to=None при days_limit>0")
        applied += 1
    else:
        print(
            "WARN: PATCH 2 — не удалось автоматически определить блок days_limit+date_to.\n"
            "     Добавьте вручную перед передачей date_to в CollectParams:\n"
            "         if days_limit:  date_to = None\n"
        )
else:
    print("INFO: PATCH 2 уже применён (guard comment найден)")
    applied += 1

# ── PATCH 3: однострочный диагностический print после get_date_range() ────────

DIAG_TAG = "# [DIAG] DateRangeWidget"
if DIAG_TAG not in src:
    old_p3 = re.compile(
        r'([ \t]*)(start_dt\s*,\s*end_dt\s*=\s*\S+\.get_date_range\(\))\n'
    )
    def add_diag(m):
        indent = m.group(1)
        line   = m.group(2)
        return (
            f"{indent}{line}\n"
            f"{indent}print(f\"{DIAG_TAG} → start={{start_dt!r}} ({{}}) "
            f"end={{end_dt!r}} ({{}})\".format(\n"
            f"{indent}    type(start_dt).__name__, type(end_dt).__name__))\n"
        )
    patched, n = old_p3.subn(add_diag, src, count=1)
    if n:
        src = patched
        print("OK: PATCH 3: добавлен диагностический print после get_date_range()")
        applied += 1
    else:
        print(
            "WARN: PATCH 3 — get_date_range() вызов не найден.\n"
            "     Добавьте вручную после вызова get_date_range():\n"
            '         print(f"[DIAG] start={start_dt!r} end={end_dt!r}")\n'
        )
else:
    print("INFO: PATCH 3 уже применён")
    applied += 1

# ── Сохранение ────────────────────────────────────────────────────────────────

try:
    ast.parse(src)
    syntax_ok = True
except SyntaxError as e:
    syntax_ok = False
    print(f"\n❌ SyntaxError: {e}")

if src != original and syntax_ok:
    TARGET.write_text(src, encoding="utf-8")
    print(f"\n✅ Сохранено: {TARGET}  ({applied}/3+ патчей применено)")
elif not syntax_ok:
    print("\n❌ Файл НЕ сохранён — синтаксическая ошибка!")
    print("   Примените изменения вручную по инструкции выше.")
else:
    print(f"\n⚠️  Файл не изменён. ({applied} проверок выполнено)")

print("""
════════════════════════════════════════
Как проверить после применения:
  1. Запустите парсер, выберите «8 дней»
  2. В логах ищите строки [DIAG DATE] и [DIAG] DateRangeWidget
  3. Убедитесь что:
       date_from = datetime (не date)
       date_to   = None    (при режиме «N дней»)
       cutoff_date = сегодня минус 8 дней, type=datetime
       upper_date  = None
════════════════════════════════════════
""")
