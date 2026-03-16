"""
core/merger.py — Сервис «агрессивной» склейки последовательных сообщений

Проблема, которую решает модуль:
    Telegram позволяет быстро отправлять несколько коротких сообщений подряд,
    которые семантически составляют один «абзац». В первом сообщении может быть
    начало мысли, во втором — завершение с важным тегом/ключевым словом.
    При наивном экспорте DOCX такие пары разрываются, теряется контекст.

Алгоритм «агрессивной» склейки:
    Два соседних сообщения объединяются в один блок если ОДНОВРЕМЕННО выполнены:
      1. Один и тот же sender_id (автор)
      2. Временной интервал между ними ≤ MERGE_TIME_DELTA секунд
      3. Между ними не вмешивался другой участник

    Проход одним O(n) по отсортированному (ASC) потоку сообщений.
    Никаких «минимальных длин» — даже одиночный символ склеивается,
    т.к. тег может находиться в любой части разбитого сообщения.

Использование:

    from core.database import DBManager
    from core.merger import MergerService

    with DBManager(cfg.db_path) as db:
        svc = MergerService(log=print)
        stats = svc.run_merge(db, chat_id=-1001234567890)
        print(f"Групп: {stats.groups_count}, одиночек: {stats.singles_count}")

Нет никаких Qt-импортов. Логирование через стандартный logging.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Tuple

from core.database import DBManager

logger = logging.getLogger(__name__)

# Тип лог-колбэка (UI-сигнал или просто print/logger.info)
_LogCallback = Callable[[str], None]

# Временной порог склейки по умолчанию (секунды)
# Переопределяется через параметр time_delta в MergerService.__init__
DEFAULT_MERGE_TIME_DELTA: int = 60


# ==============================================================================
# Датакласс результата
# ==============================================================================

@dataclass
class MergeStats:
    """
    Итог одного прохода склейки для заданного чата / топика.

    Attributes:
        chat_id:       Нормализованный ID чата.
        topic_id:      ID топика (None = весь чат).
        total_msgs:    Всего сообщений обработано.
        groups_count:  Количество созданных групп (≥ 2 сообщений).
        singles_count: Сообщения, оставшиеся одиночными (группа из 1).
        merged_msgs:   Суммарное число сообщений, вошедших в группы ≥ 2.
    """
    chat_id:       int
    topic_id:      Optional[int]
    total_msgs:    int = 0
    groups_count:  int = 0
    singles_count: int = 0
    merged_msgs:   int = 0


# ==============================================================================
# Внутренний датакласс группы (не экспортируется)
# ==============================================================================

@dataclass
class _Group:
    """Промежуточное состояние группы при обходе сообщений."""
    row_ids:    List[int]   # первичные ключи (id) — для UPDATE
    sender_id:  Optional[int]
    last_date:  datetime    # дата последнего добавленного сообщения


# ==============================================================================
# MergerService
# ==============================================================================

class MergerService:
    """
    Сервис агрессивной склейки последовательных сообщений одного автора.

    Не хранит состояния между вызовами run_merge — каждый вызов независим.
    Один экземпляр можно переиспользовать для нескольких чатов.

    Args:
        time_delta: Порог склейки в секундах (по умолчанию DEFAULT_MERGE_TIME_DELTA).
        log:        Колбэк для UI-логов. По умолчанию — logger.info.

    Example:
        svc = MergerService(time_delta=60, log=self.log_message.emit)
        stats = svc.run_merge(db, chat_id, topic_id=None)
    """

    def __init__(
        self,
        time_delta: int          = DEFAULT_MERGE_TIME_DELTA,
        log:        _LogCallback = None,
    ) -> None:
        self._time_delta = time_delta
        self._log        = log or logger.info

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    def run_merge(
        self,
        db:       DBManager,
        chat_id:  int,
        topic_id: Optional[int] = None,
    ) -> MergeStats:
        """
        Координирует полный цикл склейки для одного чата / топика:
            1. Выгрузка сообщений (get_messages_for_merge)
            2. Группировка (_detect_groups) — O(n)
            3. Запись групп в БД (set_merge_group)

        Идемпотентен: повторный вызов перезаписывает merge_group_id.
        Уже склеенные сообщения с корректным group_id не дублируются.

        Args:
            db:       Открытый DBManager (контекст управляется снаружи).
            chat_id:  Нормализованный ID чата.
            topic_id: ID топика форума или None (весь чат).

        Returns:
            MergeStats с итоговой статистикой.
        """
        self._log(f"🔗 Запуск склейки: chat_id={chat_id}, topic_id={topic_id}")
        logger.info(
            "merger: run_merge chat_id=%d topic_id=%s time_delta=%ds",
            chat_id, topic_id, self._time_delta,
        )

        # 1. Загружаем сообщения хронологически
        rows = db.get_messages_for_merge(chat_id, topic_id=topic_id)

        stats = MergeStats(chat_id=chat_id, topic_id=topic_id, total_msgs=len(rows))

        if not rows:
            self._log("⚠️ Нет сообщений для склейки")
            logger.warning("merger: no messages found for chat_id=%d", chat_id)
            return stats

        self._log(f"📨 Загружено {len(rows)} сообщений для анализа")

        # 2. Детектируем группы
        groups = self._detect_groups(rows)

        # 3. Пишем в БД и собираем статистику
        next_group_id = self._allocate_group_id_base(chat_id)

        for group in groups:
            if len(group.row_ids) >= 2:
                db.set_merge_group(group.row_ids, group_id=next_group_id)
                stats.groups_count  += 1
                stats.merged_msgs   += len(group.row_ids)
                next_group_id       += 1
            else:
                stats.singles_count += 1

        self._log(
            f"✅ Склейка завершена: {stats.groups_count} групп "
            f"({stats.merged_msgs} сообщений), {stats.singles_count} одиночных"
        )
        logger.info(
            "merger: done chat_id=%d: groups=%d merged=%d singles=%d",
            chat_id, stats.groups_count, stats.merged_msgs, stats.singles_count,
        )
        return stats

    # ------------------------------------------------------------------
    # Внутренние методы
    # ------------------------------------------------------------------

    def _detect_groups(self, rows: List[sqlite3.Row]) -> List[_Group]:
        """
        Однопроходный O(n) алгоритм группировки сообщений.

        Агрессивная эвристика:
            - Объединяем если: тот же sender_id И Δt ≤ time_delta
            - Вмешательство другого участника разрывает группу немедленно
            - Нет минимального порога длины текста (тег может быть в части 2)

        Args:
            rows: Список sqlite3.Row, отсортированный по date ASC.
                  Ожидаемые поля: id, user_id, date (ISO-строка).

        Returns:
            Список _Group в порядке появления в тексте.
            Каждый _Group содержит ≥ 1 элемент в row_ids.
        """
        groups: List[_Group] = []
        current: Optional[_Group] = None

        for row in rows:
            row_id    = row["id"]
            sender_id = row["user_id"]
            date_str  = row["date"]

            # Парсим дату — все даты хранятся в UTC ISO-формате
            msg_date = _parse_date(date_str)

            if current is None:
                # Первое сообщение — начинаем первую группу
                current = _Group(
                    row_ids   = [row_id],
                    sender_id = sender_id,
                    last_date = msg_date,
                )
                continue

            # Вычисляем временной интервал
            delta_s = (msg_date - current.last_date).total_seconds()

            same_author   = (sender_id is not None and sender_id == current.sender_id)
            within_window = (0 <= delta_s <= self._time_delta)

            if same_author and within_window:
                # Продолжаем текущую группу
                current.row_ids.append(row_id)
                current.last_date = msg_date
            else:
                # Закрываем текущую группу, начинаем новую
                groups.append(current)
                current = _Group(
                    row_ids   = [row_id],
                    sender_id = sender_id,
                    last_date = msg_date,
                )

        # Не забываем последнюю незакрытую группу
        if current is not None:
            groups.append(current)

        logger.debug(
            "merger: _detect_groups: %d сообщений → %d групп (time_delta=%ds)",
            len(rows), len(groups), self._time_delta,
        )
        return groups

    @staticmethod
    def _allocate_group_id_base(chat_id: int) -> int:
        """
        Генерирует базовый group_id, уникальный на уровне чата.

        Использует abs(chat_id) * 100_000 как «пространство имён»,
        чтобы группы разных чатов не пересекались при одновременном
        хранении в одной БД.

        Возвращает стартовый ID; вызывающий код инкрементирует его сам.

        Args:
            chat_id: Нормализованный ID чата (может быть отрицательным).

        Returns:
            Целое число ≥ 1 — начало диапазона group_id для этого чата.
        """
        # abs() т.к. channel ID приходит как -1001234567890
        return abs(chat_id) * 100_000 + 1


# ==============================================================================
# Вспомогательные функции
# ==============================================================================

def _parse_date(date_str: str) -> datetime:
    """
    Парсит ISO-дату из БД в timezone-aware datetime (UTC).

    Поддерживает форматы:
        "2024-03-15 14:23:45"     → формат из strftime("%Y-%m-%d %H:%M:%S")
        "2024-03-15T14:23:45"     → ISO 8601 с T-разделителем
        "2024-03-15 14:23:45+00:00" → с явным UTC offset

    Args:
        date_str: Строка даты из поля messages.date.

    Returns:
        datetime с tzinfo=UTC.

    Raises:
        ValueError: если строка не соответствует ни одному из форматов.
    """
    # Нормализуем: заменяем T на пробел, убираем дробные секунды и offset
    normalized = date_str.replace("T", " ").split("+")[0].split(".")[0].strip()

    try:
        dt = datetime.strptime(normalized, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        # Крайний случай — дата без времени
        dt = datetime.strptime(normalized[:10], "%Y-%m-%d")

    return dt.replace(tzinfo=timezone.utc)
