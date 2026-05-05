#!/usr/bin/env python3
"""
patch_topic_name.py — добавляет topic_name в имена файлов экспорта.

До:    Rozitta_Parser_topic22_2026-04-05_to_2026-05-05_history.json
После: Rozitta_Parser_новости_2026-04-05_to_2026-05-05_history.json

Запускать из корня проекта:
    python patch_topic_name.py
"""

from __future__ import annotations

import py_compile
import shutil
import sys
import tempfile
from pathlib import Path

OK   = "\u2705"
FAIL = "\u274c"


class PatchError(Exception):
    pass


def _backup(path: Path) -> Path:
    bak = path.with_suffix(path.suffix + ".bak")
    shutil.copy2(path, bak)
    print(f"  \U0001f4be Резерв: {bak}")
    return bak


def _restore(path: Path, bak: Path) -> None:
    shutil.copy2(bak, path)
    print(f"  \u267b\ufe0f  Восстановлен: {path}")


def _check_syntax(path: Path) -> None:
    try:
        py_compile.compile(str(path), doraise=True)
    except py_compile.PyCompileError as exc:
        raise PatchError(f"Синтаксическая ошибка в {path}:\n  {exc}") from exc


def apply_patches(path: Path, patches: list) -> None:
    print(f"\n\U0001f4c2 {path}")
    bak = _backup(path)

    src = path.read_text(encoding="utf-8")
    failed = []

    for label, old, new in patches:
        if old not in src:
            print(f"  {FAIL} {label}: блок не найден")
            failed.append(label)
        else:
            src = src.replace(old, new, 1)
            print(f"  {OK} {label}")

    if failed:
        print(f"\n{FAIL} Не применено ({len(failed)}): {failed}")
        print(f"  Файл {path} не изменён (замены выполнялись только в памяти).")
        sys.exit(1)

    tmp = Path(tempfile.mktemp(
        dir=path.parent,
        prefix=path.stem + "_tmp_",
        suffix=path.suffix,
    ))
    try:
        tmp.write_text(src, encoding="utf-8")
        _check_syntax(tmp)
    except (PatchError, OSError) as exc:
        tmp.unlink(missing_ok=True)
        _restore(path, bak)
        print(f"\n{FAIL} {exc}")
        print(f"  Файл {path} восстановлен из резерва.")
        sys.exit(1)

    try:
        tmp.replace(path)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        _restore(path, bak)
        print(f"\n{FAIL} Не удалось заменить файл: {exc}")
        sys.exit(1)

    print(f"  {OK} Синтаксис проверен, файл записан.")


GEN = Path("features/export/generator.py")
UI  = Path("features/export/ui.py")

for p in (GEN, UI):
    if not p.exists():
        print(f"{FAIL} Файл не найден: {p}")
        sys.exit(1)


# ─────────────────────────────────────────────────────────────────────────────
# Патчи для generator.py (исправлены строки поиска)
# ─────────────────────────────────────────────────────────────────────────────

