"""
features/chats/api.py — Работа со списком чатов, форумами, linked группами.

Содержит всю Telethon-логику, которая связана с чатами:
  - Получение списка диалогов (get_dialogs)
  - Получение топиков форума (get_topics) с fallback на сканирование
  - Получение linked discussion group (get_linked_group)
  - Статистика активности участников (get_user_stats)
  - Классификация типов чатов (classify_entity)

ВАЖНЫЕ ПРАВИЛА (из claud.md):
  ✅ GetForumTopicsRequest — ТОЛЬКО functions.messages, НИКОГДА functions.channels
  ✅ GetForumTopicsRequest — ТОЛЬКО позиционные аргументы, НИКОГДА именованные
  ✅ GetForumTopicsRequest — ВСЕГДА передавай entity (результат get_entity),
     а не просто числовой ID
  ✅ ID из Telethon (get_peer_id, dialog.entity.id) — AS IS, нормализация не нужна
  ✅ ID из UI / ввода пользователя — через finalize_telegram_id(TelegramEntityType.CHANNEL)

Принцип: этот модуль является «входным фильтром» для всех chat_id.
После того как chat_id прошёл через методы этого сервиса — он гарантированно
нормализован и безопасен для передачи в parser/api.py и export/generator.py
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import logging
from typing import Dict, List, Optional

from telethon import TelegramClient, functions
from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.tl.functions.messages import GetFullChatRequest
from telethon.tl.types import (
    Channel,
    Chat,
    User,
)
from telethon.utils import get_peer_id

from config import FORUM_TOPICS_PAGE_SIZE, MAX_USER_STATS_LIMIT
from core.exceptions import (
    ChatNotFoundError,
    TelegramError,
)
from core.utils import finalize_telegram_id, TelegramEntityType

logger = logging.getLogger(__name__)


# ==============================================================================
# Типы данных
# ==============================================================================

# Результат get_dialogs: одна запись о чате
ChatInfo = Dict  # {id, raw_id, title, type, username, participants_count,
                 #  has_comments, linked_chat_id, is_linked_discussion}


# ==============================================================================
# Вспомогательная функция классификации
# ==============================================================================

def classify_entity(entity: object) -> str:
    """
    Определяет строковый тип чата по Telethon-объекту сущности.

    Используется в get_dialogs и везде, где нужно различать тип чата
    без дополнительных API-запросов.

    Returns:
        "private"  — личный чат с пользователем
        "group"    — обычная группа (Chat) или megagroup без форума
        "channel"  — broadcast-канал
        "forum"    — supergroup с включёнными топиками
        "unknown"  — не удалось определить (пропустить в UI)
    """

    if isinstance(entity, User):
        return "private"

    if isinstance(entity, Chat):
        return "group"

    if isinstance(entity, Channel):
        if entity.broadcast:
            return "channel"
        if entity.megagroup:
            return "forum" if getattr(entity, "forum", False) else "group"
        # Не broadcast и не megagroup — редкий случай, считаем каналом
        return "channel"

    return "unknown"


# ==============================================================================
# ChatsService
# ==============================================================================

class ChatsService:
    """
    Сервис для работы со списком чатов, форумами и linked группами.

    Инициализируется уже подключённым TelegramClient.
    Воркер (features/chats/ui.py) создаёт клиент, подключает его
    и передаёт сюда. Этот класс не управляет жизненным циклом клиента.

    Args:
        client: Подключённый TelegramClient (client.is_connected() == True).

    Example:
        # В QThread.run():
        client = TelegramClient(cfg.session_path, cfg.api_id_int, cfg.api_hash)
        await client.connect()
        service = ChatsService(client)
        dialogs = await service.get_dialogs(log=self.log_message.emit)
        await client.disconnect()
    """

    def __init__(self, client: TelegramClient) -> None:
        self._client = client

    # ------------------------------------------------------------------
    # 1. Список диалогов
    # ------------------------------------------------------------------

    async def get_dialogs(
        self,
        limit: int = 200,
        log=None,
        cache_db_path: Optional[str] = None,
        force_refresh: bool = False,
    ) -> List[ChatInfo]:
        """
        Возвращает список всех диалогов пользователя.

        При cache_db_path — сначала пробует отдать кэш из SQLite
        (актуальный не старше 24 часов). Сеть трогает только если
        кэш пуст, устарел или force_refresh=True.

        ID чатов берутся напрямую из Telethon через get_peer_id(entity)
        и используются AS IS — без finalize_telegram_id, так как
        Telethon уже возвращает корректный peer ID.

        Для каналов выполняется дополнительный запрос GetFullChannelRequest,
        чтобы узнать, есть ли linked discussion group (для кнопки «Комментарии»).
        Запрос делается в try/except, ошибка не прерывает загрузку.

        Args:
            limit:          Максимальное число диалогов (по умолчанию 200).
            log:            Колбэк для UI-логов. Если None — используется logger.info.
            cache_db_path:  Путь к SQLite-файлу кэша. None — кэш не используется.
            force_refresh:  True — игнорировать кэш, загрузить с сервера.

        Returns:
            Список ChatInfo, отсортированный по типу:
            сначала каналы, потом форумы, потом группы, потом личные.

        Raises:
            TelegramError: при критической ошибке Telegram API.
        """

        _log = log or logger.info

        # ── Кэш ────────────────────────────────────────────────────────
        if cache_db_path and not force_refresh:
            try:
                from core.database import DBManager
                with DBManager(cache_db_path) as _db:
                    cached = _db.load_dialogs_cache(max_age_hours=87600)
                    age    = _db.dialogs_cache_age_minutes()
                    day    = age // 1440
                    hour   = (age % 1440) // 60
                    min_   = age % 60
                if cached:
                    age_str = f"{day} д. {hour} ч. {min_} мин. назад" if age is not None else "недавно"
                    _log(f"📋 Загружено {len(cached)} чатов из кэша (обновлено {age_str})")
                    _log("💡 Для обновления нажмите кнопку 🔄 Обновить чаты")
                    return cached
            except Exception as exc:
                logger.warning("chats: не удалось прочитать кэш: %s", exc)

        _log("📄 Получение списка всех диалогов...")

        try:
            all_dialogs = await self._client.get_dialogs(limit=limit)
        except Exception as exc:
            logger.error("chats: get_dialogs failed: %s", exc)
            raise TelegramError(f"Не удалось получить список диалогов: {exc}") from exc

        _log(f"📊 Получено с сервера: {len(all_dialogs)} диалогов (запрошено: {limit})")

        dialogs: List[ChatInfo] = []

        for dialog in all_dialogs:
            entity = dialog.entity
            chat_type = classify_entity(entity)

            if chat_type == "unknown":
                logger.debug("chats: skip unknown entity type: %r", entity)
                continue

            # --- Имя чата ---
            if chat_type == "private":
                title = f"{getattr(entity, 'first_name', '') or ''} " \
                        f"{getattr(entity, 'last_name', '') or ''}".strip()
                if not title:
                    title = getattr(entity, "username", None) or f"User {entity.id}"
            else:
                title = getattr(entity, "title", None) or f"Chat {entity.id}"

            # --- ID: берём из Telethon AS IS ---
            peer_id = get_peer_id(entity)

            chat_info: ChatInfo = {
                "id":                   peer_id,
                "raw_id":               entity.id,
                "title":                title,
                "type":                 chat_type,
                "username":             getattr(entity, "username", None),
                "participants_count":   getattr(entity, "participants_count", 0) or 0,
                "has_comments":         False,
                "linked_chat_id":       None,
                "is_linked_discussion": False,
            }

            dialogs.append(chat_info)

        # --- Обогащение participants_count для каналов и групп ---
        # Telethon get_dialogs() не заполняет participants_count для broadcast-каналов
        # и маленьких групп. GetFullChannelRequest → full_chat.participants_count
        await self._enrich_participants_counts(dialogs, _log)

        # --- Сортировка: каналы → форумы → группы → личние ---
        _type_order = {"channel": 0, "forum": 1, "group": 2, "private": 3}
        dialogs.sort(key=lambda x: _type_order.get(x["type"], 9))

        _log(f"✅ Найдено {len(dialogs)} диалогов")
        logger.info("chats: get_dialogs → %d results", len(dialogs))

        # ── Сохраняем в кэш ─────────────────────────────────────────────
        if cache_db_path and dialogs:
            try:
                from core.database import DBManager
                with DBManager(cache_db_path) as _db:
                    _db.save_dialogs_cache(dialogs)
                logger.info("chats: кэш диалогов обновлён (%d записей)", len(dialogs))
            except Exception as exc:
                logger.warning("chats: не удалось сохранить кэш: %s", exc)

        return dialogs

    # ------------------------------------------------------------------
    # 1b. Обогащение participants_count (GetFullChannelRequest)
    # ------------------------------------------------------------------

    async def _enrich_participants_counts(
            self,
            dialogs: List[ChatInfo],
            log=None,
    ) -> None:
        """
        Обогащает participants_count для чатов, где он = 0.

        Telethon get_dialogs() не заполняет participants_count для:
        - Broadcast-каналов (всегда 0 из get_dialogs)
        - Маленьких/приватных групп (может быть 0)

        GetFullChannelRequest → full_chat.participants_count даёт точное число,
        но требует отдельный API-запрос на каждый чат.

        Используем asyncio.Semaphore(3) для ограничения параллелизма
        и избежания FloodWait. Ошибки не прерывают загрузку.

        Args:
            dialogs: Список ChatInfo (модифицируется in-place).
            log:     Колбэк для логов.
        """
        _log = log or logger.info

        # Собираем чаты, которым нужно обогащение: Channel с count == 0
        need_enrich = [
            (i, d) for i, d in enumerate(dialogs)
            if d.get("participants_count", 0) == 0
            and d.get("type") in ("channel", "forum", "group")
        ]

        if not need_enrich:
            return

        _log(f"📊 Обогащаю participants_count для {len(need_enrich)} чатов...")
        sem = asyncio.Semaphore(3)  # не более 3 параллельных запросов
        enriched = 0

        async def _fetch_one(idx: int, chat_info: ChatInfo) -> None:
            nonlocal enriched
            chat_id = chat_info.get("id")
            try:
                async with sem:
                    entity = await self._client.get_entity(chat_id)

                    if isinstance(entity, Channel):
                        # Супергруппа или канал — GetFullChannelRequest
                        full = await self._client(GetFullChannelRequest(channel=entity))
                        count = getattr(full.full_chat, "participants_count", 0) or 0
                    elif isinstance(entity, Chat):
                        # Базовая группа — GetFullChatRequest
                        full = await self._client(GetFullChatRequest(chat_id=entity.id))
                        count = getattr(full.full_chat, "participants_count", 0) or 0
                    else:
                        # Private chat / User — не enrich
                        return

                    if count > 0:
                        dialogs[idx]["participants_count"] = count
                        enriched += 1
                        logger.debug(
                            "chats: participants_count enriched: %s → %d",
                            chat_info.get("title", chat_id), count,
                        )
            except Exception as exc:
                # Ошибка — не критично, оставляем 0
                logger.debug(
                    "chats: _enrich_participants_counts failed for %s: %s",
                    chat_id, exc,
                )

        # Запускаем все задачи параллельно (с semaphore = 3)
        tasks = [_fetch_one(idx, d) for idx, d in need_enrich]
        await asyncio.gather(*tasks, return_exceptions=True)

        if enriched:
            _log(f"✅ Participants count обогащён для {enriched} чатов")

    # ------------------------------------------------------------------
    # 2. Топики форума
    # ------------------------------------------------------------------

    async def get_topics(
        self,
        chat_id: int,
        log=None,
    ) -> Dict[int, str]:
        """
        Получает список топиков форума.

        Стратегия (два уровня, с fallback):
          1. GetForumTopicsRequest — официальный API, пагинированный
          2. Сканирование iter_messages — если API вернул ошибку

        КРИТИЧНО: GetForumTopicsRequest принимает ТОЛЬКО ПОЗИЦИОННЫЕ аргументы.
        Никогда не используй именованные параметры — это сломает запрос.

        КРИТИЧНО: Нельзя передавать числовой ID напрямую — нужна InputChannel
        (entity). Всегда вызывай get_entity() перед GetForumTopicsRequest.

        Args:
            chat_id: ID чата. Принимает как нормализованный (-1002882674903),
                     так и raw положительный (2882674903) — будет нормализован.
            log:     Колбэк для UI-логов.

        Returns:
            Словарь {topic_id: title}. Пустой словарь — если чат не форум
            или топиков нет.

        Raises:
            ChatNotFoundError: если чат не найден или нет доступа.
        """

        _log = log or logger.info

        # Нормализуем ID: если пришёл raw положительный — добавляем -100 prefix
        normalized_id = finalize_telegram_id(chat_id, TelegramEntityType.CHANNEL)
        logger.debug("chats: get_topics chat_id=%s → normalized=%s", chat_id, normalized_id)

        # --- Получаем entity ---
        try:
            entity = await self._client.get_entity(normalized_id)
        except Exception as exc:
            logger.error("chats: get_entity(%s) failed: %s", normalized_id, exc)
            raise ChatNotFoundError(
                normalized_id,
                f"Не удалось найти чат {normalized_id}: {exc}"
            ) from exc

        # --- Проверяем флаг forum ---
        is_forum = getattr(entity, "forum", False)

        if not is_forum:
            # Пробуем получить полную информацию о канале
            try:
                full = await self._client(GetFullChannelRequest(channel=entity))
                if full.chats:
                    first_chat = full.chats[0]
                    if getattr(first_chat, "forum", False):
                        is_forum = True
                        # entity из get_entity() не заменяем — first_chat из full.chats[0]
                        # является «минимальным» объектом и не сериализуется Telethon корректно
            except Exception as exc:
                logger.debug("chats: GetFullChannelRequest failed: %s", exc)

        if not is_forum:
            _log("ℹ️ Чат не является форумом (флаг forum=False)")
            logger.info("chats: get_topics → not a forum, returning empty")
            return {}

        _log("📋 Получение списка топиков форума...")

        # --- Уровень 1: GetForumTopicsRequest (пагинация) ---
        # GetForumTopicsRequest требует InputChannel (с access_hash), а не Channel.
        # get_input_entity() возвращает правильный InputChannel из кэша сессии.
        topics: Dict[int, str] = {}
        try:
            input_entity = await self._client.get_input_entity(entity)
            topics = await self._fetch_topics_via_api(input_entity, _log)
            if topics:
                logger.info("chats: get_topics via API → %d topics", len(topics))
                return topics
        except Exception as exc:
            _log(f"⚠️ Ошибка прямого запроса топиков: {exc}")
            _log("🔄 Пробую альтернативный метод (сканирование сообщений)...")
            logger.warning("chats: GetForumTopicsRequest failed, trying fallback: %s", exc)

        # --- Уровень 2: Fallback — сканирование iter_messages ---
        try:
            topics = await self._fetch_topics_via_scan(entity, _log)
        except Exception as exc:
            logger.error("chats: fallback scan also failed: %s", exc)

        if not topics:
            _log("❌ Не удалось получить топики ни одним из способов")
            logger.error("chats: get_topics → both methods failed for %s", normalized_id)

        return topics

    async def _fetch_topics_via_api(
            self,
            entity,
            log,
    ) -> Dict[int, str]:
        """
        Получает топики через official GetForumTopicsRequest API.
        Важно: entity должен быть InputChannel, полученный через get_input_entity()

        Делает пагинированные запросы пока result.count > len(накоплено).

        Сигнатура Telethon 1.35+ (6 аргументов без hash):
            channel, q, offset_date, offset_id, offset_topic, limit

        Args:
            entity: InputChannel / Channel (результат get_entity).
            log:    Колбэк для логов.

        Returns:
            Словарь {topic_id: title}.
        """

        topics: Dict[int, str] = {}
        offset_date = None
        offset_id = 0
        offset_topic = 0

        try:
            # КРИТИЧНО: получаем InputChannel из entity
            input_entity = await self._client.get_input_entity(entity)
            logger.debug(f"Input entity type: {type(input_entity)}")

            if hasattr(input_entity, 'channel_id'):
                logger.debug(f"Channel ID in input_entity: {input_entity.channel_id}")

            while True:
                # Создаем запрос с явным указанием типов
                # q должен быть строкой или None, НИКОГДА не числом!
                request = functions.messages.GetForumTopicsRequest(
                    peer=input_entity,
                    q=None,  # Явно указываем None, а не число
                    offset_date=offset_date,
                    offset_id=offset_id,
                    offset_topic=offset_topic,
                    limit=FORUM_TOPICS_PAGE_SIZE
                )

                # Отправляем запрос
                result = await self._client(request)

                if not hasattr(result, "topics") or not result.topics:
                    break

                batch = result.topics
                total = getattr(result, "count", len(batch))

                log(f"📊 Загружено {len(topics) + len(batch)}/{total} топиков")

                for topic in batch:
                    # Получаем ID топика
                    topic_id = None
                    if hasattr(topic, 'id'):
                        topic_id = topic.id

                    if topic_id is not None:
                        # Получаем название топика
                        title = None
                        if hasattr(topic, 'title'):
                            title = topic.title

                        if not title:
                            title = f"Topic {topic_id}"

                        topics[topic_id] = title
                        logger.debug(f"Found topic: {topic_id} - {title}")

                # Условие выхода: получили всё или страница неполная
                if len(topics) >= total or len(batch) < FORUM_TOPICS_PAGE_SIZE:
                    break

                # Смещение для следующей страницы
                last = batch[-1]
                if hasattr(last, 'date'):
                    offset_date = last.date
                if hasattr(last, 'id'):
                    offset_id = last.id
                    offset_topic = last.id

        except Exception as e:
            logger.error(f"Error in _fetch_topics_via_api: {e}", exc_info=True)

        log(f"📋 Загружено {len(topics)} веток")
        return topics

    async def _fetch_topics_via_scan(
        self,
        entity,
        log,
        scan_limit: int = 500,
    ) -> Dict[int, str]:
        """
        Fallback: определяет топики по полю reply_to_top_id в сообщениях.

        Менее точный метод — заголовки топиков будут вида «Топик #ID».
        Используется только если GetForumTopicsRequest не сработал.

        Args:
            entity:      InputChannel сущность.
            log:         Колбэк для логов.
            scan_limit:  Сколько последних сообщений просканировать.

        Returns:
            Словарь {topic_id: «Топик #ID»}.
        """

        seen_topics: Dict[int, str] = {}

        async for message in self._client.iter_messages(entity, limit=scan_limit):
            # 1. Сервисное сообщение о создании топика — содержит реальное название
            action = getattr(message, "action", None)
            if action and hasattr(action, "title"):
                seen_topics[message.id] = action.title
                continue
            # 2. Обычное сообщение — определяем топик по reply_to_top_id
            reply_to = getattr(message, "reply_to", None)
            if reply_to:
                top_id = getattr(reply_to, "reply_to_top_id", None)
                if top_id and top_id not in seen_topics:
                    seen_topics[top_id] = f"Ветка #{top_id}"

        if seen_topics:
            log(f"📊 Найдено топиков через сканирование: {len(seen_topics)}")
            logger.info("chats: fallback scan → %d topics", len(seen_topics))
        else:
            log("ℹ️ В этом форуме нет топиков (или сообщения без структуры)")

        return seen_topics

    # ------------------------------------------------------------------
    # 3. Linked discussion group (для скачивания комментариев)
    # ------------------------------------------------------------------

    async def get_linked_group(
        self,
        channel_id: int,
        log=None,
    ) -> Optional[int]:
        """
        Возвращает ID linked discussion группы для канала.

        Linked группа — это Telegram-группа, в которой пользователи
        оставляют комментарии к постам канала. Найти её можно через
        GetFullChannelRequest → full_chat.linked_chat_id.

        Args:
            channel_id: ID канала. Принимает любой формат (нормализует сам).
            log:        Колбэк для UI-логов.

        Returns:
            ID linked группы или None если группы нет.

        Raises:
            ChatNotFoundError: если канал не найден.
        """

        _log = log or logger.info

        normalized_id = finalize_telegram_id(channel_id, TelegramEntityType.CHANNEL)
        logger.debug("chats: get_linked_group channel_id=%s → %s", channel_id, normalized_id)

        try:
            entity = await self._client.get_entity(normalized_id)
        except Exception as exc:
            raise ChatNotFoundError(
                normalized_id,
                f"Канал {normalized_id} не найден: {exc}"
            ) from exc

        # Только каналы могут иметь linked группу
        if not isinstance(entity, Channel):
            logger.debug("chats: get_linked_group: entity is not Channel")
            return None

        try:
            full = await self._client(GetFullChannelRequest(channel=entity))
            linked_id: Optional[int] = getattr(full.full_chat, "linked_chat_id", None)

            if linked_id:
                _log(f"✅ Найдена группа комментариев: {linked_id}")
                logger.info("chats: linked_group for %s → %s", normalized_id, linked_id)
                return linked_id

            _log("⚠️ У канала нет группы комментариев")
            return None

        except Exception as exc:
            logger.warning("chats: get_linked_group GetFullChannelRequest failed: %s", exc)
            _log(f"⚠️ Не удалось получить linked group: {exc}")
            return None

    # ------------------------------------------------------------------
    # 4. Статистика участников
    # ------------------------------------------------------------------

    async def get_user_stats(
        self,
        chat_id: int,
        limit: int = MAX_USER_STATS_LIMIT,
        date_from=None,
        date_to=None,
        log=None,
    ) -> List[Dict]:
        """
        Собирает топ активных участников чата по количеству сообщений.

        Работает без прав администратора (не использует get_participants).
        Сканирует последние N сообщений через iter_messages.

                ОСОБЕННОСТЬ (Variant A-2): В мегагруппах и каналах админ может писать
        «от имени канала». Такие сообщения имеют sender_type="channel".
        Канал/чат включается в participant list как равноправный отправитель.
        Нет резолва channel→admin (ненадёжно, не соответствует Telegram).

        Args:
            chat_id: ID чата (из get_dialogs, уже нормализован через get_peer_id).
            limit:   Сколько топ-участников вернуть.
            date_from: Фильтр: с какой даты (date или datetime).
            date_to:   Фильтр: по какую дату (date или datetime).
            log:     Колбэк для UI-логов.

        Returns:
            Список словарей {"id", "name", "username", "sender_type",
            "message_count"}, отсортированный по убыванию message_count.
        """

        _log = log or logger.info

        # ── Конвертация date → datetime для Telethon ──────────────────
        if date_from is not None and isinstance(date_from, _dt.date) and not isinstance(date_from, _dt.datetime):
            date_from = _dt.datetime.combine(date_from, _dt.time.min)
        if date_to is not None and isinstance(date_to, _dt.date) and not isinstance(date_to, _dt.datetime):
            date_to = _dt.datetime.combine(date_to, _dt.time(23, 59, 59))

        logger.info(
            "chats: get_user_stats: chat_id=%s, date_from=%r (%s), date_to=%r (%s)",
            chat_id,
            date_from, type(date_from).__name__ if date_from else "None",
            date_to, type(date_to).__name__ if date_to else "None",
        )

        # ID из get_dialogs() уже нормализован через get_peer_id().
        # finalize_telegram_id() ЛОМАЕТ ID для базовых групп Chat!
        try:
            entity = await self._client.get_entity(chat_id)
        except Exception as exc:
            logger.warning("chats: get_user_stats get_entity(%s) failed: %s", chat_id, exc)
            _log(f"⚠️ Не удалось найти чат {chat_id}: {exc}")
            return []

        entity_type = type(entity).__name__
        entity_id = getattr(entity, 'id', '?')
        is_channel_entity = isinstance(entity, Channel)
        is_chat_entity = isinstance(entity, Chat)
        is_broadcast = is_channel_entity and getattr(entity, "broadcast", False)
        is_megagroup = is_channel_entity and getattr(entity, "megagroup", False)

        logger.info(
            "chats: get_user_stats entity: %s id=%s (broadcast=%s, megagroup=%s, linked_chat_id=%s)",
            entity_type, entity_id,
            getattr(entity, "broadcast", None),
            getattr(entity, "megagroup", None),
            getattr(entity, "linked_chat_id", None),
        )

        # Счётчики
        counts: Dict[int, int] = {}
        names: Dict[int, str] = {}
        usernames: Dict[int, str] = {}
        sender_types: Dict[int, str] = {}

        try:
            # Pre-populate текущего пользователя
            try:
                me = await self._client.get_me()
                if me:
                    me_name = (
                        f"{me.first_name or ''} {me.last_name or ''}".strip()
                        or me.username or str(me.id)
                    )
                    names[me.id] = me_name
                    usernames[me.id] = (me.username or "").strip()
            except Exception:
                pass

            # Параметры iter_messages
            scan_limit = None if date_from else 10_000
            iter_kwargs: Dict = {"limit": scan_limit}
            if date_to is not None:
                iter_kwargs["offset_date"] = date_to

            msg_count = 0
            skipped = 0

            async for message in self._client.iter_messages(entity, **iter_kwargs):
                if date_from and message.date:
                    msg_date = message.date.replace(tzinfo=None) if hasattr(message.date, 'replace') else message.date
                    if msg_date < date_from:
                        break

                msg_count += 1

                # Определяем sender_id
                sender_id = getattr(message, "sender_id", None)
                if sender_id is None:
                    from_id = getattr(message, "from_id", None)
                    if from_id is not None:
                        sender_id = (
                            getattr(from_id, "user_id", None)
                            or getattr(from_id, "channel_id", None)
                            or getattr(from_id, "chat_id", None)
                        )
                    if sender_id is None:
                        peer_id = getattr(message, "peer_id", None)
                        if peer_id is not None and hasattr(peer_id, "channel_id"):
                            sender_id = peer_id.channel_id
                        else:
                            skipped += 1
                            continue

                counts[sender_id] = counts.get(sender_id, 0) + 1

                # Имя и тип отправителя
                if sender_id not in names:
                    try:
                        sender = getattr(message, "sender", None)
                        if sender is not None:
                            if isinstance(sender, User):
                                name = (
                                    f"{sender.first_name or ''} {sender.last_name or ''}".strip()
                                    or sender.username or f"Deleted_{sender_id}"
                                )
                                username = (sender.username or "").strip()
                                stype = "deleted" if not (sender.first_name or sender.last_name or sender.username) else "user"
                            else:
                                name = getattr(sender, "title", str(sender_id))
                                username = getattr(sender, "username", "") or ""
                                stype = "channel"
                            names[sender_id] = name
                            usernames[sender_id] = username
                            sender_types[sender_id] = stype
                        else:
                            from_id = getattr(message, "from_id", None)
                            if from_id is not None and hasattr(from_id, "channel_id"):
                                sender_types[sender_id] = "channel"
                            elif from_id is not None and hasattr(from_id, "user_id"):
                                sender_types[sender_id] = "deleted"
                            else:
                                peer_id = getattr(message, "peer_id", None)
                                if peer_id is not None and hasattr(peer_id, "channel_id"):
                                    sender_types[sender_id] = "channel"
                                else:
                                    sender_types[sender_id] = "user"
                    except Exception as exc:
                        logger.debug("chats: sender extraction failed: %s", exc)

            logger.info(
                "chats: get_user_stats scan: %d msgs, %d senders, %d skipped",
                msg_count, len(counts), skipped,
            )

            # Резолвим неизвестные имена
            unknown_ids = [uid for uid in counts if uid not in names]
            for uid in unknown_ids[:50]:
                try:
                    ent = await self._client.get_entity(uid)
                    if isinstance(ent, User):
                        names[uid] = (
                            f"{ent.first_name or ''} {ent.last_name or ''}".strip()
                            or ent.username or f"Deleted_{uid}"
                        )
                        usernames[uid] = (ent.username or "").strip()
                        sender_types[uid] = "deleted" if not (ent.first_name or ent.last_name or ent.username) else "user"
                    elif hasattr(ent, "title"):
                        names[uid] = getattr(ent, "title", str(uid))
                        usernames[uid] = getattr(ent, "username", "") or ""
                        sender_types[uid] = "channel"
                except Exception:
                    pass

        except Exception as exc:
            logger.warning("chats: get_user_stats iter_messages failed: %s", exc, exc_info=True)
            _log(f"⚠️ Ошибка получения статистики: {exc}")
            return []

        # ── B1/B3: Normalize channel sender IDs for DB compat ────
        # Telethon sender_id для channel-sender сообщений может не
        # совпадать с тем, что парсер сохранил в БД.  Парсер
        # нормализует channel sender_id в marked-negative формат
        # broadcast-канала.  Делаем то же самое, чтобы экспорт
        # находил сообщения через _telegram_user_id_variants().
        if is_megagroup:
            _linked = getattr(entity, "linked_chat_id", None)
            if _linked is not None:
                _bc_marked = -(1_000_000_000_000 + _linked)
                for _old in (entity.id,
                             -(1_000_000_000_000 + entity.id),
                             _linked):
                    if _old in counts and _old != _bc_marked:
                        counts[_bc_marked] = counts.get(_bc_marked, 0) + counts.pop(_old, 0)
                        if _old in names:
                            names[_bc_marked] = names.pop(_old)
                        if _old in usernames:
                            usernames[_bc_marked] = usernames.pop(_old)
                        if _old in sender_types:
                            sender_types[_bc_marked] = sender_types.pop(_old)
                if _bc_marked in counts:
                    logger.info(
                        "chats: B1/B3 normalize: megagroup channel sender "
                        "remapped → broadcast marked id=%s (%d msgs)",
                        _bc_marked, counts[_bc_marked],
                    )
        elif is_broadcast:
            _bc_marked = -(1_000_000_000_000 + entity.id)
            if entity.id in counts and entity.id != _bc_marked:
                counts[_bc_marked] = counts.get(_bc_marked, 0) + counts.pop(entity.id, 0)
                if entity.id in names:
                    names[_bc_marked] = names.pop(entity.id)
                if entity.id in usernames:
                    usernames[_bc_marked] = usernames.pop(entity.id)
                if entity.id in sender_types:
                    sender_types[_bc_marked] = sender_types.pop(entity.id)
                if _bc_marked in counts:
                    logger.info(
                        "chats: B1/B3 normalize: broadcast channel sender "
                        "remapped → marked id=%s (%d msgs)",
                        _bc_marked, counts[_bc_marked],
                    )

        # ── Variant A-2: канал как равноправный участник ──────────
        # В Channel-сущностях (broadcast-каналы, megagroups) — оставляем
        # channel-sender как равноправного участника (Variant A-2).
        # В базовых Chat-группах — убираем (название чата ≠ участник).
        filter_channel_senders = is_chat_entity

        # ── B1/B3: Merge channel-sender entries in megagroups ─────
        # В мегагруппе channel-sender может появляться с разными ID:
        # bare-positive (3508193296) и marked-negative (-1003783247484).
        # Сливаем в одну запись с marked-negative ID (формат БД).
        if is_megagroup:
            _ch_uids = [uid for uid in counts if sender_types.get(uid) == 'channel']
            if len(_ch_uids) > 1:
                # Prefer marked-negative ID (matches DB sender_id)
                _merged_id = next(
                    (uid for uid in _ch_uids if uid < -1_000_000_000_000),
                    -(1_000_000_000_000 + _ch_uids[0]),
                )
                _merged_count = sum(counts[u] for u in _ch_uids)
                # Name from broadcast channel entry (shorter, cleaner)
                _merged_name = None
                for _u in _ch_uids:
                    if _u < -1_000_000_000_000 and _u in names:
                        _merged_name = names[_u]
                        break
                if _merged_name is None:
                    _merged_name = names.get(_ch_uids[0], f"Channel_{_merged_id}")
                _merged_uname = next(
                    (usernames[u] for u in _ch_uids
                     if u in usernames and usernames[u]),
                    "",
                )
                for _u in _ch_uids:
                    del counts[_u]
                    names.pop(_u, None)
                    usernames.pop(_u, None)
                    sender_types.pop(_u, None)
                counts[_merged_id] = _merged_count
                names[_merged_id] = _merged_name
                usernames[_merged_id] = _merged_uname
                sender_types[_merged_id] = 'channel'
                logger.info(
                    "chats: B1/B3 merge: %d channel-sender entries → id=%s (%d msgs)",
                    len(_ch_uids), _merged_id, _merged_count,
                )

        sorted_users = sorted(counts.items(), key=lambda x: x[1], reverse=True)

        # Логируем ВСЕХ senders до фильтрации
        logger.info("chats: get_user_stats BEFORE filter (%d senders):", len(sorted_users))
        for uid, cnt in sorted_users[:10]:
            stype = sender_types.get(uid, "user")
            name = names.get(uid, f"User_{uid}")
            logger.info("  → %s (id=%s, type=%s, msgs=%d)", name, uid, stype, cnt)

        result: List[Dict] = []
        channel_skipped = 0
        for uid, cnt in sorted_users[:limit]:
            stype = sender_types.get(uid, "user")
            if stype == "channel" and filter_channel_senders:
                channel_skipped += 1
                continue
            result.append({
                "id": uid,
                "name": names.get(uid, f"User_{uid}"),
                "username": usernames.get(uid, None),
                "sender_type": stype,
                "message_count": cnt,
            })

        logger.info(
            "chats: get_user_stats AFTER filter: %d users (channel_skipped=%d)",
            len(result), channel_skipped,
        )
        for r in result[:5]:
            logger.info("  ✅ %s (id=%s, type=%s, msgs=%d)", r["name"], r["id"], r["sender_type"], r["message_count"])

        _log(f"📊 Топ {len(result)} активных участников получен")
        return result

    async def resolve_chat(
        self,
        chat_id: int,
        entity_type: str = TelegramEntityType.CHANNEL,
    ):
        """
        Нормализует chat_id и возвращает Telethon-сущность.

        Используется в parser/api.py и export/generator.py для получения
        entity перед iter_messages / get_messages.

        Args:
            chat_id:     Сырой или нормализованный ID чата.
            entity_type: Тип для finalize_telegram_id (по умолчанию CHANNEL).

        Returns:
            Telethon entity (Channel / Chat / User).

        Raises:
            ChatNotFoundError: если чат не найден или нет прав.
        """

        normalized = finalize_telegram_id(chat_id, entity_type)
        try:
            return await self._client.get_entity(normalized)
        except Exception as exc:
            raise ChatNotFoundError(
                normalized,
                f"Чат {normalized} не найден: {exc}"
            ) from exc
