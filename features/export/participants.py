"""
features/export/participants.py — Экспорт списка участников в Markdown.

Не требует QThread — синхронный, быстрый.
Вызывается напрямую из SettingsPanel по кнопке.

Нет импортов Qt. Нет Telethon. Только stdlib + core.utils.

Публичный API:
    get_user_message_counts(db_path, chat_id) → dict[int, int]
        Читает количество сообщений на пользователя прямо из SQLite.

    enrich_and_sort_users(users, counts) → list[dict]
        Добавляет msg_count и сортирует по убыванию активности.

    export_participants_md(users, chat_title, output_dir, counts) → str
        Генерирует MD-файл со списком участников.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime
from typing import Dict, List, Optional

from core.utils import sanitize_filename

logger = logging.getLogger(__name__)


# ==============================================================================
# Подсчёт сообщений из локальной БД
# ==============================================================================

def get_user_message_counts(db_path: str, chat_id: int) -> Dict[int, int]:
    """
    Возвращает словарь {user_id: количество_сообщений} из локальной SQLite БД.

    Читает данные напрямую через sqlite3 (не через DBManager) чтобы не создавать
    зависимости от Qt и не мешать WAL-логике воркеров.

    Args:
        db_path: Путь к файлу telegram_archive.db.
        chat_id: ID чата (нормализованный, как в таблице messages).

    Returns:
        Словарь user_id → кол-во сообщений. Пустой словарь если БД не существует
        или возникла ошибка (не бросает исключений).
    """
    if not db_path or not os.path.exists(db_path):
        return {}

    try:
        conn = sqlite3.connect(db_path, timeout=5, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        cursor = conn.execute(
            """
            SELECT user_id, COUNT(*) AS msg_count
            FROM messages
            WHERE chat_id = ?
              AND user_id IS NOT NULL
              AND user_id != 0
              AND is_comment = 0
            GROUP BY user_id
            ORDER BY msg_count DESC
            """,
            (chat_id,),
        )
        result: Dict[int, int] = {int(row[0]): int(row[1]) for row in cursor.fetchall()}
        conn.close()
        logger.debug(
            "participants: loaded counts for %d users (chat_id=%s)", len(result), chat_id
        )
        return result
    except Exception as exc:
        logger.warning("participants: get_user_message_counts failed: %s", exc)
        return {}


# ==============================================================================
# Вспомогательные функции
# ==============================================================================

def _display_name(user: dict) -> str:
    """Возвращает отображаемое имя пользователя из словаря."""
    uid = user.get("id", 0)
    return (
        user.get("username")
        or user.get("name")
        or user.get("first_name")
        or str(uid)
    )


def enrich_and_sort_users(
    users:  List[dict],
    counts: Dict[int, int],
) -> List[dict]:
    """
    Добавляет поле msg_count к каждому пользователю и сортирует по убыванию.

    Args:
        users:  Список словарей от MembersWorker.
        counts: Словарь {user_id: msg_count} из get_user_message_counts().

    Returns:
        Новый список с полем msg_count, отсортированный:
        1. По msg_count DESC (самые активные вверху).
        2. По имени ASC (алфавитно для одинакового count).
    """
    enriched: List[dict] = []
    for user in users:
        uid = user.get("id", 0)
        enriched.append({**user, "msg_count": counts.get(uid, 0)})

    enriched.sort(key=lambda u: (-u["msg_count"], _display_name(u).lower()))
    return enriched


# ==============================================================================
# Экспорт в Markdown
# ==============================================================================

def export_participants_md(
    users:      List[dict],
    chat_title: str,
    output_dir: str,
    counts:     Optional[Dict[int, int]] = None,
) -> str:
    """
    Создаёт Markdown-файл со списком участников чата.

    Если передан словарь counts:
      - Добавляет колонку «Сообщений».
      - Сортирует список по убыванию активности.
      - Показывает суммарную статистику.

    Формат файла (с counts):
        # Участники: <chat_title>
        Дата выгрузки: YYYY-MM-DD HH:MM
        Всего участников: N  |  Сообщений в архиве: M

        | # | Имя | Username | ID | Сообщений |
        |--:|-----|----------|----|----------:|
        | 1 | ... | @...     | .. |       420 |

    Args:
        users:      Список словарей пользователей (id, username, name, ...).
        chat_title: Название чата (для заголовка и имени файла).
        output_dir: Папка назначения (создаётся автоматически).
        counts:     Опциональный {user_id: msg_count}.

    Returns:
        Абсолютный путь к созданному файлу.

    Raises:
        OSError: если не удалось записать файл.
    """
    os.makedirs(output_dir, exist_ok=True)

    now        = datetime.now()
    date_str   = now.strftime("%Y-%m-%d %H:%M")
    file_date  = now.strftime("%Y-%m-%d_%H-%M")
    safe_title = sanitize_filename(chat_title)
    filename   = f"{safe_title}_participants_{file_date}.md"
    filepath   = os.path.join(output_dir, filename)

    has_counts = bool(counts)

    # Сортируем и обогащаем если есть счётчики
    if has_counts:
        users = enrich_and_sort_users(users, counts)
        total_msgs = sum(u.get("msg_count", 0) for u in users)
        stats_line = (
            f"Всего участников: **{len(users)}**  |  "
            f"Сообщений в архиве: **{total_msgs:,}**"
        )
    else:
        stats_line = f"Всего участников: **{len(users)}**"

    lines: list[str] = [
        f"# Участники: {chat_title}",
        "",
        f"Дата выгрузки: {date_str}  ",
        stats_line,
        "",
        "---",
        "",
        "## Список участников",
        "",
    ]

    # Заголовок таблицы
    if has_counts:
        lines += [
            "| # | Имя | Username | ID | Сообщений |",
            "|--:|-----|----------|----|----------:|",
        ]
    else:
        lines += [
            "| # | Имя | Username | ID |",
            "|--:|-----|----------|-----|",
        ]

    # Строки таблицы
    for idx, user in enumerate(users, start=1):
        uid      = user.get("id", "")
        name     = _display_name(user)
        username = user.get("username") or ""

        name_md     = name.replace("|", "\\|")
        username_md = f"@{username}" if username else "—"

        if has_counts:
            msg_count = user.get("msg_count", counts.get(uid, 0) if uid else 0)
            lines.append(f"| {idx} | {name_md} | {username_md} | {uid} | {msg_count:,} |")
        else:
            lines.append(f"| {idx} | {name_md} | {username_md} | {uid} |")

    content = "\n".join(lines) + "\n"

    with open(filepath, "w", encoding="utf-8") as fh:
        fh.write(content)

    logger.info("participants: exported %d users → %s", len(users), filepath)
    return filepath