GEN_PATCHES = [

    (
        "_topic_suffix signature",
        'def _topic_suffix(topic_id: Optional[int]) -> str:\n'
        '    """Возвращает строку \'_topicN\' или \'\' если topic_id is None."""\n'
        '\n'
        '    return f"_topic{topic_id}" if topic_id is not None else ""',

        'def _topic_suffix(topic_id: Optional[int], topic_name: Optional[str] = None) -> str:\n'
        '    """Возвращает \'_<имя>\' (из topic_name), \'_topicN\' или \'\' если topic_id is None."""\n'
        '\n'
        '    if topic_id is None:\n'
        '        return ""\n'
        '    if topic_name:\n'
        '        return f"_{sanitize_filename(topic_name)}"\n'
        '    return f"_topic{topic_id}"',
    ),

    (
        "DocxGenerator.__init__ _topic_name",
        '        self._topic_id:     Optional[int] = None   # ← задача 1\n'
        '        # Транскрипции: {message_id: text} — загружаются в generate()',

        '        self._topic_id:     Optional[int] = None   # ← задача 1\n'
        '        self._topic_name:   Optional[str] = None\n'
        '        # Транскрипции: {message_id: text} — загружаются в generate()',
    ),

    (
        "DocxGenerator.generate() signature",
        '        topic_id:         Optional[int] = None,\n'
        '        user_id:          Optional[int] = None,\n'
        '        include_comments: bool          = False,\n'
        '        period_label:     str           = "fullchat",',

        '        topic_id:         Optional[int] = None,\n'
        '        topic_name:       Optional[str] = None,\n'
        '        user_id:          Optional[int] = None,\n'
        '        include_comments: bool          = False,\n'
        '        period_label:     str           = "fullchat",',
    ),

    (
        "DocxGenerator.generate() store _topic_name",
        '        self._topic_id     = topic_id   # ← задача 1: сохраняем для _build_path\n'
        '        os.makedirs(self._output_dir, exist_ok=True)',

        '        self._topic_id     = topic_id   # ← задача 1: сохраняем для _build_path\n'
        '        self._topic_name   = topic_name\n'
        '        os.makedirs(self._output_dir, exist_ok=True)',
    ),

    (
        "DocxGenerator._build_path",
        '        topic_sfx  = _topic_suffix(self._topic_id)',
        '        topic_sfx  = _topic_suffix(self._topic_id, self._topic_name)',
    ),

    (
        "JsonGenerator.generate() signature",
        '        topic_id:             Optional[int]  = None,      # ← задача 2\n'
        '        user_id:              Optional[int]  = None,\n'
        '        include_comments:     bool           = False,\n'
        '        ai_split:             bool           = False,\n'
        '        period_label:         str            = "fullchat", # ← задача 3',

        '        topic_id:             Optional[int]  = None,      # ← задача 2\n'
        '        topic_name:           Optional[str]  = None,\n'
        '        user_id:              Optional[int]  = None,\n'
        '        include_comments:     bool           = False,\n'
        '        ai_split:             bool           = False,\n'
        '        period_label:         str            = "fullchat", # ← задача 3',
    ),

    (
        "JsonGenerator _topic_suffix call (исправлено: учтён лишний {topic_id})",
        '        topic_sfx  = _topic_suffix(topic_id)           # ← задача 2\n'
        '        base_name  = f"{safe_title}{topic_id}{topic_sfx}_{period_label}_history"  # ← задача 3',

        '        topic_sfx  = _topic_suffix(topic_id, topic_name)  # ← задача 2\n'
        '        base_name  = f"{safe_title}{topic_sfx}_{period_label}_history"  # ← задача 3',
    ),

    (
        "MarkdownGenerator.generate() signature",
        '        topic_id:             Optional[int]  = None,      # ← задача 2\n'
        '        user_id:              Optional[int]  = None,\n'
        '        include_comments:     bool           = False,\n'
        '        ai_split:             bool           = False,\n'
        '        period_label:         str,',

        '        topic_id:             Optional[int]  = None,      # ← задача 2\n'
        '        topic_name:           Optional[str]  = None,\n'
        '        user_id:              Optional[int]  = None,\n'
        '        include_comments:     bool           = False,\n'
        '        ai_split:             bool           = False,\n'
        '        period_label:         str,',
    ),

    (
        "MarkdownGenerator _topic_suffix call",
        '        topic_sfx   = _topic_suffix(topic_id)           # ← задача 2\n'
        '        base_name   = f"{safe_title}{topic_sfx}_{period_label}_history"',

        '        topic_sfx   = _topic_suffix(topic_id, topic_name)  # ← задача 2\n'
        '        base_name   = f"{safe_title}{topic_sfx}_{period_label}_history"',
    ),

    (
        "HtmlGenerator.generate() signature",
        '        topic_id:             Optional[int]  = None,\n'
        '        user_id:              Optional[int]  = None,\n'
        '        include_comments:     bool           = False,\n'
        '        ai_split:             bool           = False,\n'
        '        period_label:         str            = "fullchat",\n'
        '        ai_split_chunk_words: int            = 300_000,',

        '        topic_id:             Optional[int]  = None,\n'
        '        topic_name:           Optional[str]  = None,\n'
        '        user_id:              Optional[int]  = None,\n'
        '        include_comments:     bool           = False,\n'
        '        ai_split:             bool           = False,\n'
        '        period_label:         str            = "fullchat",\n'
        '        ai_split_chunk_words: int            = 300_000,',
    ),

    (
        "HtmlGenerator _topic_suffix call",
        '        topic_sfx   = _topic_suffix(topic_id)\n'
        '        base_name   = f"{safe_title}{topic_sfx}_{period_label}_history"',

        '        topic_sfx   = _topic_suffix(topic_id, topic_name)\n'
        '        base_name   = f"{safe_title}{topic_sfx}_{period_label}_history"',
    ),
]


