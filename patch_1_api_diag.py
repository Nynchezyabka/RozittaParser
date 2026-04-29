"""
patch_1_api_diag.py
===================
Добавляет диагностические логи в features/parser/api.py.

PATCH A — после period_label="fullchat":
          [DIAG DATE] — значения date_from, date_to, days_limit, cutoff_date, upper_date
PATCH B — перед iter_messages:
          [DIAG ITER] — entity, topic_id, max_id, cutoff, upper, attempt
PATCH C — внутри цикла:
          [DIAG MSG]       — каждое 1-3 и каждое 50-е сообщение с датой и флагами фильтрации
          [DIAG SKIP upper] — первые 5 сообщений, отфильтрованных по upper_date

Именно эти строки помогут увидеть, где рвётся фильтр дат.

Запуск из корня проекта:
    python patch_1_api_diag.py
"""
import ast, sys
from pathlib import Path

TARGET = Path("features/parser/api.py")
if not TARGET.exists():
    print(f"ABORT: {TARGET} не найден. Запустите из корня проекта.")
    sys.exit(1)

src = TARGET.read_text(encoding="utf-8")
original = src
applied = 0

# ── PATCH A ──────────────────────────────────────────────────────────────────

OLD_A = (
    '        period_label = "fullchat"\n'
    '\n'
    '        depth_label = "за всё время" if cutoff_date is None '
    'else f"с {cutoff_date.strftime(\'%Y-%m-%d\')}"\n'
    '        self._log(f"📅 Глубина: {depth_label}")\n'
)

NEW_A = (
    '        period_label = "fullchat"\n'
    '\n'
    '        # ── Диагностика дат ──────────────────────────────────────────────\n'
    '        self._log(\n'
    '            f"[DIAG DATE] date_from={params.date_from!r} "\n'
    '            f"({type(params.date_from).__name__}), "\n'
    '            f"date_to={params.date_to!r} ({type(params.date_to).__name__}), "\n'
    '            f"days_limit={params.days_limit}"\n'
    '        )\n'
    '        self._log(\n'
    '            f"[DIAG DATE] cutoff_date={cutoff_date!r} "\n'
    '            f"({type(cutoff_date).__name__}), "\n'
    '            f"upper_date={upper_date!r} ({type(upper_date).__name__})"\n'
    '        )\n'
    '        logger.info(\n'
    '            "parser DATE diag: cutoff=%s upper=%s date_from=%r date_to=%r days=%s",\n'
    '            cutoff_date, upper_date, params.date_from, params.date_to, params.days_limit\n'
    '        )\n'
    '        # ─────────────────────────────────────────────────────────────────\n'
    '\n'
    '        depth_label = "за всё время" if cutoff_date is None '
    'else f"с {cutoff_date.strftime(\'%Y-%m-%d\')}"\n'
    '        self._log(f"📅 Глубина: {depth_label}")\n'
)

if OLD_A in src:
    src = src.replace(OLD_A, NEW_A, 1)
    print("OK: PATCH A applied")
    applied += 1
else:
    print("WARN: PATCH A — anchor not found, skipping")

# ── PATCH B ──────────────────────────────────────────────────────────────────

OLD_B = (
    '                _max_id_arg = last_message_id - 1 if last_message_id else 0\n'
    '                logger.debug(\n'
)

NEW_B = (
    '                _max_id_arg = last_message_id - 1 if last_message_id else 0\n'
    '                # ── Диагностика перед стартом итерации ───────────────────\n'
    '                self._log(\n'
    '                    f"[DIAG ITER] entity={getattr(entity, \'id\', entity)} "\n'
    '                    f"topic={topic_id} max_id={_max_id_arg} "\n'
    '                    f"cutoff={cutoff_date} upper={upper_date} attempt={attempts}"\n'
    '                )\n'
    '                # ─────────────────────────────────────────────────────────\n'
    '                logger.debug(\n'
)

if OLD_B in src:
    src = src.replace(OLD_B, NEW_B, 1)
    print("OK: PATCH B applied")
    applied += 1
else:
    print("WARN: PATCH B — anchor not found, skipping")

# ── PATCH C ──────────────────────────────────────────────────────────────────

OLD_C = (
    '                    msg_date = ensure_aware_utc(message.date) if message.date else None\n'
    '\n'
    '                    # Фильтр верхней даты (пропускаем слишком новые)\n'
    '                    if upper_date and msg_date and msg_date > upper_date:\n'
    '                        continue\n'
    '\n'
    '                    # Фильтр нижней даты (iter_messages идёт от новых к старым)\n'
    '                    if cutoff_date is not None and msg_date and msg_date < cutoff_date:\n'
)

NEW_C = (
    '                    msg_date = ensure_aware_utc(message.date) if message.date else None\n'
    '\n'
    '                    # ── Диагностика: каждые 50 сообщений + первые три ────\n'
    '                    if _iter_msg_count <= 3 or _iter_msg_count % 50 == 0:\n'
    '                        self._log(\n'
    '                            f"[DIAG MSG] #{_iter_msg_count} id={message.id} "\n'
    '                            f"date={msg_date} "\n'
    '                            f"upper_ok={upper_date is None or (msg_date is not None and msg_date <= upper_date)} "\n'
    '                            f"lower_ok={cutoff_date is None or (msg_date is not None and msg_date >= cutoff_date)}"\n'
    '                        )\n'
    '                    # ─────────────────────────────────────────────────────\n'
    '\n'
    '                    # Фильтр верхней даты (пропускаем слишком новые)\n'
    '                    if upper_date and msg_date and msg_date > upper_date:\n'
    '                        if _iter_msg_count <= 5:\n'
    '                            self._log(\n'
    '                                f"[DIAG SKIP upper] id={message.id} "\n'
    '                                f"msg_date={msg_date} > upper_date={upper_date}"\n'
    '                            )\n'
    '                        continue\n'
    '\n'
    '                    # Фильтр нижней даты (iter_messages идёт от новых к старым)\n'
    '                    if cutoff_date is not None and msg_date and msg_date < cutoff_date:\n'
)

if OLD_C in src:
    src = src.replace(OLD_C, NEW_C, 1)
    print("OK: PATCH C applied")
    applied += 1
else:
    print("WARN: PATCH C — anchor not found, skipping")

# ── Сохранение ────────────────────────────────────────────────────────────────

try:
    ast.parse(src)
    syntax_ok = True
except SyntaxError as e:
    syntax_ok = False
    print(f"\n❌ SyntaxError: {e}")

if src != original and syntax_ok:
    TARGET.write_text(src, encoding="utf-8")
    print(f"\n✅ Сохранено: {TARGET}  ({applied}/3 патчей применено)")
elif not syntax_ok:
    print("\n❌ Файл НЕ сохранён — синтаксическая ошибка!")
else:
    print(f"\n⚠️  Файл не изменён ({applied}/3)")
