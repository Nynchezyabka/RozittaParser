"""
core/database.py — Менеджер SQLite базы данных Rozitta Parser

Ключевые свойства:
- WAL режим (Write-Ahead Logging) — параллельный read/write без блокировок
- Стратегия соединений:
    · Файловая БД  → thread-local соединения: каждый QThread получает
      своё собственное sqlite3.Connection (WAL позволяет параллельные чтения).
    · In-memory БД → одно разделяемое соединение + Lock: у каждого
      sqlite3.connect(":memory:") своя изолированная БД, поэтому thread-local
      здесь неприменим. In-memory используется только в TopicsWorker (один поток).
- Retry-логика (3 попытки, экспоненциальный backoff) для крайних случаев
- Контекстный менеджер — соединение гарантированно закрывается
- Миграции схемы — таблицы и индексы создаются при первом открытии
- Авто-миграция (insert_chat) — Retry Loop добавляет недостающие колонки на лету

Правильное использование в воркерах:

    # ParseWorker / ExportWorker — файловая БД:
    with DBManager(db_path) as db:
        db.insert_message(...)

    # TopicsWorker — изолированная in-memory БД:
    with DBManager(":memory:") as db:
        ...
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from contextlib import contextmanager
from typing import Generator, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Константы
# ---------------------------------------------------------------------------

_WAL_PRAGMAS = (
    "PRAGMA journal_mode = WAL;"
    "PRAGMA synchronous  = NORMAL;"
    "PRAGMA foreign_keys = ON;"
    "PRAGMA busy_timeout = 60000;"
    "PRAGMA wal_autocheckpoint = 100;"   # P3-1: сброс WAL каждые 100 страниц
)

_MAX_RETRIES      = 3
_RETRY_BASE_DELAY = 0.3


# ---------------------------------------------------------------------------
# Схема базы данных
# ---------------------------------------------------------------------------

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS messages (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id            INTEGER NOT NULL,
    message_id         INTEGER NOT NULL,
    topic_id           INTEGER,
    user_id            INTEGER,
    username           TEXT,
    date               TEXT    NOT NULL,
    text               TEXT,
    media_path         TEXT,
    file_type          TEXT,
    file_size          INTEGER,
    reply_to_msg_id    INTEGER,
    post_id            INTEGER,
    is_comment         INTEGER DEFAULT 0,
    from_linked_group  INTEGER DEFAULT 0,
    merge_group_id     INTEGER,
    merge_part_index   INTEGER
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_messages_unique
    ON messages (chat_id, message_id, COALESCE(topic_id, 0));

CREATE INDEX IF NOT EXISTS idx_messages_chat    ON messages (chat_id);
CREATE INDEX IF NOT EXISTS idx_messages_topic   ON messages (topic_id);
CREATE INDEX IF NOT EXISTS idx_messages_user    ON messages (user_id);
CREATE INDEX IF NOT EXISTS idx_messages_post    ON messages (post_id);
CREATE INDEX IF NOT EXISTS idx_messages_reply   ON messages (reply_to_msg_id);
CREATE INDEX IF NOT EXISTS idx_messages_date    ON messages (date);
CREATE INDEX IF NOT EXISTS idx_merge_group      ON messages (chat_id, merge_group_id)
    WHERE merge_group_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS chats (
    chat_id         INTEGER PRIMARY KEY,
    title           TEXT,
    type            TEXT,
    linked_chat_id  INTEGER,
    metadata        TEXT    DEFAULT ''
);

CREATE TABLE IF NOT EXISTS topics (
    topic_id  INTEGER NOT NULL,
    chat_id   INTEGER NOT NULL,
    title     TEXT,
    PRIMARY KEY (topic_id, chat_id),
    FOREIGN KEY (chat_id) REFERENCES chats (chat_id)
);

CREATE TABLE IF NOT EXISTS transcriptions (
    message_id  INTEGER NOT NULL,
    peer_id     INTEGER NOT NULL,
    text        TEXT    NOT NULL,
    model_type  TEXT    NOT NULL DEFAULT 'base',
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (message_id, peer_id)
);

CREATE TABLE IF NOT EXISTS cached_dialogs (
    chat_id              INTEGER PRIMARY KEY,
    title                TEXT,
    type                 TEXT,
    username             TEXT,
    participants_count   INTEGER,
    linked_chat_id       INTEGER,
    has_comments         INTEGER DEFAULT 0,
    is_linked_discussion INTEGER DEFAULT 0,
    updated_at           TEXT    NOT NULL DEFAULT (datetime('now'))
);
"""


