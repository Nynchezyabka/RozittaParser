#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_index.py — универсальный индексатор выгрузок Rozitta Parser.

НИЧЕГО НЕ ПЕРЕИМЕНОВЫВАЕТ. Файлы парсера остаются как есть; вся семантика
(выпуск, тема, цикл...) живёт в отдельной карте (CSV) и в генерируемом
индексе 00_Индекс.md.

Как файлы привязываются к постам (по номеру поста):
  * "..._post_{N}_comments_fullchat.md"  -> комментарии (текст поста + обсуждение)
  * "{N}_что_угодно.md"                   -> транскрипт видео поста N
  * "{N}_что_угодно.mp4|mp3|mkv|..."      -> медиа поста N

Режимы:
  1. Первый запуск по новому чату — создать заготовку карты:
       python make_index.py "D:\\...\\Имя Чата" --init-map карта.csv
     Скрипт найдёт все номера постов, попробует вытащить первую строку
     текста поста как черновое описание и запишет CSV. Вы заполняете/правите
     колонки (выпуск, цикл, тип, описание) в любом табличном редакторе.

  2. Построить индекс:
       python make_index.py "D:\\...\\Имя Чата" --map карта.csv
     Без --map индекс тоже строится — просто по номерам постов,
     с автоописаниями.

Формат карты (CSV, разделитель ";", кодировка UTF-8):
  пост;выпуск;тип;цикл;описание
  92;6;методика;Методика;Ключевые узлы большого алгоритма
  103;;инфо;;Запуск платформы makeeva.pro        <- пустой "выпуск" = инфо-пост
  91;5д;дополнение;Методика;Дополнение к выпуску 5
