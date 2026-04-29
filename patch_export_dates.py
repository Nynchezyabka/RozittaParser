"""
patch_export_dates.py
=====================
FILE: ui/main_window.py

Исправляет баг: экспорт игнорировал выбранный диапазон дат.

Root cause
──────────
В _run_export() создавался ExportParams без date_from / date_to.
Всё остальное было реализовано корректно:
  - ExportParams уже содержал оба поля
  - ExportWorker передавал их в генераторы
  - Генераторы передавали в get_messages()
  - get_messages() применял WHERE date >= ? AND date <= ?
Недоставало только одного звена — передачи значений из SettingsPanel.get_params()
в ExportParams.

Изменение
─────────
Добавляет два аргумента в ExportParams(…):
    date_from = params.date_from if params else None,
    date_to   = params.date_to   if params else None,

Запуск из корня проекта:
    python patch_export_dates.py
"""
import ast, sys
from pathlib import Path

TARGET = Path("ui/main_window.py")
if not TARGET.exists():
    print(f"ABORT: {TARGET} не найден. Запустите из корня проекта.")
    sys.exit(1)

src = TARGET.read_text(encoding="utf-8")
original = src

OLD = (
    "        export_params = ExportParams(\n"
    "            chat_id=chat.get(\"id\"),\n"
    "            chat_title=chat_title,\n"
    "            split_mode=split_mode,\n"
    "            topic_id=chat.get(\"selected_topic_id\"),\n"
    "            include_comments=params.include_comments if params else False,\n"
    "            output_dir=chat_dir,\n"
    "            db_path=db_path,\n"
    "            period_label=getattr(collect_result, \"period_label\", \"fullchat\"),\n"
    "            export_formats=self._settings_screen.get_export_formats(),\n"
    "            ai_split=self._settings_screen.get_ai_split(),\n"
    "            ai_split_chunk_words=self._settings_screen.get_ai_split_chunk_words() if hasattr(self._settings_screen, 'get_ai_split_chunk_words') else 300_000,\n"
    "        )\n"
)

NEW = (
    "        export_params = ExportParams(\n"
    "            chat_id=chat.get(\"id\"),\n"
    "            chat_title=chat_title,\n"
    "            split_mode=split_mode,\n"
    "            topic_id=chat.get(\"selected_topic_id\"),\n"
    "            include_comments=params.include_comments if params else False,\n"
    "            output_dir=chat_dir,\n"
    "            db_path=db_path,\n"
    "            period_label=getattr(collect_result, \"period_label\", \"fullchat\"),\n"
    "            export_formats=self._settings_screen.get_export_formats(),\n"
    "            ai_split=self._settings_screen.get_ai_split(),\n"
    "            ai_split_chunk_words=self._settings_screen.get_ai_split_chunk_words() if hasattr(self._settings_screen, 'get_ai_split_chunk_words') else 300_000,\n"
    "            date_from=params.date_from if params else None,\n"
    "            date_to=params.date_to   if params else None,\n"
    "        )\n"
)

if OLD not in src:
    print("ABORT: anchor block not found — файл изменился или патч уже применён.")
    sys.exit(1)

src = src.replace(OLD, NEW, 1)

try:
    ast.parse(src)
except SyntaxError as e:
    print(f"ABORT: SyntaxError после патча: {e}")
    sys.exit(1)

TARGET.write_text(src, encoding="utf-8")
print("✅ Патч применён: ui/main_window.py")
print("   Добавлено: date_from и date_to в ExportParams внутри _run_export()")