# ---------------------------------------------------------------------------
# DBManager
# ---------------------------------------------------------------------------

class DBManager:
    """
    Менеджер SQLite для Rozitta Parser.

    Стратегия соединений:
    - Файловая БД: thread-local соединения.
    - In-memory БД (":memory:"): единое разделяемое соединение + Lock.

    Usage:
        with DBManager("telegram_archive.db") as db:
            db.insert_message(...)
    """

    def __init__(self, db_path: str = "telegram_archive.db") -> None:
        self.db_path    = db_path
        self._is_memory = (db_path == ":memory:")

        # thread-local для файловых БД
        self._local = threading.local()

        # Разделяемое соединение для in-memory БД
        self._shared_conn: Optional[sqlite3.Connection] = None
        self._shared_lock = threading.Lock()

        # Защита _ensure_schema
        self._init_lock   = threading.Lock()
        self._initialized = False

        self._ensure_schema()

    # ------------------------------------------------------------------
    # Управление соединением
    # ------------------------------------------------------------------

    def _create_conn(self) -> sqlite3.Connection:
        """Создаёт новое sqlite3.Connection с WAL-прагмами."""
        conn = sqlite3.connect(
            self.db_path,
            check_same_thread=False,
            detect_types=sqlite3.PARSE_DECLTYPES,
            timeout=20.0,
        )
        conn.row_factory = sqlite3.Row
        conn.executescript(_WAL_PRAGMAS)
        return conn

    def _get_connection(self) -> sqlite3.Connection:
        """
        Возвращает sqlite3.Connection согласно стратегии соединений.

        - :memory: → единое разделяемое соединение (double-checked locking)
        - файл     → thread-local соединение текущего потока
        """
        if self._is_memory:
            if self._shared_conn is None:
                with self._shared_lock:
                    if self._shared_conn is None:
                        self._shared_conn = self._create_conn()
            return self._shared_conn

        conn: Optional[sqlite3.Connection] = getattr(self._local, "conn", None)
        if conn is None:
            conn = self._create_conn()
            self._local.conn = conn
            logger.debug(
                "DBManager: новое соединение для потока %s (db=%s)",
                threading.current_thread().name,
                self.db_path,
            )
        return conn

    @contextmanager
    def _cursor(self) -> Generator[sqlite3.Cursor, None, None]:
        """
        Контекстный менеджер: курсор с commit/rollback и retry-логикой.

        Для in-memory БД удерживает _shared_lock на время операции.
        """
        conn = self._get_connection()

        for attempt in range(1, _MAX_RETRIES + 1):
            acquired = False
            try:
                if self._is_memory:
                    self._shared_lock.acquire()
                    acquired = True
                cursor = conn.cursor()
                yield cursor
                conn.commit()
                return
            except sqlite3.OperationalError as exc:
                if "locked" in str(exc).lower() and attempt < _MAX_RETRIES:
                    delay = _RETRY_BASE_DELAY * (2 ** (attempt - 1))
                    logger.warning(
                        "DBManager: база заблокирована (попытка %d/%d, задержка %.1fs): %s",
                        attempt, _MAX_RETRIES, delay, exc,
                    )
                    time.sleep(delay)
                else:
                    conn.rollback()
                    raise
            except Exception:
                conn.rollback()
                raise
            finally:
                if acquired and self._is_memory and self._shared_lock.locked():
                    self._shared_lock.release()

    def _ensure_schema(self) -> None:
        """Создаёт таблицы и индексы (идемпотентно, один раз)."""
        with self._init_lock:
            if self._initialized:
                return
            conn = self._get_connection()
            conn.executescript(_SCHEMA_SQL)
            conn.commit()
            self._initialized = True
            logger.info("DBManager: схема инициализирована (%s)", self.db_path)

    def close(self) -> None:
        """Закрывает соединение текущего потока (и разделяемое для :memory:)."""
        if self._is_memory:
            with self._shared_lock:
                if self._shared_conn is not None:
                    try:
                        self._shared_conn.close()
                    except Exception as exc:
                        logger.warning("DBManager: ошибка закрытия in-memory: %s", exc)
                    finally:
                        self._shared_conn = None
        else:
            conn: Optional[sqlite3.Connection] = getattr(self._local, "conn", None)
            if conn is not None:
                try:
                    conn.close()
                except Exception as exc:
                    logger.warning("DBManager: ошибка закрытия: %s", exc)
                finally:
                    self._local.conn = None

    # ------------------------------------------------------------------
    # Контекстный менеджер
    # ------------------------------------------------------------------

    def __enter__(self) -> "DBManager":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Запись данных
    # ------------------------------------------------------------------

    def insert_message(
        self,
        *,
        chat_id:           int,
        message_id:        int,
        date:              str,
        topic_id:          Optional[int] = None,
        user_id:           Optional[int] = None,
        username:          Optional[str] = None,
        text:              Optional[str] = None,
        media_path:        Optional[str] = None,
        file_type:         Optional[str] = None,
        file_size:         Optional[int] = None,
        reply_to_msg_id:   Optional[int] = None,
        post_id:           Optional[int] = None,
        is_comment:        int           = 0,
        from_linked_group: int           = 0,
    ) -> bool:
        """
        Вставляет или заменяет сообщение в таблице messages.

        При конфликте по уникальному индексу (chat_id, message_id,
        COALESCE(topic_id, 0)) заменяет запись — повторный парсинг
        обновляет данные без дублирования.

        Args:
            chat_id:           ID чата (нормализованный, -100... для каналов).
            message_id:        ID сообщения в Telegram.
            date:              ISO-дата ('YYYY-MM-DD HH:MM:SS').
            topic_id:          ID топика форума (None если не форум).
            user_id:           ID отправителя.
            username:          Имя отправителя.
            text:              Текст сообщения.
            media_path:        Абсолютный путь к медиафайлу.
            file_type:         Тип медиа: "photo"|"video"|"voice"|"file" или None.
            file_size:         Размер файла в байтах (None если нет медиа).
            reply_to_msg_id:   ID сообщения-оригинала (ответ).
            post_id:           ID поста (для комментариев к каналу).
            is_comment:        1 если это комментарий.
            from_linked_group: 1 если из linked discussion группы.

        Returns:
            True при успешной операции.
        """
        sql = """
            INSERT OR REPLACE INTO messages
                (chat_id, message_id, topic_id, user_id, username, date, text,
                 media_path, file_type, file_size,
                 reply_to_msg_id, post_id, is_comment, from_linked_group)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        params = (
            chat_id, message_id, topic_id, user_id, username, date, text,
            media_path, file_type, file_size,
            reply_to_msg_id, post_id, is_comment, from_linked_group,
        )
        with self._cursor() as cur:
            cur.execute(sql, params)
        logger.debug("DBManager: сохранено сообщение %d (chat=%d)", message_id, chat_id)
        return True

    def insert_messages_batch(self, rows: List[dict]) -> int:
        """
        Batch-вставка сообщений — 1 commit на N строк.

        Значительно быстрее чем N × insert_message() при скачивании больших чатов.
        Использует executemany → 1 fsync вместо N (прирост до 500× на WAL).

        Args:
            rows: Список словарей с теми же ключами, что и аргументы insert_message().
                  Обязательные ключи: chat_id, message_id, date.
                  Опциональные: topic_id, user_id, username, text, media_path,
                  file_type, file_size, reply_to_msg_id, post_id,
                  is_comment, from_linked_group.

        Returns:
            Количество сохранённых строк. 0 если rows пустой.
        """
        if not rows:
            return 0

        sql = """
            INSERT OR REPLACE INTO messages
                (chat_id, message_id, topic_id, user_id, username, date, text,
                 media_path, file_type, file_size,
                 reply_to_msg_id, post_id, is_comment, from_linked_group)
            VALUES
                (:chat_id, :message_id, :topic_id, :user_id, :username, :date, :text,
                 :media_path, :file_type, :file_size,
                 :reply_to_msg_id, :post_id, :is_comment, :from_linked_group)
        """
        conn = self._get_connection()
        acquired = False
        try:
            if self._is_memory:
                self._shared_lock.acquire()
                acquired = True
            cursor = conn.cursor()
            cursor.executemany(sql, rows)
            conn.commit()
            logger.debug("DBManager: batch insert %d messages", len(rows))
            return len(rows)
        except Exception:
            conn.rollback()
            raise
        finally:
            if acquired and self._is_memory:
                try:
                    self._shared_lock.release()
                except RuntimeError:
                    pass

    def upsert_messages_batch(self, rows: List[dict]) -> int:
        """
        Batch-вставка сообщений в режиме INSERT OR IGNORE.

        Используется в инкрементальном режиме (re_download=False):
        если запись уже существует по UNIQUE INDEX
        (chat_id, message_id, COALESCE(topic_id, 0)), она пропускается
        без ошибки и без перезаписи — merge_group_id / merge_part_index
        существующих строк остаются нетронутыми.

        В отличие от insert_messages_batch (INSERT OR REPLACE), не удаляет
        и не перевставляет строки, что важно для сохранения сцепленных групп.

        Args:
            rows: Список словарей с теми же ключами, что и insert_messages_batch().

        Returns:
            Количество реально вставленных строк (< len(rows) при дублях).
        """
        if not rows:
            return 0

        sql = """
            INSERT OR IGNORE INTO messages
                (chat_id, message_id, topic_id, user_id, username, date, text,
                 media_path, file_type, file_size,
                 reply_to_msg_id, post_id, is_comment, from_linked_group)
            VALUES
                (:chat_id, :message_id, :topic_id, :user_id, :username, :date, :text,
                 :media_path, :file_type, :file_size,
                 :reply_to_msg_id, :post_id, :is_comment, :from_linked_group)
        """
        conn = self._get_connection()
        acquired = False
        try:
            if self._is_memory:
                self._shared_lock.acquire()
                acquired = True
            cursor = conn.cursor()
            cursor.executemany(sql, rows)
            conn.commit()
            logger.debug("DBManager: upsert batch %d rows (INSERT OR IGNORE)", len(rows))
            return len(rows)
        except Exception:
            conn.rollback()
            raise
        finally:
            if acquired and self._is_memory:
                try:
                    self._shared_lock.release()
                except RuntimeError:
                    pass

    def insert_chat(
        self,
        chat_id:        int,
        title:          str,
        chat_type:      str,
        linked_chat_id: Optional[int] = None,
        metadata:       str           = "",
    ) -> None:
        """
        Сохраняет или обновляет чат в таблице chats.

        Колонки в схеме: chat_id, title, type, linked_chat_id, metadata.

        Включает АВТОМАТИЧЕСКОЕ ИСПРАВЛЕНИЕ (Auto-Migration) схемы:
        Retry Loop методично добавляет недостающие колонки по одной
        пока запрос не выполнится успешно. Защищает от потери данных
        при рассинхроне схемы (старый .db файл + новый код).

        Args:
            chat_id:        Нормализованный ID чата.
            title:          Название чата.
            chat_type:      Тип: "channel" | "forum" | "group" | "private".
            linked_chat_id: ID linked discussion группы (None если нет).
            metadata:       Доп. данные в виде строки (JSON или текст).
        """
        sql = """
            INSERT INTO chats (chat_id, title, type, linked_chat_id, metadata)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                title          = excluded.title,
                type           = excluded.type,
                linked_chat_id = excluded.linked_chat_id,
                metadata       = excluded.metadata
        """

        # Retry Loop: до 3 попыток, каждая может добавить одну недостающую колонку
        for attempt in range(_MAX_RETRIES):
            try:
                with self._cursor() as cur:
                    cur.execute(sql, (chat_id, title, chat_type, linked_chat_id, metadata))
                return  # Успешно — выходим

            except sqlite3.OperationalError as exc:
                err_msg = str(exc).lower()

                # --- Авто-миграция: добавляем недостающие колонки по одной ---
                if "no column named type" in err_msg:
                    logger.warning(
                        "DBManager: ⚠️ Авто-миграция: колонка 'type' отсутствует в chats. Добавляю..."
                    )
                    conn = self._get_connection()
                    conn.execute("ALTER TABLE chats ADD COLUMN type TEXT DEFAULT ''")
                    conn.commit()

                elif "no column named linked_chat_id" in err_msg:
                    logger.warning(
                        "DBManager: ⚠️ Авто-миграция: колонка 'linked_chat_id' отсутствует. Добавляю..."
                    )
                    conn = self._get_connection()
                    conn.execute("ALTER TABLE chats ADD COLUMN linked_chat_id INTEGER")
                    conn.commit()

                elif "no column named metadata" in err_msg:
                    logger.warning(
                        "DBManager: ⚠️ Авто-миграция: колонка 'metadata' отсутствует. Добавляю..."
                    )
                    conn = self._get_connection()
                    conn.execute("ALTER TABLE chats ADD COLUMN metadata TEXT DEFAULT ''")
                    conn.commit()

                else:
                    # Ошибка не связана с колонками — логируем схему и пробрасываем
                    self.debug_check_schema("chats")
                    raise

            except sqlite3.Error as exc:
                logger.error("DBManager: ошибка при вставке чата %d: %s", chat_id, exc)
                raise

        logger.error(
            "DBManager: insert_chat не выполнен за %d попыток (chat_id=%d)",
            _MAX_RETRIES, chat_id,
        )

    def debug_check_schema(self, table_name: str) -> None:
        """
        Выводит в лог реальные колонки таблицы из файла БД.
        Вызывается автоматически при неизвестных OperationalError.
        """
        try:
            with self._cursor() as cur:
                cur.execute(f"PRAGMA table_info({table_name})")
                columns = cur.fetchall()
                col_names = [col[1] for col in columns]
                logger.warning(
                    "DBManager: ⚠️ Реальная схема таблицы '%s': %s",
                    table_name, col_names,
                )
        except Exception as exc:
            logger.error("DBManager: не удалось проверить схему '%s': %s", table_name, exc)

    # ------------------------------------------------------------------
    # Чтение данных
    # ------------------------------------------------------------------

    def get_messages(
        self,
        chat_id:          int,
        *,
        topic_id:         Optional[int] = None,
        user_id:          Optional[int] = None,
        include_comments: bool          = False,
    ) -> List[sqlite3.Row]:
        """
        Возвращает сообщения чата с опциональной фильтрацией.

        Args:
            chat_id:          ID чата (нормализованный).
            topic_id:         Фильтр по топику форума.
            user_id:          Фильтр по отправителю.
            include_comments: Включать ли комментарии (is_comment = 1).

        Returns:
            Список sqlite3.Row, отсортированных по дате ASC.
        """
        conditions = ["chat_id = ?"]
        params: List[object] = [chat_id]

        if topic_id is not None:
            conditions.append("topic_id = ?")
            params.append(topic_id)

        if user_id is not None:
            conditions.append("user_id = ?")
            params.append(user_id)

        if not include_comments:
            conditions.append("is_comment = 0")

        where_clause = " AND ".join(conditions)
        sql = f"SELECT * FROM messages WHERE {where_clause} ORDER BY date ASC"

        with self._cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()

    def get_post_with_comments(
        self, chat_id: int, post_id: int
    ) -> List[sqlite3.Row]:
        """
        Возвращает пост и все его комментарии, отсортированных по дате.

        Args:
            chat_id: ID чата (нормализованный).
            post_id: ID поста (message_id основного поста).

        Returns:
            Список sqlite3.Row (пост + комментарии), ORDER BY date ASC.
        """
        sql = """
            SELECT * FROM messages
            WHERE chat_id = ? AND (message_id = ? OR post_id = ?)
            ORDER BY date ASC
        """
        with self._cursor() as cur:
            cur.execute(sql, (chat_id, post_id, post_id))
            return cur.fetchall()

    def get_user_stats(
        self, chat_id: int, limit: int = 50
    ) -> List[Tuple[int, str, int]]:
        """
        Возвращает топ активных участников чата.

        Args:
            chat_id: ID чата (нормализованный).
            limit:   Максимальное количество пользователей.

        Returns:
            Список (user_id, username, messages_count), сортировка по убыванию.
        """
        sql = """
            SELECT user_id, username, COUNT(*) AS cnt
            FROM messages
            WHERE chat_id = ? AND user_id IS NOT NULL
            GROUP BY user_id
            ORDER BY cnt DESC
            LIMIT ?
        """
        with self._cursor() as cur:
            cur.execute(sql, (chat_id, limit))
            return [(row[0], row[1], row[2]) for row in cur.fetchall()]

    def get_chat_title(self, chat_id: int) -> Optional[str]:
        """
        Возвращает название чата из таблицы chats.

        Args:
            chat_id: ID чата (нормализованный).

        Returns:
            Название чата или None если чат не найден.
        """
        sql = "SELECT title FROM chats WHERE chat_id = ?"
        with self._cursor() as cur:
            cur.execute(sql, (chat_id,))
            row = cur.fetchone()
        return row["title"] if row else None

    def get_topics(self, chat_id: int) -> List[sqlite3.Row]:
        """
        Возвращает все топики форума из локальной БД.

        Args:
            chat_id: ID форума (нормализованный).

        Returns:
            Список sqlite3.Row (topic_id, chat_id, title), ORDER BY topic_id.
        """
        sql = "SELECT * FROM topics WHERE chat_id = ? ORDER BY topic_id ASC"
        with self._cursor() as cur:
            cur.execute(sql, (chat_id,))
            return cur.fetchall()

    # ------------------------------------------------------------------
    # STT — транскрипции
    # ------------------------------------------------------------------

    def insert_transcription(
        self,
        message_id: int,
        peer_id: int,
        text: str,
        model_type: str = "base",
    ) -> None:
        """
        Сохраняет транскрипцию голосового/видео сообщения.

        Использует INSERT OR REPLACE — повторный вызов обновит текст.
        """
        sql = """
            INSERT OR REPLACE INTO transcriptions
                (message_id, peer_id, text, model_type, created_at)
            VALUES
                (:message_id, :peer_id, :text, :model_type, datetime('now'))
        """
        for attempt in range(_MAX_RETRIES):
            try:
                with self._cursor() as cur:
                    cur.execute(sql, {
                        "message_id": message_id,
                        "peer_id": peer_id,
                        "text": text,
                        "model_type": model_type,
                    })
                return
            except sqlite3.OperationalError as exc:
                if "locked" in str(exc).lower() and attempt < _MAX_RETRIES - 1:
                    import time
                    time.sleep(_RETRY_BASE_DELAY * (2 ** attempt))
                    continue
                raise

    def get_transcription(self, message_id: int, peer_id: int) -> Optional[str]:
        """
        Возвращает текст транскрипции или None если не найдена.
        """
        sql = "SELECT text FROM transcriptions WHERE message_id = ? AND peer_id = ?"
        with self._cursor() as cur:
            cur.execute(sql, (message_id, peer_id))
            row = cur.fetchone()
        return row[0] if row else None

    def get_stt_candidates(
        self, chat_id: int, file_types: Optional[List[str]] = None
    ) -> List[sqlite3.Row]:
        """
        Возвращает сообщения чата с медиафайлами, у которых нет транскрипции.

        Args:
            chat_id:    ID чата (нормализованный).
            file_types: Список типов файлов ('voice', 'video_note', 'video').
                        По умолчанию: ['voice', 'video_note'].

        Returns:
            Список sqlite3.Row (id, message_id, media_path, file_type).
        """
        if file_types is None:
            file_types = ["voice", "video_note"]
        placeholders = ",".join("?" * len(file_types))
        sql = f"""
            SELECT m.id, m.message_id, m.media_path, m.file_type
            FROM messages m
            LEFT JOIN transcriptions t
                ON t.message_id = m.message_id AND t.peer_id = m.chat_id
            WHERE m.chat_id = ?
              AND m.file_type IN ({placeholders})
              AND m.media_path IS NOT NULL
              AND t.message_id IS NULL
            ORDER BY m.date ASC
        """
        params: List[object] = [chat_id, *file_types]
        with self._cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()

    def get_transcriptions_for_chat(self, chat_id: int) -> dict:
        """
        Возвращает словарь {message_id: text} всех транскрипций чата.

        Используется в DocxGenerator для вставки текста распознавания.
        """
        sql = """
            SELECT t.message_id, t.text
            FROM transcriptions t
            JOIN messages m ON m.message_id = t.message_id AND m.chat_id = t.peer_id
            WHERE m.chat_id = ?
        """
        with self._cursor() as cur:
            cur.execute(sql, (chat_id,))
            return {row[0]: row[1] for row in cur.fetchall()}

    def get_distinct_post_ids(
        self, chat_id: int, topic_id: Optional[int] = None
    ) -> List[int]:
        """
        Возвращает уникальные post_id не-комментариев для split_mode='post'.

        Используется при генерации DOCX по постам без загрузки всех данных.

        Args:
            chat_id:  ID чата.
            topic_id: Фильтр по топику (опционально).

        Returns:
            Список уникальных post_id, ORDER BY post_id ASC.
        """
        conditions = ["chat_id = ?", "is_comment = 0", "post_id IS NOT NULL"]
        params: List[object] = [chat_id]

        if topic_id is not None:
            conditions.append("topic_id = ?")
            params.append(topic_id)

        where_clause = " AND ".join(conditions)
        sql = f"SELECT DISTINCT post_id FROM messages WHERE {where_clause} ORDER BY post_id ASC"

        with self._cursor() as cur:
            cur.execute(sql, params)
            return [row[0] for row in cur.fetchall()]

    def message_count(self, chat_id: int, topic_id: Optional[int] = None) -> int:
        """
        Возвращает общее количество сообщений в чате (включая комментарии).

        Args:
            chat_id:  ID чата.
            topic_id: Фильтр по топику (опционально).

        Returns:
            Целое число сообщений.
        """
        if topic_id is not None:
            sql = "SELECT COUNT(*) FROM messages WHERE chat_id = ? AND topic_id = ?"
            params: tuple = (chat_id, topic_id)
        else:
            sql = "SELECT COUNT(*) FROM messages WHERE chat_id = ?"
            params = (chat_id,)

        with self._cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
        return int(row[0]) if row else 0

    # ------------------------------------------------------------------
    # Методы для склейки сообщений (MergerService)
    # ------------------------------------------------------------------

    def set_merge_group(self, message_ids: List[int], group_id: int) -> None:
        """
        Массово проставляет merge_group_id и merge_part_index для списка сообщений.

        Сообщения нумеруются внутри группы начиная с 0 (порядок передачи списка).
        Использует executemany — один round-trip к БД вместо N запросов.

        Args:
            message_ids: Список первичных ключей (поле `id` из таблицы messages)
                         в хронологическом порядке — индекс определяет merge_part_index.
            group_id:    Уникальный идентификатор группы (присваивается MergerService).

        Example:
            db.set_merge_group([101, 102, 103], group_id=7)
            # → строки с id=101,102,103 получат merge_group_id=7,
            #   merge_part_index=0,1,2 соответственно.
        """
        if not message_ids:
            return
        params = [
            (group_id, part_idx, row_id)
            for part_idx, row_id in enumerate(message_ids)
        ]
        sql = "UPDATE messages SET merge_group_id = ?, merge_part_index = ? WHERE id = ?"
        with self._cursor() as cur:
            cur.executemany(sql, params)
        logger.debug(
            "DBManager: set_merge_group group_id=%d, %d сообщений",
            group_id, len(message_ids),
        )

    def get_messages_for_merge(
        self,
        chat_id:  int,
        topic_id: Optional[int] = None,
    ) -> List[sqlite3.Row]:
        """
        Возвращает сообщения чата в хронологическом порядке (ASC) для алгоритма склейки.

        Выбирает только не-комментарии (is_comment = 0), т.к. склейка применяется
        к основному потоку сообщений, а не к комментариям под постами.

        Args:
            chat_id:  ID чата (нормализованный).
            topic_id: Фильтр по топику форума (None — весь чат).

        Returns:
            Список sqlite3.Row с полями: id, message_id, user_id, date,
            text, merge_group_id — отсортированных по date ASC.
        """
        conditions = ["chat_id = ?", "is_comment = 0"]
        params: List[object] = [chat_id]

        if topic_id is not None:
            conditions.append("topic_id = ?")
            params.append(topic_id)

        where_clause = " AND ".join(conditions)
        sql = (
            f"SELECT id, message_id, user_id, date, text, merge_group_id "
            f"FROM messages WHERE {where_clause} ORDER BY date ASC"
        )
        with self._cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()

    def get_merge_group(self, chat_id: int, group_id: int) -> List[sqlite3.Row]:
        """
        Возвращает все части одного склеенного блока в порядке merge_part_index.

        Используется генератором DOCX для сборки единого блока текста/медиа
        из нескольких сообщений с одним merge_group_id.

        Args:
            chat_id:  ID чата (нормализованный).
            group_id: Идентификатор группы (merge_group_id).

        Returns:
            Список sqlite3.Row, ORDER BY merge_part_index ASC.
            Пустой список если группа не найдена.
        """
        sql = """
            SELECT * FROM messages
            WHERE chat_id = ? AND merge_group_id = ?
            ORDER BY merge_part_index ASC
        """
        with self._cursor() as cur:
            cur.execute(sql, (chat_id, group_id))
            return cur.fetchall()

    # ------------------------------------------------------------------
    # Кэш списка диалогов
    # ------------------------------------------------------------------

    def save_dialogs_cache(self, dialogs: List[dict]) -> None:
        """
        Сохраняет список чатов в таблицу cached_dialogs.

        Перезаписывает существующие записи (INSERT OR REPLACE),
        обновляет updated_at — так кэш всегда актуален после
        успешной загрузки с сервера.

        Args:
            dialogs: Список chat-dict (формат ChatsService.get_dialogs()).
        """
        rows = [
            (
                d["id"],
                d.get("title"),
                d.get("type"),
                d.get("username"),
                d.get("participants_count"),
                d.get("linked_chat_id"),
                int(bool(d.get("has_comments", False))),
                int(bool(d.get("is_linked_discussion", False))),
            )
            for d in dialogs
        ]
        with self._cursor() as cur:
            cur.executemany(
                """
                INSERT OR REPLACE INTO cached_dialogs
                    (chat_id, title, type, username, participants_count,
                     linked_chat_id, has_comments, is_linked_discussion,
                     updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                """,
                rows,
            )
        logger.info("DBManager: cached_dialogs saved %d rows", len(rows))

    def load_dialogs_cache(self, max_age_hours: int = 24) -> List[dict]:
        """
        Читает кэш диалогов, если он не устарел.

        Args:
            max_age_hours: Максимальный возраст кэша в часах (default 24).

        Returns:
            Список chat-dict в том же формате что ChatsService.get_dialogs(),
            или [] если кэш пуст / устарел.
        """
        with self._cursor() as cur:
            cur.execute(
                """
                SELECT chat_id, title, type, username, participants_count,
                       linked_chat_id, has_comments, is_linked_discussion
                FROM   cached_dialogs
                WHERE  updated_at > datetime('now', ?)
                ORDER BY
                    CASE type
                        WHEN 'channel' THEN 0
                        WHEN 'forum'   THEN 1
                        WHEN 'group'   THEN 2
                        ELSE                3
                    END
                """,
                (f"-{max_age_hours} hours",),
            )
            rows = cur.fetchall()

        if not rows:
            return []

        return [
            {
                "id":                  r[0],
                "title":               r[1] or "",
                "type":                r[2] or "group",
                "username":            r[3],
                "participants_count":  r[4],
                "linked_chat_id":      r[5],
                "has_comments":        bool(r[6]),
                "is_linked_discussion": bool(r[7]),
                "is_forum":            r[2] == "forum",
            }
            for r in rows
        ]

    def dialogs_cache_age_minutes(self) -> Optional[int]:
        """
        Возвращает возраст кэша в минутах, или None если кэша нет.
        Используется для отображения в UI ('обновлено 10 мин назад').
        """
        with self._cursor() as cur:
            cur.execute(
                "SELECT MIN(updated_at) FROM cached_dialogs"
            )
            row = cur.fetchone()
        if not row or not row[0]:
            return None
        import datetime as _dt
        try:
            updated = _dt.datetime.fromisoformat(row[0])
            now     = _dt.datetime.utcnow()
            return max(0, int((now - updated).total_seconds() / 60))
        except Exception:
            return None