"""

import argparse
import csv
import re
import sys
import unicodedata
from pathlib import Path

RE_COMMENTS = re.compile(r"post_(\d+)_comments")
RE_LEADNUM  = re.compile(r"^(\d+)_")
RE_RENAMED  = re.compile(r"^(?:В\d+д?_п|И)(\d+)_")   # В06_п092_... / И103_...
MEDIA_EXT = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".mp3", ".m4a",
             ".ogg", ".oga", ".opus", ".wav", ".flac"}
INDEX_NAME = "00_Индекс.md"
# первая содержательная строка поста в comments-файле:
RE_POST_LINE = re.compile(r"^\*\*\[[\d\- :]+\][^\n]*?\[↗\]\([^\)]+\)\s*$")


# ---------------------------------------------------------------- карта ---

def load_map(path: Path) -> dict:
    """CSV -> {пост: {выпуск, тип, цикл, описание}}"""
    mapping = {}
    with open(path, encoding="utf-8-sig", newline="") as f:
        # поддержка и ";" и ","
        sample = f.read(2048); f.seek(0)
        delim = ";" if sample.count(";") >= sample.count(",") else ","
        for row in csv.DictReader(f, delimiter=delim):
            row = { (k or "").strip().lower(): (v or "").strip() for k, v in row.items() }
            if not row.get("пост"):
                continue
            try:
                post = int(row["пост"])
            except ValueError:
                continue
            mapping[post] = {
                "выпуск": row.get("выпуск", ""),
                "тип": row.get("тип", ""),
                "цикл": row.get("цикл", ""),
                "описание": row.get("описание", ""),
            }
    return mapping


def guess_description(comments_file: Path, max_len: int = 120) -> str:
    """Первая содержательная строка текста поста из comments-файла."""
    try:
        text = comments_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    lines = text.replace("\r\n", "\n").split("\n")
    seen_header = False
    for ln in lines:
        s = ln.strip()
        if not s:
            continue
        if RE_POST_LINE.match(s):
            seen_header = True
            continue
        if seen_header:
            s = re.sub(r"[*_#`\[\]]+", "", s).strip()   # снять markdown-разметку
            if s and s != "---":
                return (s[:max_len] + "…") if len(s) > max_len else s
    return ""


def init_map(path: Path, posts: dict, folder: Path):
    """Создать заготовку карты по найденным постам."""
    if path.exists():
        sys.exit(f"Файл карты уже существует, не перезаписываю: {path}")
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["пост", "выпуск", "тип", "цикл", "описание"])
        for post in sorted(posts):
            desc = ""
            com = posts[post].get("комментарии")
            if com:
                desc = guess_description(folder / com if not Path(com).is_absolute() else Path(com))
            w.writerow([post, "", "", "", desc])
    print(f"Заготовка карты записана: {path}")
    print("Заполните колонки «выпуск/тип/цикл», поправьте «описание» — и стройте индекс с --map.")


# ---------------------------------------------------------------- скан ---

def scan(root: Path, self_names: set) -> tuple[dict, list]:
    """-> ({пост: {роль: относительный_путь}}, [несопоставленные])"""
    posts: dict[int, dict[str, str]] = {}
    unknown = []
    for f in sorted(root.rglob("*")):
        if not f.is_file() or f.name in self_names:
            continue
        name = unicodedata.normalize("NFC", f.name)
        rel = f.relative_to(root).as_posix()
        m = RE_COMMENTS.search(name)
        if m:
            posts.setdefault(int(m.group(1)), {})["комментарии"] = rel
            continue
        m = RE_RENAMED.match(name) or RE_LEADNUM.match(name)
        if m:
            post = int(m.group(1))
            ext = f.suffix.lower()
            role = ("транскрипт" if ext == ".md"
                    else "медиа" if ext in MEDIA_EXT
                    else "прочее")
            slot = posts.setdefault(post, {})
            # не затирать, если файлов одной роли несколько — собрать списком
            if role in slot:
                slot[role] = slot[role] + " ; " + rel if isinstance(slot[role], str) else rel
            else:
                slot[role] = rel
            continue
        if ext_is_indexable(name):
            unknown.append(rel)
    return posts, unknown


def ext_is_indexable(name: str) -> bool:
    ext = Path(name).suffix.lower()
    return ext == ".md" or ext in MEDIA_EXT


# --------------------------------------------------------------- индекс ---

def sort_key(post: int, meta: dict):
    """Сначала по выпуску (если задан), инфо-посты после; иначе по номеру поста."""
    issue = (meta or {}).get("выпуск", "")
    if issue:
        m = re.match(r"(\d+)(д?)", issue)
        if m:
            return (0, int(m.group(1)), 1 if m.group(2) else 0, post)
    return (1, post, 0, 0)


def cell(rel: str | None) -> str:
    if not rel:
        return "—"
    parts = [p.strip() for p in rel.split(";")]
    return "<br>".join(f"[✅]({p.replace(' ', '%20')})" for p in parts)


def build_index(title: str, posts: dict, mapping: dict, folder: Path) -> str:
    has_map = bool(mapping)
    out = [f"# Индекс: {title}", "",
           "Автосгенерировано make_index.py. Файлы не переименованы — "
           "имена соответствуют выгрузке Rozitta Parser.", ""]
    if has_map:
        out += ["| Выпуск | Пост | Цикл | Тип | Описание | Транскрипт | Медиа | Пост+комментарии |",
                "|:------:|:----:|:-----|:----|:---------|:----------:|:-----:|:----------------:|"]
    else:
        out += ["| Пост | Описание (автоматически) | Транскрипт | Медиа | Пост+комментарии |",
                "|:----:|:-------------------------|:----------:|:-----:|:----------------:|"]

    extra_posts = sorted(p for p in posts if has_map and p not in mapping)
    main_posts = [p for p in posts if not has_map or p in mapping]
    order = sorted(main_posts, key=lambda p: sort_key(p, mapping.get(p)))
    for post in order:
        roles = posts[post]
        if has_map:
            meta = mapping.get(post, {})
            issue = meta.get("выпуск", "")
            tag = f"В{issue}" if issue else "инфо"
            desc = meta.get("описание", "")
            if not desc and roles.get("комментарии"):
                desc = guess_description(folder / roles["комментарии"])
            out.append(f"| {tag} | {post} | {meta.get('цикл') or '—'} | "
                       f"{meta.get('тип') or '—'} | {desc} | "
                       f"{cell(roles.get('транскрипт'))} | {cell(roles.get('медиа'))} | "
                       f"{cell(roles.get('комментарии'))} |")
        else:
            desc = guess_description(folder / roles["комментарии"]) if roles.get("комментарии") else ""
            out.append(f"| {post} | {desc} | {cell(roles.get('транскрипт'))} | "
                       f"{cell(roles.get('медиа'))} | {cell(roles.get('комментарии'))} |")
    if has_map and extra_posts:
        out += ["", "## Файлы вне карты",
                "", "Скорее всего — транскрипты медиа из комментариев "
                "(число в имени — ID сообщения, не поста).", ""]
        for post in extra_posts:
            for role, rel in sorted(posts[post].items()):
                for p in [x.strip() for x in rel.split(";")]:
                    out.append(f"- [{p}]({p.replace(' ', '%20')})")
    out.append("")
    return "\n".join(out)


# ----------------------------------------------------------------- main ---

def main():
    ap = argparse.ArgumentParser(description="Индексатор выгрузок Rozitta Parser (без переименования)")
    ap.add_argument("root", type=Path, help="Корневая папка выгрузки чата")
    ap.add_argument("--map", type=Path, default=None, help="CSV-карта постов")
    ap.add_argument("--init-map", type=Path, default=None,
                    help="Создать заготовку карты по найденным постам и выйти")
    ap.add_argument("--out", default=INDEX_NAME, help=f"Имя файла индекса (по умолчанию {INDEX_NAME})")
    args = ap.parse_args()

    root: Path = args.root
    if not root.is_dir():
        sys.exit(f"Папка не найдена: {root}")

    self_names = {args.out, Path(sys.argv[0]).name}
    if args.map:
        self_names.add(args.map.name)

    posts, unknown = scan(root, self_names)
    print(f"Найдено постов: {len(posts)} "
          f"(транскриптов: {sum('транскрипт' in r for r in posts.values())}, "
          f"медиа: {sum('медиа' in r for r in posts.values())}, "
          f"комментариев: {sum('комментарии' in r for r in posts.values())})")

    if args.init_map:
        init_map(args.init_map, posts, root)
        return

    mapping = load_map(args.map) if args.map else {}
    title = root.name
    index_text = build_index(title, posts, mapping, root)
    (root / args.out).write_text(index_text, encoding="utf-8")
    print(f"Индекс записан: {root / args.out}")

    if mapping:
        missing = sorted(set(posts) - set(mapping))
        if missing:
            print(f"Файлов вне карты: {len(missing)} — вынесены в раздел «Файлы вне карты» в конце индекса")
    if unknown:
        print(f"\nНе сопоставлены ({len(unknown)}):")
        for u in unknown[:20]:
            print(f"  {u}")
        if len(unknown) > 20:
            print(f"  ... и ещё {len(unknown) - 20}")


if __name__ == "__main__":
    main()
