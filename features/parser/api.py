"""
features/parser/api.py — Сбор сообщений, скачивание медиа, обход FloodWait

Содержит всю логику итерации по сообщениям Telegram:
  - collect_data()       — главный метод: iter_messages + фильтрация + медиа
  - _process_message()   — обработка одного сообщения: имя, дата, медиа → БД
  - _download_media()    — скачивание файла с FloodWait retry и стримингом
  - _get_post_replies()  — комментарии к посту из linked группы
  - _should_download()   — классификация медиа по фильтру (photo/video/voice/...)
  - _extract_topic_id()  — определение топика из reply_to
  - _get_sender_name()   — имя отправителя из объекта сообщения

FloodWait стратегия:
    1. iter_messages — при FloodWaitError: sleep(seconds + 3) и продолжаем.
       Telethon сам восстанавливает итератор после паузы, поэтому достаточно
       поймать исключение ВОКРУГ цикла и перезапустить с последнего message_id.
    2. download_media — при FloodWaitError: sleep(seconds + 3), max 3 попытки.
    3. Все остальные сетевые ошибки: max 3 попытки с линейным backoff (5 сек).

Особенности скачивания медиа (исправление memory leak):
    - Всегда передаём file=path в download_media → Telethon пишет потоком на диск.
    - Никогда не скачиваем в bytes (это и было источником OOM при больших видео).
    - Размер файла НЕ проверяем заранее — file_size из MessageMediaDocument
      часто неточный. Стриминг на диск безопасен для любого размера.

Нет никаких Qt-импортов. Весь UI-код — в features/parser/ui.py.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field, replace as dataclass_replace
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, List, Optional

from telethon import TelegramClient
from telethon.errors import (
    BadRequestError,
    FloodWaitError as TelethonFloodWaitError,
    RPCError,
)
from telethon.tl.types import (
    Channel,
    Chat,
    DocumentAttributeAudio,
    DocumentAttributeVideo,
    Message,
    MessageMediaDocument,
    MessageMediaPhoto,
    User,
)

from config import (
    DAYS_LIMIT_ALL_TIME,
    MAX_COMMENT_LIMIT,
    MEDIA_FOLDER_NAME,
    MESSAGES_LOG_INTERVAL,
)
from core.database import DBManager
from core.exceptions import (
    ChatNotFoundError,
    FloodWaitError,
    TelegramError,
)
from core.retry import async_retry
from core.utils import ensure_aware_utc, finalize_telegram_id, sanitize_filename, TelegramEntityType, DownloadTracker

# simpleeval — опциональная зависимость для filter_expression
# Без неё параметр CollectParams.filter_expression молча игнорируется.
try:
    from simpleeval import simple_eval as _simple_eval
    _SIMPLEEVAL_OK = True
except ImportError:
    _SIMPLEEVAL_OK = False
    _simple_eval = None  # type: ignore

logger = logging.getLogger(__name__)

# Тип лог-колбэка: Qt-сигнал или просто print/logger.info
_LogCallback      = Callable[[str], None]
# Тип прогресс-колбэка: принимает int 0..100
_ProgressCallback = Callable[[int], None]

# Максимальное число ретраев при сетевых ошибках
_MAX_RETRIES = 3
# Базовая пауза между ретраями (секунды)
_RETRY_BASE_DELAY = 5.0
# Дополнительный буфер после FloodWait (секунды)
_FLOOD_BUFFER = 3
# Максимальное число параллельных скачиваний медиа (Semaphore)
_MEDIA_PARALLELISM = 3
# Число сообщений в одном gather()-пакете задач (только для задач скачивания медиа)
_TASK_BATCH_SIZE = 20
# Число строк в одном SQLite batch-flush во время парсинга текстовых сообщений.
# Защищает от потери всего прогресса при падении — пишем каждые 200 сообщений,
# а не только в конце всего чата.
_DB_BATCH_SIZE = 200
# Через сколько сообщений замерять время ответа сервера для адаптивной паузы
_ADAPTIVE_BATCH_SIZE = 100
# Подпапки для каждого типа медиа внутри MEDIA_FOLDER_NAME
_MEDIA_SUBFOLDERS: dict[str, str] = {
    "photo":      "photos",
    "video":      "videos",
    "voice":      "voice",
    "video_note": "video_notes",
    "file":       "files",
}

# ── TeleGet — докачка больших файлов ─────────────────────────────────────────
# Порог в байтах: файлы НИЖЕ этого лимита скачиваются стандартным
# Telethon download_media (быстро, без лишних зависимостей).
# Файлы ВЫШЕ лимита → TeleGet (поддерживает resume, FILE_REFERENCE_EXPIRED,
# многопоточность внутри одного потока asyncio).
_TELEGET_THRESHOLD_BYTES: int = 50 * 1_024 * 1_024   # 50 МБ
# Максимальный таймаут для TeleGet-загрузок (секунды).
# TeleGet сам восстанавливается после разрывов; этот guard нужен только
# если процесс «завис» на уровне ОС (например, потерян сокет без TCP RST).
_TELEGET_MAX_TIMEOUT: float = 4.0 * 3600.0             # 4 часа


# ==============================================================================
# Датакласс параметров сбора
# ==============================================================================

@dataclass
class CollectParams:
    """
    Параметры одного запуска collect_data().

    Передаётся из ParseWorker (ui.py) в ParserService.collect_data().
    Отделяет «что парсить» от «как парсить» и устраняет длинные сигнатуры.

    Attributes:
        chat_id:           ID чата (любой формат; нормализуется внутри).
        topic_id:          ID топика форума (None = весь чат).
        days_limit:        Глубина в днях. 0 или >= DAYS_LIMIT_ALL_TIME → всё время.
        media_filter:      Список внутренних ключей медиа: "photo", "video", ...
                           Пустой список → скачивать всё. None → ничего не скачивать.
        download_comments: Скачивать ли комментарии для каналов.
        user_ids:          Фильтр по участникам — список ID (None = все).
        output_dir:        Корневая папка для медиа и БД.
    """
    chat_id:           int
    topic_id:          Optional[int]       = None
    days_limit:        int                 = 0       # используется если date_from не задан
    date_from:         Optional[datetime]  = None    # нижняя граница дат (включительно)
    date_to:           Optional[datetime]  = None    # верхняя граница дат (включительно)
    media_filter:      Optional[List[str]] = None
    download_comments: bool                = False
    user_ids:          Optional[List[int]] = None
    output_dir:        str                 = "output"
    re_download:       bool                = False   # True = игнорировать downloaded.txt и перекачать заново
    filter_expression: Optional[str]      = None    # выражение-фильтр сообщений (simpleeval)
    use_takeout:       bool                = False   # True = использовать Takeout API (отдельные лимиты)


# ==============================================================================
# Результат collect_data
# ==============================================================================

@dataclass
class CollectResult:
    """
    Результат работы collect_data().

    Attributes:
        success:         True если сбор завершён без критических ошибок.
        chat_id:         Нормализованный chat_id.
        chat_title:      Название чата.
        messages_count:  Всего сохранено сообщений (включая комментарии).
        comments_count:  Сохранено комментариев.
        media_count:     Скачано медиафайлов.
        period_label:    Строка периода для имени файла DOCX.
        errors:          Некритические ошибки (например, один файл не скачался).
    """
    success:        bool
    chat_id:        int
    chat_title:     str            = ""
    messages_count: int            = 0
    comments_count: int            = 0
    media_count:    int            = 0
    period_label:   str            = "fullchat"
    errors:         List[str]      = field(default_factory=list)
    # Абсолютный путь к БД — передаётся из ParseWorker, чтобы MainWindow
    # не реконструировал путь из chat_title (расхождение → OperationalError).
    db_path:        str            = ""


# ==============================================================================
# ParserService
# ==============================================================================

class ParserService:
    """
    Сервис парсинга: итерирует сообщения, скачивает медиа, сохраняет в БД.

    Инициализируется уже подключённым TelegramClient и открытым DBManager.
    Жизненным циклом клиента и БД управляет ParseWorker (features/parser/ui.py).

    Args:
        client:     Подключённый TelegramClient.
        db:         Открытый DBManager (файловая или :memory: БД).
        log:        Колбэк для UI-логов (по умолчанию logger.info).

    Example (в QThread.run):
        client = TelegramClient(...)
        await client.connect()
        with DBManager(cfg.db_path) as db:
            service = ParserService(client, db, log=self.log_message.emit)
            result = await service.collect_data(params)
        await client.disconnect()
    """

    def __init__(
        self,
        client:   TelegramClient,
        db:       DBManager,
        log:      _LogCallback      = None,
        progress: _ProgressCallback = None,
    ) -> None:
        self._client      = client
        self._db          = db
        self._log         = log or logger.info
        self._progress_cb = progress or (lambda _: None)

        # Счётчики (обнуляются в начале каждого collect_data)
        self._msg_count:     int = 0
        self._comment_count: int = 0
        self._media_count:   int = 0

        # Текущий контекст (для путей к медиа)
        self._chat_title:  str = "chat"
        self._output_dir:  str = "output"

        # TeleGet загрузчик — инициализируется лениво при первом вызове
        # _init_teleget().  None = ещё не инициализирован;
        # False = попытка провалилась (библиотека отсутствует);
        # объект Downloader = готов к работе.
        self._teleget_downloader = None  # type: ignore[assignment]

    # ------------------------------------------------------------------
    # 1. Главный метод
    # ------------------------------------------------------------------

    async def collect_data(self, params: CollectParams) -> CollectResult:
        """
        Основной метод: итерирует сообщения чата, скачивает медиа, пишет в БД.

        Поток выполнения:
            1. Использовать chat_id из params (уже нормализован ChatsService)
            2. get_entity → получить название и тип чата
            3. Сохранить чат в БД (insert_chat)
            4. Вычислить cutoff_date из date_from / days_limit
            5. Быстрый count через get_messages(limit=1) для прогресс-бара
            6. iter_messages с reply_to=topic_id (если топик)
            7. Для каждого сообщения: фильтр по дате → фильтр по юзеру → _process_message
            8. Batch insert каждые 200 сообщений + финальный flush
            9. Для каналов с download_comments: собрать post_ids → get_post_replies
            10. Вернуть CollectResult

        Args:
            params: Параметры парсинга (CollectParams).

        Returns:
            CollectResult с итоговой статистикой.

        Raises:
            ChatNotFoundError: если чат не найден.
            TelegramError:     при критической ошибке API (не FloodWait).
        """
        # --- Сброс счётчиков и семафор параллельных скачиваний ---
        self._msg_count     = 0
        self._comment_count = 0
        self._media_count   = 0
        self._output_dir    = params.output_dir
        self._sem           = asyncio.Semaphore(_MEDIA_PARALLELISM)

        errors: List[str] = []

        # --- ID уже нормализован через get_peer_id в ChatsService.get_dialogs() ---
        normalized_id = params.chat_id
        logger.debug("parser: collect_data using chat_id=%s (pre-normalized by ChatsService)", normalized_id)

        # --- Получаем entity ---
        logger.debug("[DIAG] get_entity start: chat_id=%s", normalized_id)
        self._log(f"[DIAG] get_entity → {normalized_id}")
        try:
            entity = await self._client.get_entity(normalized_id)
        except Exception as exc:
            raise ChatNotFoundError(
                normalized_id, f"Чат {normalized_id} не найден: {exc}"
            ) from exc
        logger.debug("[DIAG] get_entity done: type=%s id=%s", type(entity).__name__, getattr(entity, 'id', '?'))
        self._log(f"[DIAG] entity OK: {type(entity).__name__} id={getattr(entity, 'id', '?')}")

        # --- Определяем название и тип чата ---
        chat_title = (
            getattr(entity, "title", None)
            or getattr(entity, "username", None)
            or str(normalized_id)
        )
        self._chat_title = chat_title

        chat_type = self._classify_chat_type(entity)
        self._log(f"📂 Чат: {chat_title} ({chat_type})")
        logger.info("parser: chat %s type=%s", normalized_id, chat_type)

        # --- Linked group для комментариев ---
        linked_chat_id: Optional[int] = None
        if params.download_comments and chat_type == "channel":
            from features.chats.api import ChatsService
            chats_svc = ChatsService(self._client)
            linked_chat_id = await chats_svc.get_linked_group(
                normalized_id, log=self._log
            )
            if not linked_chat_id:
                self._log("⚠️ У канала нет группы комментариев — пропускаем")
                params = dataclass_replace(params, download_comments=False)

        # --- Сохраняем чат в БД ---
        self._db.insert_chat(normalized_id, chat_title, chat_type, linked_chat_id)

        # --- Вычисляем cutoff_date (нижняя граница) и upper_date (верхняя) ---
        # Приоритет: date_from > days_limit
        if params.date_from is not None:
            cutoff_date: Optional[datetime] = ensure_aware_utc(params.date_from)
        elif 0 < params.days_limit < DAYS_LIMIT_ALL_TIME:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=params.days_limit)
        else:
            cutoff_date = None

        upper_date: Optional[datetime] = (
            ensure_aware_utc(params.date_to) if params.date_to is not None else None
        )

        # Period label для имени DOCX
        if cutoff_date and upper_date:
            period_label = (
                f"{cutoff_date.strftime('%Y-%m-%d')}_to_{upper_date.strftime('%Y-%m-%d')}"
            )
        elif cutoff_date:
            now = datetime.now(timezone.utc)
            period_label = f"{cutoff_date.strftime('%Y-%m-%d')}_to_{now.strftime('%Y-%m-%d')}"
        else:
            period_label = "fullchat"

        # ── Диагностика дат ──────────────────────────────────────────────
        self._log(
            f"[DIAG DATE] date_from={params.date_from!r} "
            f"({type(params.date_from).__name__}), "
            f"date_to={params.date_to!r} ({type(params.date_to).__name__}), "
            f"days_limit={params.days_limit}"
        )
        self._log(
            f"[DIAG DATE] cutoff_date={cutoff_date!r} "
            f"({type(cutoff_date).__name__}), "
            f"upper_date={upper_date!r} ({type(upper_date).__name__})"
        )
        logger.info(
            "parser DATE diag: cutoff=%s upper=%s date_from=%r date_to=%r days=%s",
            cutoff_date, upper_date, params.date_from, params.date_to, params.days_limit
        )
        # ─────────────────────────────────────────────────────────────────

        depth_label = "за всё время" if cutoff_date is None else f"с {cutoff_date.strftime('%Y-%m-%d')}"
        self._log(f"📅 Глубина: {depth_label}")
        if params.topic_id:
            self._log(f"📁 Топик ID: {params.topic_id}")
        if params.user_ids:
            self._log(f"👤 Фильтр по участникам: {len(params.user_ids)} чел.")

        # --- Проверка simpleeval при наличии filter_expression ---
        if params.filter_expression and not _SIMPLEEVAL_OK:
            self._log(
                "⚠️  filter_expression задан, но simpleeval не установлен — "
                "фильтр игнорируется. Установите: pip install simpleeval"
            )

        # --- Выбор функции пакетной вставки ---
        # re_download=True  → INSERT OR REPLACE (перезаписываем всё)
        # re_download=False → INSERT OR IGNORE  (пропускаем дубли, не трогаем merge-поля)
        insert_fn = (
            self._db.insert_messages_batch if params.re_download
            else self._db.upsert_messages_batch
        )

        # --- DownloadTracker — инкрементальный режим ---
        # Трекер отключается если задан диапазон дат: сообщения, уже
        # находящиеся в БД, должны быть доступны через фильтр дат в БД, а не
        # через трекер (иначе «скачанные» записи молча пропускаются при смене периода).
        use_tracker: bool = (
            not params.re_download
            and params.date_from is None
            and params.date_to is None
        )
        tracker = DownloadTracker(params.output_dir, chat_title, normalized_id)
        if params.re_download:
            tracker.clear()
            self._log("♻️  Режим перезагрузки: трекер сброшен, начинаем заново")
        elif not use_tracker:
            self._log("📅 Задан диапазон дат — инкрементальный трекер отключён")
        elif tracker.count > 0:
            self._log(f"📋 Инкрементальный режим: {tracker.count} сообщений уже скачано, пропускаем")

        # --- Быстрый count для прогресс-бара (без двойного прохода) ---
        total_est = 0
        logger.debug("[DIAG] get_messages(limit=1) start")
        self._log("[DIAG] подсчёт сообщений (limit=1)...")
        try:
            history = await self._client.get_messages(entity, limit=1)
            total_est = getattr(history, "total", 0) or 0
        except Exception as _count_exc:
            logger.debug("[DIAG] get_messages count failed: %s", _count_exc)
        logger.debug("[DIAG] total_est=%d", total_est)
        self._log(f"[DIAG] total_est={total_est}")
        self._progress_cb(5)

        # --- Форум: список всех топиков для итерации ---
        # Если выбран форум без конкретного topic_id — парсим все ветки.
        _topics_map: Dict[int, str] = {}
        if chat_type == "forum" and params.topic_id is None:
            from features.chats.api import ChatsService
            _chats_svc = ChatsService(self._client)
            _topics_map = await _chats_svc.get_topics(normalized_id, log=self._log)
            if _topics_map:
                _topics_to_parse: List[Optional[int]] = list(_topics_map.keys())
                self._log(f"📋 Форум: найдено {len(_topics_to_parse)} топиков — парсим все")
                logger.info("parser: forum mode — %d topics to iterate", len(_topics_to_parse))
            else:
                _topics_to_parse = [None]
                self._log("⚠️ Топики форума не получены — парсим без фильтра по топику")
        else:
            _topics_to_parse = [params.topic_id]

        # --- Итерация по сообщениям ---
        posts_with_comments: Dict[int, int] = {}  # {post_id: replies_count}
        _batch: List[dict] = []

        async def _run_topics() -> None:
            for _topic_id in _topics_to_parse:
                if len(_topics_to_parse) > 1:
                    _topic_title = _topics_map.get(_topic_id, f"#{_topic_id}")
                    self._log(f"📁 Топик: «{_topic_title}» (id={_topic_id})")

                self._log(f"🔍 Начинаем сбор из: {chat_title}")
                logger.debug("[DIAG] _iter_one_topic start: topic_id=%s", _topic_id)
                self._log(f"[DIAG] iter_one_topic → topic_id={_topic_id}")
                await self._iter_one_topic(
                    entity              = entity,
                    topic_id            = _topic_id,
                    params              = params,
                    normalized_id       = normalized_id,
                    cutoff_date         = cutoff_date,
                    upper_date          = upper_date,
                    total_est           = total_est,
                    insert_fn           = insert_fn,
                    tracker             = tracker,
                    use_tracker         = use_tracker,
                    errors              = errors,
                    posts_with_comments = posts_with_comments,
                    linked_chat_id      = linked_chat_id,
                    chat_type           = chat_type,
                    batch               = _batch,
                )
                logger.debug("[DIAG] _iter_one_topic done: topic_id=%s msgs_so_far=%d", _topic_id, self._msg_count)
                self._log(f"[DIAG] iter_one_topic done: topic_id={_topic_id} msgs={self._msg_count}")

        if params.use_takeout:
            self._log("📦 Режим Takeout API (отдельные лимиты Telegram)...")
            # Завершаем висящую takeout-сессию если она осталась от предыдущего запуска
            try:
                from telethon.tl.functions.account import FinishTakeoutSessionRequest
                await self._client(FinishTakeoutSessionRequest(success=False))
                logger.debug("parser: старая takeout-сессия завершена")
            except Exception:
                pass  # нет висящей сессии — нормально
            try:
                async with self._client.takeout(
                    contacts=False,
                    users=False,
                    chats=False,
                    megagroups=True,
                    channels=True,
                    files=bool(params.media_filter),
                    max_file_size=None,
                ) as takeout_client:
                    # В режиме takeout подменяем клиент только для итерации
                    _original_client = self._client
                    self._client = takeout_client
                    try:
                        await _run_topics()
                    finally:
                        self._client = _original_client
                self._log("✅ Takeout сессия завершена")
            except Exception as exc:
                self._log(f"⚠️ Takeout недоступен: {exc} — переключаюсь на обычный режим")
                logger.warning("parser: takeout failed, falling back: %s", exc)
                await _run_topics()
        else:
            await _run_topics()

        # Финальный flush остатка батча в БД
        if _batch:
            insert_fn(_batch)
            _batch.clear()

        # Сброс трекера в файл — одна запись вместо N × open/write/close в event loop
        tracker.save()

        self._log(f"✅ Сбор завершён: {self._msg_count} сообщений")

        # --- Скачиваем комментарии к постам ---
        if posts_with_comments and linked_chat_id:
            self._log(f"💬 Найдено постов с комментариями: {len(posts_with_comments)}")
            self._log(f"💬 Скачиваем комментарии из группы {linked_chat_id}...")

            for post_id, replies_count in posts_with_comments.items():
                self._log(f"  🔍 Пост #{post_id} ({replies_count} комментариев)...")
                try:
                    downloaded = await self._get_post_replies(
                        channel_id     = normalized_id,
                        post_id        = post_id,
                        linked_chat_id = linked_chat_id,
                        media_filter   = params.media_filter,
                        topic_id       = params.topic_id,
                        insert_fn      = insert_fn,
                        user_ids       = params.user_ids,
                    )
                    self._comment_count += downloaded
                    self._msg_count     += downloaded
                    if downloaded:
                        self._log(f"    ✅ Скачано {downloaded} комментариев")
                except Exception as exc:
                    err = f"Ошибка загрузки комментариев к посту {post_id}: {exc}"
                    self._log(f"    ❌ {err}")
                    logger.warning("parser: %s", err)
                    errors.append(err)

        self._progress_cb(100)
        logger.info(
            "parser: collect_data done: msgs=%d comments=%d media=%d errors=%d",
            self._msg_count, self._comment_count, self._media_count, len(errors),
        )

        return CollectResult(
            success        = True,
            chat_id        = normalized_id,
            chat_title     = chat_title,
            messages_count = self._msg_count,
            comments_count = self._comment_count,
            media_count    = self._media_count,
            period_label   = period_label,
            errors         = errors,
        )

    # ------------------------------------------------------------------
    # 2. Итерация сообщений одного топика (с FloodWait retry)
    # ------------------------------------------------------------------

    async def _iter_one_topic(
        self,
        entity,
        topic_id:            Optional[int],
        params:              CollectParams,
        normalized_id:       int,
        cutoff_date:         Optional[datetime],
        upper_date:          Optional[datetime],
        total_est:           int,
        insert_fn:           Callable,
        tracker:             DownloadTracker,
        use_tracker:         bool,
        errors:              List[str],
        posts_with_comments: Dict[int, int],
        linked_chat_id:      Optional[int],
        chat_type:           str,
        batch:               List[dict],
    ) -> None:
        """
        Итерирует сообщения одного топика (или всего чата если topic_id=None).

        Вызывается из collect_data в цикле по топикам форума.
        Состояние между вызовами не хранит — все мутабельные коллекции
        (batch, errors, posts_with_comments) передаются по ссылке и
        пополняются in-place.

        Args:
            entity:              Telethon-сущность чата.
            topic_id:            ID топика форума (None = общее пространство).
            params:              Параметры парсинга из ParseWorker.
            normalized_id:       Нормализованный chat_id.
            cutoff_date:         Нижняя граница дат (None = без ограничений).
            upper_date:          Верхняя граница дат (None = без ограничений).
            total_est:           Оценка общего числа сообщений для прогресс-бара.
            insert_fn:           Функция пакетной вставки (insert или upsert).
            tracker:             DownloadTracker для инкрементального режима.
            errors:              Список некритических ошибок (пополняется in-place).
            posts_with_comments: Накопитель post_id → replies_count (in-place).
            linked_chat_id:      ID linked группы (для каналов с комментариями).
            chat_type:           "channel" | "forum" | "group" | "private".
            batch:               Общий буфер строк для batch-insert (in-place).
        """
        last_message_id: Optional[int] = None
        attempts = 0
        _pending: list[tuple[int, asyncio.Task]] = []
        _iter_msg_count = 0  # счётчик внутри этого топика (для [DIAG])
        _batch_t_start = time.perf_counter()  # момент начала текущего батча

        while attempts <= _MAX_RETRIES:
            try:
                _max_id_arg = last_message_id - 1 if last_message_id else 0
                # ── Диагностика перед стартом итерации ───────────────────
                self._log(
                    f"[DIAG ITER] entity={getattr(entity, 'id', entity)} "
                    f"topic={topic_id} max_id={_max_id_arg} "
                    f"cutoff={cutoff_date} upper={upper_date} attempt={attempts}"
                )
                # ─────────────────────────────────────────────────────────
                logger.debug(
                    "[DIAG] iter_messages call: entity=%s topic_id=%s max_id=%s attempt=%d",
                    getattr(entity, 'id', entity), topic_id, _max_id_arg, attempts,
                )
                self._log(
                    f"[DIAG] iter_messages → entity={getattr(entity, 'id', '?')} "
                    f"topic_id={topic_id} max_id={_max_id_arg} attempt={attempts}"
                )
                async for message in self._client.iter_messages(
                    entity,
                    reply_to=topic_id,
                    min_id=0,
                    # Продолжаем с последнего известного ID при рестарте после FloodWait
                    max_id=_max_id_arg,
                    reverse=False,
                ):
                    last_message_id = message.id
                    _iter_msg_count += 1
                    if _iter_msg_count == 1:
                        logger.debug("[DIAG] first message from iter: id=%d date=%s", message.id, message.date)
                        self._log(f"[DIAG] первое сообщение: id={message.id} date={message.date}")
                        _batch_t_start = time.perf_counter()

                    # Вычисляем дату один раз
                    msg_date = ensure_aware_utc(message.date) if message.date else None

                    # ── Диагностика: каждые 50 сообщений + первые три ────
                    if _iter_msg_count <= 3 or _iter_msg_count % 50 == 0:
                        self._log(
                            f"[DIAG MSG] #{_iter_msg_count} id={message.id} "
                            f"date={msg_date} "
                            f"upper_ok={upper_date is None or (msg_date is not None and msg_date <= upper_date)} "
                            f"lower_ok={cutoff_date is None or (msg_date is not None and msg_date >= cutoff_date)}"
                        )
                    # ─────────────────────────────────────────────────────

                    # Фильтр верхней даты (пропускаем слишком новые)
                    if upper_date and msg_date and msg_date > upper_date:
                        if _iter_msg_count <= 5:
                            self._log(
                                f"[DIAG SKIP upper] id={message.id} "
                                f"msg_date={msg_date} > upper_date={upper_date}"
                            )
                        continue

                    # Фильтр нижней даты (iter_messages идёт от новых к старым)
                    if cutoff_date is not None and msg_date and msg_date < cutoff_date:
                        # Flush перед выходом — задачи уже созданы, ждём их
                        if _pending:
                            await self._flush_tasks(
                                _pending, batch, errors, tracker, total_est
                            )
                            _pending.clear()
                        break  # дальше только более старые — выходим

                    # Фильтр по пользователю
                    if params.user_ids and message.sender_id not in params.user_ids:
                        continue

                    # Инкрементальный режим: пропускаем уже скачанные
                    if use_tracker and tracker.is_downloaded(message.id):
                        continue

                    # Фильтр выражений (simpleeval) — до создания задачи
                    if (params.filter_expression and _SIMPLEEVAL_OK
                            and not self._eval_filter(message, params.filter_expression)):
                        continue

                    # Запоминаем посты с комментариями (sync — читаем атрибуты до task)
                    if (params.download_comments
                            and linked_chat_id
                            and chat_type == "channel"
                            and message.replies
                            and message.replies.replies > 0):
                        posts_with_comments[message.id] = message.replies.replies

                    # Определяем, требуется ли скачивание медиа для этого сообщения
                    needs_download = (
                        params.media_filter is not None
                        and self._should_download(message, params.media_filter)
                    )

                    if needs_download:
                        # Медиа-сообщение: асинхронная задача (download + извлечение полей)
                        task = asyncio.create_task(
                            self._process_message(
                                message      = message,
                                chat_id      = normalized_id,
                                topic_id     = topic_id,
                                media_filter = params.media_filter,
                            )
                        )
                        _pending.append((message.id, task))

                        # Gather-пакет медиа-задач
                        if len(_pending) >= _TASK_BATCH_SIZE:
                            await self._flush_tasks(
                                _pending, batch, errors, tracker, total_est
                            )
                            _pending.clear()
                    else:
                        # Быстрый путь: текстовое сообщение, нет I/O — inline
                        row = self._extract_row_sync(message, normalized_id, topic_id)
                        batch.append(row)
                        tracker.mark_downloaded(message.id)
                        self._msg_count += 1
                        if self._msg_count % MESSAGES_LOG_INTERVAL == 0:
                            self._log(f"📨 Обработано сообщений: {self._msg_count}")
                            if total_est:
                                pct = 5 + int(self._msg_count / total_est * 85)
                                self._progress_cb(min(pct, 90))

                        # Периодический flush в БД — каждые _DB_BATCH_SIZE сообщений.
                        if len(batch) >= _DB_BATCH_SIZE:
                            insert_fn(batch)
                            batch.clear()
                            tracker.save()

                    # ── Адаптивная пауза между батчами ───────────────────────
                    # Пауза делается между батчами (каждые _ADAPTIVE_BATCH_SIZE сообщений),
                    # а не между отдельными сообщениями. Это соответствует тому как работает
                    # MTProto: 100 сообщений = 1 запрос getHistory. Пауза адаптируется под
                    # скорость ответа сервера — не давим если сервер уже тормозит.
                    # Источник: telethon_2026_report.md, раздел 4.1
                    if _iter_msg_count % _ADAPTIVE_BATCH_SIZE == 0:
                        elapsed = time.perf_counter() - _batch_t_start
                        if elapsed < 0.5:
                            wait = 0.3        # сервер отвечает быстро — небольшая пауза
                        elif elapsed < 2.0:
                            wait = 0.7        # умеренно
                        else:
                            wait = elapsed * 0.5  # сервер тормозит — не давим
                        logger.debug(
                            "parser: adaptive pause %.2fs (batch elapsed=%.2fs)",
                            wait, elapsed,
                        )
                        await asyncio.sleep(wait)
                        _batch_t_start = time.perf_counter()

                # Flush оставшихся медиа-задач после завершения итератора
                if _pending:
                    await self._flush_tasks(
                        _pending, batch, errors, tracker, total_est
                    )
                    _pending.clear()

                # Цикл завершился нормально — выходим из while
                break

            except TelethonFloodWaitError as exc:
                # Дожидаемся уже запущенных задач перед паузой
                if _pending:
                    await self._flush_tasks(
                        _pending, batch, errors, tracker, total_est
                    )
                    _pending.clear()
                wait = exc.seconds + _FLOOD_BUFFER
                self._log(f"⏳ FloodWait: пауза {wait} сек...")
                logger.warning("parser: FloodWait %ds during iter_messages", exc.seconds)
                await asyncio.sleep(wait)
                attempts += 1
                # last_message_id сохранён → рестартуем итератор с нужного места

            except BadRequestError as exc:
                if _pending:
                    await self._flush_tasks(
                        _pending, batch, errors, tracker, total_est
                    )
                    _pending.clear()
                if "TOPIC_ID_INVALID" in str(exc):
                    logger.warning(
                        "parser: топик id=%s не существует (TOPIC_ID_INVALID) — пропускаем",
                        topic_id,
                    )
                    self._log(f"⚠️ Топик id={topic_id} не существует (TOPIC_ID_INVALID) — пропускаем")
                    return  # пропустить этот топик, collect_data продолжит следующий
                raise  # остальные BadRequestError — пробрасывать дальше

            except OSError as exc:
                if _pending:
                    await self._flush_tasks(
                        _pending, batch, errors, tracker, total_est
                    )
                    _pending.clear()
                if attempts >= _MAX_RETRIES:
                    raise TelegramError(
                        f"Сетевая ошибка после {_MAX_RETRIES} попыток: {exc}"
                    ) from exc
                delay = _RETRY_BASE_DELAY * (attempts + 1)
                self._log(f"⚠️ Сетевая ошибка: {exc}. Повтор через {delay:.0f} сек...")
                logger.warning("parser: network error (%s), retry %d", exc, attempts + 1)
                await asyncio.sleep(delay)
                attempts += 1

    # ------------------------------------------------------------------
    # 3. Gather-пакет задач + запись результатов в batch / tracker
    # ------------------------------------------------------------------

    async def _flush_tasks(
        self,
        pending:   list[tuple[int, asyncio.Task]],
        batch:     List[dict],
        errors:    List[str],
        tracker:   DownloadTracker,
        total_est: int,
    ) -> None:
        """
        Ожидает завершения всех задач в pending через asyncio.gather(),
        записывает row-дикты в batch, обновляет tracker и счётчики.

        Args:
            pending:   Список (message_id, Task) — порядок соответствует gather().
            batch:     Аккумулятор строк для insert_messages_batch().
            errors:    Список некритических ошибок (пополняется in-place).
            tracker:   DownloadTracker — mark_downloaded() при успехе.
            total_est: Оценка общего числа сообщений для прогресс-бара.
        """
        if not pending:
            return

        tasks   = [t for _, t in pending]
        first_id = pending[0][0]
        last_id  = pending[-1][0]
        self._log(f"⬇️  Батч медиа: {len(tasks)} файлов (id {first_id}–{last_id})...")
        logger.debug("[DIAG] gather start: %d tasks", len(tasks))
        # 7200 сек (2 часа) — батч из 20 задач может содержать несколько больших видео.
        # Каждому видео даётся до ~2 часов своего таймаута (PATCH A),
        # поэтому батч должен ждать не меньше.
        try:
            results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=7200.0,
            )
        except asyncio.TimeoutError:
            logger.error(
                "[DIAG] _flush_tasks TIMEOUT: %d задач зависли, принудительно пропускаем",
                len(tasks),
            )
            results = [TimeoutError(f"download_media timeout (batch of {len(tasks)})")] * len(tasks)
        logger.debug("[DIAG] gather done: %d results", len(results))

        for (msg_id, _), result in zip(pending, results):
            if isinstance(result, BaseException):
                err = f"Ошибка обработки msg_id={msg_id}: {result}"
                errors.append(err)
                logger.warning("parser: task error %s", err)
            else:
                row, media_err = result
                if media_err:
                    errors.append(media_err)
                if row:
                    batch.append(row)
                    tracker.mark_downloaded(msg_id)

            self._msg_count += 1
            if self._msg_count % MESSAGES_LOG_INTERVAL == 0:
                self._log(f"📨 Обработано сообщений: {self._msg_count}")

        # Обновляем прогресс после каждого батча (не ждём MESSAGES_LOG_INTERVAL)
        if total_est:
            pct = 5 + int(self._msg_count / total_est * 85)
            self._progress_cb(min(pct, 90))
        ok = sum(1 for r in results if not isinstance(r, BaseException))
        self._log(f"   ✅ Батч завершён: {ok}/{len(tasks)} файлов")

    # ------------------------------------------------------------------
    # 3. Обработка одного сообщения
    # ------------------------------------------------------------------

    async def _process_message(
        self,
        message:      Message,
        chat_id:      int,
        topic_id:     Optional[int],
        media_filter: Optional[List[str]],
        post_id:      Optional[int] = None,
        is_comment:   bool          = False,
        from_linked:  bool          = False,
    ) -> tuple[Optional[dict], Optional[str]]:
        """
        Обрабатывает одно сообщение: извлекает поля и скачивает медиа.

        НЕ сохраняет в БД — возвращает row dict для batch insert в collect_data.

        Args:
            message:      Telethon Message объект.
            chat_id:      Нормализованный ID чата.
            topic_id:     ID топика форума или None.
            media_filter: Список ключей медиа для скачивания (None = не скачивать).
            post_id:      ID поста-родителя (для комментариев).
            is_comment:   True если это комментарий к посту.
            from_linked:  True если сообщение из linked группы.

        Returns:
            (row_dict, media_error_str) — row_dict готов к insert_messages_batch(),
            media_error_str — описание ошибки скачивания или None.
        """
        sender_name = self._get_sender_name(message)
        date_str    = message.date.strftime("%Y-%m-%d %H:%M:%S") if message.date else ""
        text        = message.text or ""

        # reply_to_msg_id
        reply_to_msg_id: Optional[int] = None
        if message.reply_to:
            reply_to_msg_id = getattr(message.reply_to, "reply_to_msg_id", None)

        # topic_id из сообщения (если не задан явно через параметр)
        effective_topic_id = topic_id or self._extract_topic_id(message)

        # Медиа
        media_path: Optional[str] = None
        media_type: Optional[str] = None
        file_size:  Optional[int] = None
        media_error: Optional[str] = None

        if media_filter is not None and self._should_download(message, media_filter):
            media_type = self._detect_media_type(message)
            media_dir  = self._build_media_dir(media_type)   # подпапка по типу
            os.makedirs(media_dir, exist_ok=True)

            filename = f"{chat_id}_{message.id}_{int(message.date.timestamp())}"
            target   = os.path.join(media_dir, filename)

            try:
                media_path = await self._download_media(message, target)
                if media_path and os.path.exists(media_path):
                    file_size = os.path.getsize(media_path)
                    self._media_count += 1
            except (OSError, RPCError) as exc:
                media_error = (
                    f"Медиа msg_id={message.id} не скачано после {_MAX_RETRIES} попыток: {exc}"
                )
                logger.warning("parser: %s", media_error)

        row = {
            "chat_id":           chat_id,
            "message_id":        message.id,
            "topic_id":          effective_topic_id,
            "user_id":           message.sender_id,
            "username":          sender_name,
            "date":              date_str,
            "text":              text,
            "media_path":        media_path,
            "file_type":         media_type,
            "file_size":         file_size,
            "reply_to_msg_id":   reply_to_msg_id,
            "post_id":           post_id,
            "is_comment":        1 if is_comment else 0,
            "from_linked_group": 1 if from_linked else 0,
        }
        logger.debug("parser: processed msg %d (chat=%d)", message.id, chat_id)
        return row, media_error

    # ------------------------------------------------------------------
    # 3. Скачивание медиа (с FloodWait retry)
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # 2b. Инициализация TeleGet (lazy, один раз на экземпляр)
    # ------------------------------------------------------------------

    async def _init_teleget(self) -> object:
        """
        Лениво инициализирует TeleGet Downloader и возвращает его.

        TeleGet API (teleget9527):
            from teleget import Downloader
            dl = Downloader(client)
            await dl.start()           # запускает внутренние воркеры (опционально)
            path = await dl.download(message, save_path=target_path)

        Returns:
            Объект Downloader если инициализация прошла успешно, иначе None.
        """
        if self._teleget_downloader is not None:
            # False означает «библиотека недоступна» — не пытаемся повторно
            return self._teleget_downloader if self._teleget_downloader is not False else None

        try:
            from teleget import Downloader  # type: ignore[import]
            dl = Downloader(self._client)
            # Некоторые версии TeleGet требуют явного start()
            if hasattr(dl, "start") and asyncio.iscoroutinefunction(dl.start):
                await dl.start()
            self._teleget_downloader = dl
            logger.info(
                "parser: TeleGet Downloader инициализирован (порог >= %d МБ)",
                _TELEGET_THRESHOLD_BYTES // (1024 * 1024),
            )
            return dl
        except ImportError:
            self._teleget_downloader = False  # type: ignore[assignment]
            logger.warning(
                "parser: teleget9527 не установлен — "
                "для больших файлов используется стандартный download_media. "
                "Установите: pip install teleget9527[all]"
            )
            return None
        except Exception as exc:
            self._teleget_downloader = False  # type: ignore[assignment]
            logger.warning(
                "parser: TeleGet init failed: %s — fallback to download_media", exc
            )
            return None

    async def _teleget_download_file(
        self,
        message:     "Message",
        target_path: str,
        file_size:   int,
    ) -> "Optional[str]":
        """
        Скачивает файл через TeleGet с поддержкой докачки.

        Не удаляет частичные файлы при ошибке — TeleGet возобновит
        с того же места при следующем вызове с тем же target_path.

        Args:
            message:     Telethon Message с медиа.
            target_path: Желаемый путь (TeleGet использует его как base name).
            file_size:   Размер файла в байтах (для логов).

        Returns:
            Реальный путь к скачанному файлу или None (вызывающий выполнит fallback).
        """
        dl = await self._init_teleget()
        if dl is None:
            return None

        mb = file_size // (1024 * 1024)
        self._log(
            f"⬇️  TeleGet: скачивание {mb} МБ "
            f"(msg_id={message.id}, таймаут {int(_TELEGET_MAX_TIMEOUT // 3600)} ч)"
        )
        logger.info(
            "parser: TeleGet download start: msg_id=%d size=%d bytes path=%s",
            message.id, file_size, target_path,
        )

        # TeleGet API: Downloader.download(message, save_path=…)
        # Если ваша версия библиотеки использует другой ключ аргумента —
        # замените save_path= на file= или path= в строке ниже:
        try:
            result = await asyncio.wait_for(
                dl.download(message, save_path=target_path),
                timeout=_TELEGET_MAX_TIMEOUT,
            )
            logger.info(
                "parser: TeleGet download done: msg_id=%d -> %s",
                message.id, result,
            )
            self._log(
                f"✅ TeleGet: сохранён -> {os.path.basename(str(result or target_path))}"
            )
            return result or target_path
        except asyncio.TimeoutError:
            logger.error(
                "parser: TeleGet timeout (%.0f ч) msg_id=%d — "
                "частичный файл НЕ удалён, докачка при следующем запуске",
                _TELEGET_MAX_TIMEOUT / 3600, message.id,
            )
            self._log(
                f"⚠️  TeleGet: таймаут {int(_TELEGET_MAX_TIMEOUT // 3600)} ч "
                f"(msg_id={message.id}) — частичный файл сохранён для докачки"
            )
            return None
        except Exception as exc:
            logger.warning(
                "parser: TeleGet error msg_id=%d: %s — "
                "частичный файл НЕ удалён, fallback на download_media",
                message.id, exc,
            )
            self._log(f"⚠️  TeleGet ошибка (msg_id={message.id}): {exc} — fallback")
            return None

    @async_retry(
        max_attempts = _MAX_RETRIES,
        base_delay   = _RETRY_BASE_DELAY,
        backoff      = 2.0,
        exc_retry    = (OSError, RPCError),
        flood_cls    = TelethonFloodWaitError,
        flood_buffer = _FLOOD_BUFFER,
    )
    async def _download_media(
        self,
        message:     Message,
        target_path: str,
    ) -> Optional[str]:
        """
        Скачивает медиа сообщения на диск.

        Стратегия выбора пути загрузки
        ──────────────────────────────
        • Файл < _TELEGET_THRESHOLD_BYTES (50 МБ):
              Telethon download_media + потоковая запись на диск.
              Таймаут динамический: max(600 с, size / 512 КБ/с + 120 с).
        • Файл >= _TELEGET_THRESHOLD_BYTES:
              1) TeleGet (_teleget_download_file) — докачка, FILE_REFERENCE_EXPIRED,
                 многопоточность внутри одного asyncio-потока.
              2) Если TeleGet недоступен или вернул ошибку — fallback на Telethon.
        • Частичные файлы НЕ удаляются ни в каком сценарии:
              TeleGet продолжит докачку при следующем вызове с тем же путём;
              Telethon перезапишет файл поверх при следующей попытке.

        Retry-логика (декоратор @async_retry):
            FloodWait → sleep(seconds + _FLOOD_BUFFER), не считается попыткой.
            OSError / RPCError → экспоненциальный backoff, макс. _MAX_RETRIES раз.
            После исчерпания попыток → re-raise последнего исключения.

        Args:
            message:     Telethon Message с медиа.
            target_path: Путь без расширения (Telethon добавит .jpg/.mp4/...).

        Returns:
            Реальный путь к скачанному файлу (с расширением) или None.

        Raises:
            OSError | RPCError: после _MAX_RETRIES неудачных попыток.
        """
        # ── Определяем размер файла ──────────────────────────────────────────
        _file_size: int = 0
        if hasattr(message.media, "document") and message.media.document:
            _file_size = getattr(message.media.document, "size", 0) or 0
        # Фото — всегда маленькие, динамический таймаут покроет

        logger.debug(
            "[DIAG] download_media start: msg_id=%s media=%s path=%s size=%d",
            message.id, type(message.media).__name__, target_path, _file_size,
        )

        # ── Диагностика размера и порога TeleGet ─────────────────────────────
        self._log(
            f"[DIAG] file_size={_file_size} bytes "
            f"({_file_size // (1024*1024)} МБ), "
            f"threshold={_TELEGET_THRESHOLD_BYTES // (1024*1024)} МБ, "
            f"use_teleget={_file_size >= _TELEGET_THRESHOLD_BYTES}"
        )
        # ─────────────────────────────────────────────────────────────────────

        async with self._sem:
            # ── Путь 1: TeleGet для больших файлов ───────────────────────────
            if _file_size >= _TELEGET_THRESHOLD_BYTES:
                result = await self._teleget_download_file(
                    message, target_path, _file_size
                )
                if result is not None:
                    logger.debug(
                        "[DIAG] download_media via TeleGet OK: msg_id=%s -> %s",
                        message.id, result,
                    )
                    return result
                # TeleGet вернул None (недоступен или ошибка) → fallback ниже
                logger.debug(
                    "[DIAG] TeleGet fallback -> download_media: msg_id=%s", message.id
                )
                self._log(
                    f"⬇️  Telethon fallback: {_file_size // (1024*1024)} МБ "
                    f"(msg_id={message.id})"
                )

            # ── Путь 2: Telethon download_media (малые файлы + fallback) ─────
            # Динамический таймаут: 2 сек/МБ + 2 мин запаса, минимум 600 с
            _timeout: float = max(600.0, _file_size / (512 * 1024) + 120.0)
            logger.debug(
                "[DIAG] download_media (telethon): msg_id=%s size=%d timeout=%.0fs",
                message.id, _file_size, _timeout,
            )
            try:
                result = await asyncio.wait_for(
                    message.download_media(file=target_path),
                    timeout=_timeout,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "[DIAG] download_media timeout: msg_id=%s size=%d timeout=%.0fs "
                    "— частичный файл НЕ удалён",
                    message.id, _file_size, _timeout,
                )
                # Частичный файл НЕ удаляем — Telethon перезапишет при retry
                return None

        logger.debug(
            "[DIAG] download_media done (telethon): msg_id=%s -> %s",
            message.id, result,
        )
        return result


    # ------------------------------------------------------------------
    # 4. Комментарии к посту
    # ------------------------------------------------------------------

    async def _get_post_replies(
        self,
        channel_id:     int,
        post_id:        int,
        linked_chat_id: int,
        media_filter:   Optional[List[str]],
        topic_id:       Optional[int]      = None,
        limit:          int                = MAX_COMMENT_LIMIT,
        insert_fn:      Optional[Callable] = None,
        user_ids:       Optional[List[int]] = None,
    ) -> int:
        """
        Скачивает комментарии к посту из linked discussion группы.

        Комментарии хранятся в linked группе как reply_to=post_id.
        Сохраняются в БД с chat_id=channel_id (привязаны к каналу),
        is_comment=1, post_id=post_id.

        Args:
            channel_id:     ID основного канала (для сохранения в БД).
            post_id:        ID поста в канале.
            linked_chat_id: ID linked группы комментариев (AS IS из Telethon).
            media_filter:   Фильтр медиа (None = не скачивать).
            topic_id:       ID топика (передаётся в insert_message).
            limit:          Максимальное число комментариев.
            insert_fn:      Функция пакетной вставки (insert_messages_batch или
                            upsert_messages_batch). По умолчанию insert_messages_batch.

        Returns:
            Количество сохранённых комментариев.
        """
        _insert = insert_fn or self._db.insert_messages_batch
        count = 0
        attempts = 0
        comment_batch: List[dict] = []

        while attempts <= _MAX_RETRIES:
            try:
                async for comment in self._client.iter_messages(
                    linked_chat_id,
                    reply_to=post_id,
                    limit=limit,
                ):
                    row, media_err = await self._process_message(
                        message      = comment,
                        chat_id      = channel_id,   # привязываем к каналу
                        topic_id     = topic_id,
                        media_filter = media_filter,
                        post_id      = post_id,
                        is_comment   = True,
                        from_linked  = True,
                    )
                    if media_err:
                        logger.debug("parser: comment media err: %s", media_err)
                    if row:
                        comment_batch.append(row)
                    count += 1

                # Batch flush всех комментариев поста
                if comment_batch:
                    _insert(comment_batch)
                break   # успешно завершили итерацию

            except TelethonFloodWaitError as exc:
                wait = exc.seconds + _FLOOD_BUFFER
                self._log(
                    f"⏳ FloodWait при загрузке комментариев поста #{post_id}: {wait} сек..."
                )
                logger.warning(
                    "parser: FloodWait %ds on get_post_replies post_id=%s",
                    exc.seconds, post_id,
                )
                await asyncio.sleep(wait)
                comment_batch.clear()
                attempts += 1

            except Exception as exc:
                logger.warning(
                    "parser: get_post_replies error post_id=%s: %s", post_id, exc
                )
                raise  # CR-3: пробрасываем — collect_data добавит в errors и продолжит

        return count

    # ------------------------------------------------------------------
    # 5. Вспомогательные методы
    # ------------------------------------------------------------------

    @staticmethod
    def _should_download(message: Message, media_filter: List[str]) -> bool:
        """
        Определяет, нужно ли скачивать медиа из сообщения.

        Args:
            message:      Telethon Message.
            media_filter: Список ключей: "photo", "video", "videomessage",
                          "voice", "file". Пустой список → скачивать всё.

        Returns:
            True если медиа есть и оно попадает под фильтр.
        """
        if not message.media:
            return False

        # Пустой фильтр = скачивать всё
        if not media_filter:
            return True

        if isinstance(message.media, MessageMediaPhoto):
            return "photo" in media_filter

        if isinstance(message.media, MessageMediaDocument):
            doc   = message.media.document
            attrs = doc.attributes

            # Видео (обычное или кружочек)
            video_attrs = [a for a in attrs if isinstance(a, DocumentAttributeVideo)]
            if video_attrs:
                is_round = any(getattr(a, "round_message", False) for a in video_attrs)
                return "videomessage" in media_filter if is_round else "video" in media_filter

            # Голосовое сообщение
            if any(isinstance(a, DocumentAttributeAudio) and getattr(a, "voice", False)
                   for a in attrs):
                return "voice" in media_filter

            # Прочие файлы (документы)
            return "file" in media_filter

        return False

    @staticmethod
    def _detect_media_type(message: Message) -> Optional[str]:
        """
        Возвращает строковый тип медиа для сохранения в поле file_type БД.

        Returns:
            "photo" | "video" | "videomessage" | "voice" | "file" | None
        """
        if not message.media:
            return None

        if isinstance(message.media, MessageMediaPhoto):
            return "photo"

        if isinstance(message.media, MessageMediaDocument):
            doc   = message.media.document
            attrs = doc.attributes

            video_attrs = [a for a in attrs if isinstance(a, DocumentAttributeVideo)]
            if video_attrs:
                is_round = any(getattr(a, "round_message", False) for a in video_attrs)
                return "videomessage" if is_round else "video"

            if any(isinstance(a, DocumentAttributeAudio) and getattr(a, "voice", False)
                   for a in attrs):
                return "voice"

            return "file"

        return None

    @staticmethod
    def _extract_topic_id(message: Message) -> Optional[int]:
        """
        Определяет ID топика форума из полей reply_to сообщения.

        Логика (из оригинального backend.py, без изменений):
            1. reply_to.reply_to_top_id — явный ID топика-родителя
            2. reply_to.reply_to_msg_id — стартовое сообщение топика
            3. forum_topic=True + message.id — само стартовое сообщение

        Returns:
            ID топика или None.
        """
        reply_to = getattr(message, "reply_to", None)
        if reply_to:
            top_id = getattr(reply_to, "reply_to_top_id", None)
            if top_id:
                return top_id
            reply_msg_id = getattr(reply_to, "reply_to_msg_id", None)
            if reply_msg_id:
                return reply_msg_id

        if getattr(message, "forum_topic", False):
            return getattr(message, "id", None)

        return None

    @staticmethod
    def _get_sender_name(message: Message) -> str:
        """
        Извлекает отображаемое имя отправителя из Telethon Message.

        Приоритет: username → first_name → «Unknown».

        Returns:
            Строка с именем отправителя.
        """
        sender = getattr(message, "sender", None)
        if sender is None:
            return "Unknown"

        if isinstance(sender, User):
            username = getattr(sender, "username", None)
            if username:
                return username
            first = getattr(sender, "first_name", None) or ""
            last  = getattr(sender, "last_name",  None) or ""
            name  = f"{first} {last}".strip()
            return name or "Unknown"

        # Channel/Chat sender (анонимный пост от имени канала)
        return getattr(sender, "title", None) or "Unknown"

    @staticmethod
    def _eval_filter(message: Message, expression: str) -> bool:
        """
        Вычисляет выражение-фильтр над атрибутами сообщения.

        Доступные переменные в выражении:
            text       (str)      — текст сообщения
            user_id    (int|None) — ID отправителя
            username   (str)      — имя отправителя (пусто если неизвестно)
            has_media  (bool)     — True если есть медиа
            media_type (str|None) — "photo"|"video"|"voice"|"file"|"videomessage"|None
            date       (datetime) — дата сообщения в UTC

        Примеры выражений:
            "has_media and media_type == 'photo'"
            "user_id == 123456789"
            "'ключевое слово' in text.lower()"
            "date.year >= 2024"

        Returns:
            True  — сообщение проходит фильтр (включаем).
            False — сообщение отфильтровано (пропускаем).
            True  — при ошибке вычисления (не блокируем парсинг).
        """
        sender   = getattr(message, "sender", None)
        username = getattr(sender, "username", None) or "" if sender else ""

        names = {
            "text":       message.text or "",
            "user_id":    message.sender_id,
            "username":   username,
            "has_media":  message.media is not None,
            "media_type": ParserService._detect_media_type(message),
            "date":       message.date,
        }
        try:
            return bool(_simple_eval(expression, names=names))
        except Exception as exc:
            logger.debug("parser: filter_expression eval error: %s", exc)
            return True  # не блокируем парсинг при ошибке выражения

    @staticmethod
    def _extract_row_sync(
        message:  Message,
        chat_id:  int,
        topic_id: Optional[int],
    ) -> dict:
        """
        Быстрое синхронное извлечение полей сообщения без скачивания медиа.

        Вызывается в inline-пути цикла для текстовых сообщений (нет I/O).
        Возвращает row-словарь совместимый с insert_messages_batch().
        """
        sender_name = ParserService._get_sender_name(message)
        date_str    = message.date.strftime("%Y-%m-%d %H:%M:%S") if message.date else ""

        reply_to_msg_id: Optional[int] = None
        if message.reply_to:
            reply_to_msg_id = getattr(message.reply_to, "reply_to_msg_id", None)

        effective_topic_id = topic_id or ParserService._extract_topic_id(message)

        return {
            "chat_id":           chat_id,
            "message_id":        message.id,
            "topic_id":          effective_topic_id,
            "user_id":           message.sender_id,
            "username":          sender_name,
            "date":              date_str,
            "text":              message.text or "",
            "media_path":        None,
            "file_type":         None,
            "file_size":         None,
            "reply_to_msg_id":   reply_to_msg_id,
            "post_id":           None,
            "is_comment":        0,
            "from_linked_group": 0,
        }

    def _build_media_dir(self, media_type: Optional[str] = None) -> str:
        """
        Строит путь к подпапке медиа для текущего чата.

        Структура: output_dir / media / <тип>
            photos     — фотографии
            videos     — видеофайлы
            voice      — голосовые сообщения
            video_notes — кружочки
            files      — прочие документы

        Если тип не распознан — кладёт в корень media/.
        """
        base = os.path.join(self._output_dir, MEDIA_FOLDER_NAME)
        if media_type and media_type in _MEDIA_SUBFOLDERS:
            return os.path.join(base, _MEDIA_SUBFOLDERS[media_type])
        return base

    @staticmethod
    def _classify_chat_type(entity: object) -> str:
        """
        Определяет тип чата по Telethon-сущности для сохранения в БД.

        Returns:
            "channel" | "forum" | "group" | "private"
        """
        if isinstance(entity, User):
            return "private"
        if isinstance(entity, Chat):
            return "group"
        if isinstance(entity, Channel):
            if entity.broadcast:
                return "channel"
            if getattr(entity, "forum", False):
                return "forum"
            return "group"
        return "group"

    @staticmethod
    def _resolve_cutoff(days_limit: int) -> tuple[Optional[datetime], str]:
        """
        Вычисляет дату cutoff и метку периода для имени DOCX-файла.

        Args:
            days_limit: 0 или >= DAYS_LIMIT_ALL_TIME → всё время.
                        >0 и < DAYS_LIMIT_ALL_TIME → конкретный период.

        Returns:
            (cutoff_date, period_label)
            cutoff_date = None → «за всё время»
        """
        if days_limit <= 0 or days_limit >= DAYS_LIMIT_ALL_TIME:
            return None, "fullchat"

        now        = datetime.now(timezone.utc)
        cutoff     = now - timedelta(days=days_limit)
        label      = f"{cutoff.strftime('%Y-%m-%d')}_to_{now.strftime('%Y-%m-%d')}"
        return cutoff, label