# ─────────────────────────────────────────────────────────────────────────────
# Патчи для ui.py (проверено, соответствуют вашему файлу)
# ─────────────────────────────────────────────────────────────────────────────

UI_PATCHES = [

    (
        "ExportParams.topic_name",
        '    topic_id:         Optional[int] = None\n'
        '    user_id:          Optional[int] = None',

        '    topic_id:         Optional[int] = None\n'
        '    topic_name:       Optional[str] = None   # человекочитаемое имя ветки\n'
        '    user_id:          Optional[int] = None',
    ),

    (
        "ExportWorker DOCX topic_name",
        '                        split_mode       = p.split_mode,\n'
        '                        topic_id         = p.topic_id,\n'
        '                        user_id          = p.user_id,',

        '                        split_mode       = p.split_mode,\n'
        '                        topic_id         = p.topic_id,\n'
        '                        topic_name       = p.topic_name,\n'
        '                        user_id          = p.user_id,',
    ),

    (
        "ExportWorker JSON topic_name",
        '                    json_paths = jgen.generate(\n'
        '                        chat_id          = p.chat_id,\n'
        '                        chat_title       = p.chat_title,\n'
        '                        topic_id         = p.topic_id,',

        '                    json_paths = jgen.generate(\n'
        '                        chat_id          = p.chat_id,\n'
        '                        chat_title       = p.chat_title,\n'
        '                        topic_id         = p.topic_id,\n'
        '                        topic_name       = p.topic_name,',
    ),

    (
        "ExportWorker MD topic_name",
        '                    md_paths = mdgen.generate(\n'
        '                        chat_id          = p.chat_id,\n'
        '                        chat_title       = p.chat_title,\n'
        '                        topic_id         = p.topic_id,',

        '                    md_paths = mdgen.generate(\n'
        '                        chat_id          = p.chat_id,\n'
        '                        chat_title       = p.chat_title,\n'
        '                        topic_id         = p.topic_id,\n'
        '                        topic_name       = p.topic_name,',
    ),

    (
        "ExportWorker HTML topic_name",
        '                    html_paths = hgen.generate(\n'
        '                        chat_id              = p.chat_id,\n'
        '                        chat_title           = p.chat_title,\n'
        '                        topic_id             = p.topic_id,',

        '                    html_paths = hgen.generate(\n'
        '                        chat_id              = p.chat_id,\n'
        '                        chat_title           = p.chat_title,\n'
        '                        topic_id             = p.topic_id,\n'
        '                        topic_name           = p.topic_name,',
    ),
]


# ─────────────────────────────────────────────────────────────────────────────
# Запуск
# ─────────────────────────────────────────────────────────────────────────────

apply_patches(GEN, GEN_PATCHES)
apply_patches(UI,  UI_PATCHES)

print(f"""
{OK} Патч применён: изменены 2 файла.

Что осталось сделать вручную (ui/main_window.py и features/chats/ui.py):
  - В _run_export() при создании ExportParams добавить:
        topic_name = self._settings_screen._current_chat.get("selected_topic_name")
  - В features/chats/ui.py при выборе топика сохранять:
        chat["selected_topic_name"] = topic.title
""")