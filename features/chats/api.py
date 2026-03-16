"""
features/chats/api.py — Работа со списком чатов, форумами, linked группами

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
import logging
from typing import Dict, List, Optional, Tuple

from telethon import TelegramClient, functions
from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.tl.types import (
    Channel,
    Chat,
    User,
    InputChannel,
)
from telethon.utils import get_peer_id

from config import FORUM_TOPICS_PAGE_SIZE, MAX_USER_STATS_LIMIT
from core.exceptions import (
    ChatNotFoundError,
    FloodWaitError,
    ForumTopicsError,
    LinkedGroupNotFoundError,
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
    ) -> List[ChatInfo]:
        """
        Возвращает список всех диалогов пользователя.

        ID чатов берутся напрямую из Telethon через get_peer_id(entity)
        и используются AS IS — без finalize_telegram_id, так как
        Telethon уже возвращает корректный peer ID.

        Для каналов выполняется дополнительный запрос GetFullChannelRequest,
        чтобы узнать, есть ли linked discussion group (для кнопки «Комментарии»).
        Запрос делается в try/except, ошибка не прерывает загрузку.

        Args:
            limit: Максимальное число диалогов (по умолчанию 200).
            log:   Колбэк для UI-логов. Если None — используется logger.info.

        Returns:
            Список ChatInfo, отсортированный по типу:
            сначала каналы, потом форумы, потом группы, потом личные.

        Raises:
            TelegramError: при критической ошибке Telegram API.
        """
        _log = log or logger.info
        _log("📄 Получение списка всех диалогов...")

        try:
            all_dialogs = await self._client.get_dialogs(limit=limit)
        except Exception as exc:
            logger.error("chats: get_dialogs failed: %s", exc)
            raise TelegramError(f"Не удалось получить список диалогов: {exc}") from exc

        dialogs: List[ChatInfo] = []
        # Индексы каналов в dialogs + entity для параллельного GetFullChannelRequest
        _channel_indices: List[Tuple[int, object]] = []

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

            if chat_type == "channel":
                _channel_indices.append((len(dialogs), entity))

            dialogs.append(chat_info)

        # --- Параллельные запросы linked group для всех каналов ---
        if _channel_indices:
            _log(f"🔗 Проверяю linked group для {len(_channel_indices)} каналов...")
            # Semaphore(3) — не более 3 одновременных запросов:
            # Telegram DC допускает ~3–4 параллельных MTProto-запроса;
            # при 5+ часть получает «Server resent» и ждёт retry, суммарно медленнее.
            _sem = asyncio.Semaphore(3)

            async def _fetch_linked(ent) -> Optional[int]:
                async with _sem:
                    try:
                        full = await asyncio.wait_for(
                            self._client(GetFullChannelRequest(channel=ent)),
                            timeout=8.0,
                        )
                        # yield event loop — даём MTProto-слою обработать ACK-очередь
                        await asyncio.sleep(0)
                        return getattr(full.full_chat, "linked_chat_id", None)
                    except asyncio.TimeoutError:
                        logger.warning("chats: GetFullChannelRequest timeout for %s", ent)
                        return None
                    except Exception as exc:
                        logger.warning("chats: GetFullChannelRequest failed for %s: %s", ent, exc)
                        return None

            import time
            _t = time.perf_counter()
            linked_results = await asyncio.gather(
                *[_fetch_linked(ent) for _, ent in _channel_indices],
                return_exceptions=False,
            )
            logger.info(
                "✅ linked group: %d за %.1fs",
                sum(1 for r in linked_results if r),
                time.perf_counter() - _t,
            )
            for (idx, _), linked_id in zip(_channel_indices, linked_results):
                if linked_id:
                    dialogs[idx]["has_comments"] = True
                    dialogs[idx]["linked_chat_id"] = linked_id
                    logger.debug(
                        "chats: channel %s has linked_chat_id=%s",
                        dialogs[idx]["id"], linked_id
                    )

        # --- Сортировка: каналы → форумы → группы → личные ---
        _type_order = {"channel": 0, "forum": 1, "group": 2, "private": 3}
        dialogs.sort(key=lambda x: _type_order.get(x["type"], 9))

        _log(f"✅ Найдено {len(dialogs)} диалогов")
        logger.info("chats: get_dialogs → %d results", len(dialogs))
        return dialogs

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
        topics: Dict[int, str] = {}
        try:
            topics = await self._fetch_topics_via_api(entity, _log)
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
        offset_date = 0
        offset_id = 0
        offset_topic = 0

        while True:
            result = await self._client(
                functions.messages.GetForumTopicsRequest(
                    entity,             # peer — позиционно
                    None,               # q
                    offset_date,        # offset_date
                    offset_id,          # offset_id
                    offset_topic,       # offset_topic
                    FORUM_TOPICS_PAGE_SIZE,  # limit
                )
            )

            if not hasattr(result, "topics") or not result.topics:
                break

            batch = result.topics
            total = getattr(result, "count", len(batch))

            log(f"📊 Загружено {len(topics) + len(batch)}/{total} топиков")

            for topic in batch:
                topic_id = getattr(topic, "id", None)
                if topic_id is not None:
                    title = getattr(topic, "title", None) or f"Топик #{topic_id}"
                    topics[topic_id] = title

            # Условие выхода: получили всё или страница неполная
            if len(topics) >= total or len(batch) < FORUM_TOPICS_PAGE_SIZE:
                break

            # Смещение для следующей страницы
            last = batch[-1]
            offset_date  = getattr(last, "date", 0) or 0
            offset_id    = getattr(last, "id", 0) or 0
            offset_topic = getattr(last, "id", 0) or 0

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
            reply_to = getattr(message, "reply_to", None)
            if reply_to:
                top_id = getattr(reply_to, "reply_to_top_id", None)
                if top_id and top_id not in seen_topics:
                    seen_topics[top_id] = f"Топик #{top_id} (из сообщений)"

        if seen_topics:
            log(f"📊 Найдено топиков через сканирование: {len(seen_topics)}")
            logger.info("chats: fallback scan → %d topics", len(seen_topics))
        else:
            log("ℹ️ В этом форуме нет топиков (или первые 500 сообщений без reply_to)")

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
        log=None,
    ) -> List[Dict]:
        """
        Собирает топ активных участников чата по количеству сообщений.

        Статистика строится на основе последних 1000 сообщений.
        Полная альтернатива — get_participants() + итерация, но она
        требует прав администратора. Данный метод работает без привилегий.

        Args:
            chat_id: ID чата (любой формат).
            limit:   Сколько топ-участников вернуть.
            log:     Колбэк для UI-логов.

        Returns:
            Список словарей {"id": int, "name": str, "username": str|None,
            "message_count": int}, отсортированный по убыванию message_count.
            Пустой список при ошибке.
        """
        _log = log or logger.info
        normalized_id = finalize_telegram_id(chat_id, TelegramEntityType.CHANNEL)

        try:
            entity = await self._client.get_entity(normalized_id)
        except Exception as exc:
            logger.warning("chats: get_user_stats get_entity failed: %s", exc)
            return []

        # Счётчик: {user_id: count}
        counts: Dict[int, int] = {}
        # Кэш имён: {user_id: display_name}
        names: Dict[int, str] = {}

        try:
            async for message in self._client.iter_messages(entity, limit=1000):
                sender_id = getattr(message, "sender_id", None)
                if sender_id is None:
                    continue

                counts[sender_id] = counts.get(sender_id, 0) + 1

                # Имя — берём из объекта сообщения, если ещё не знаем
                if sender_id not in names:
                    sender = getattr(message, "sender", None)
                    if sender is not None:
                        if isinstance(sender, User):
                            name = (
                                f"{sender.first_name or ''} {sender.last_name or ''}".strip()
                                or sender.username
                                or str(sender_id)
                            )
                        else:
                            name = getattr(sender, "title", str(sender_id))
                        names[sender_id] = name

        except Exception as exc:
            logger.warning("chats: get_user_stats iter_messages failed: %s", exc)
            _log(f"⚠️ Ошибка получения статистики: {exc}")
            return []

        # Сортируем и обрезаем до limit
        sorted_users = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:limit]

        result: List[Dict] = [
            {"id": uid, "name": names.get(uid, f"User_{uid}"), "username": None, "message_count": cnt}
            for uid, cnt in sorted_users
        ]

        _log(f"📊 Топ {len(result)} активных участников получен")
        logger.info("chats: get_user_stats → %d users", len(result))
        return result

    # ------------------------------------------------------------------
    # 5. Вспомогательные методы
    # ------------------------------------------------------------------

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
