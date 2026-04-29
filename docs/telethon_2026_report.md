# Telethon 2026 — Итоговый отчёт по высокопроизводительной архивации Telegram

> **Статус:** рабочий документ. Разделы, помеченные `⚗️ ТРЕБУЕТ ТЕСТИРОВАНИЯ`, содержат противоречивые данные из нескольких источников — финальная рекомендация будет уточнена по результатам практики.

---

## Содержание

1. [Контекст и ограничения](#1-контекст-и-ограничения)
2. [Диагноз медленной скорости iter_messages](#2-диагноз-медленной-скорости-iter_messages)
3. [Takeout API — полный разбор](#3-takeout-api--полный-разбор)
4. [Практические рекомендации по ускорению](#4-практические-рекомендации-по-ускорению)
5. [VPN и FloodWait](#5-vpn-и-floodwait)
6. [Прогрев сессии](#6-прогрев-сессии)
7. [Интеграция asyncio + PySide6](#7-интеграция-asyncio--pyside6)
8. [SQLite: синхронизация воркеров](#8-sqlite-синхронизация-воркеров)
9. [Forum-топики: надёжные методы](#9-forum-топики-надёжные-методы)
10. [Pause / Resume парсинга](#10-pause--resume-парсинга)
11. [Определение типа чата](#11-определение-типа-чата)
12. [Telethon заморожен — альтернативы](#12-telethon-заморожен--альтернативы)
13. [tdata и opentele в 2026](#13-tdata-и-opentele-в-2026)
14. [Лимиты Telegram API 2026](#14-лимиты-telegram-api-2026)
15. [Что НЕ помогает — список заблуждений](#15-что-не-помогает--список-заблуждений)

---

## 1. Контекст и ограничения

**Стек:** Python 3.10+, Telethon 1.42 (заморожен февраль 2026), PySide6 6.6+, SQLite WAL, asyncio в QThread.

**Основной сценарий:** скачать все сообщения группы/канала (5 000–50 000+) без медиафайлов.

### Абсолютное ограничение

> **ЗАПРЕЩЕНО** использовать параметр `limit` в `iter_messages` как метод ускорения.
> `limit` — это суммарный потолок итерации, а **не** размер батча.
> `limit=100` означает «вернуть только первые 100 сообщений и остановиться».

---

## 2. Диагноз медленной скорости `iter_messages`

### 2.1 Архитектурный потолок MTProto

`iter_messages` под капотом вызывает `messages.getHistory` (для каналов — `messages.channelMessages`).
**Жёсткий серверный лимит: 100 сообщений за один запрос.** Это не ограничение Telethon — это протокол.

Для 9 000 сообщений Telethon выполняет **минимум 90 последовательных запросов**.
Параллелизация невозможна: каждый следующий запрос использует `offset_id` из предыдущего ответа.

### 2.2 Причины нестабильности (2 сек vs 2+ мин на пакет)

**Основная причина: серверный имплицитный rate-limiting.**
Telegram задерживает ответ на стороне сервера вместо явного `FloodWaitError`.
Явный `FloodWaitError` — крайняя мера; чаще сервер молчит.

Паттерн из логов:
```
[14:56:37] 100 сообщений — быстро       ← первый пакет без тротлинга
[14:58:55] 200 сообщений — 2 мин 18 сек ← имплицитный FloodWait
[14:59:42] 300 сообщений — 47 сек
[15:00:02] 400 сообщений — 20 сек
[15:01:50] 500 сообщений — 1 мин 48 сек
[15:01:52] 600 сообщений — 2 сек        ← следующий пакет прошёл сразу
```

**Три фактора замедления работают одновременно:**

| Фактор | Механизм | Влияние |
|---|---|---|
| Новая/молодая сессия | Telegram агрессивно тротлит аккаунты без репутации | Высокое |
| VPN с ротацией IP | Смена exit-IP выглядит как разные устройства под одним аккаунтом | Среднее |
| `wait_time=0` в `iter_messages` | Запросы летят максимально быстро — триггерит тротлинг | Среднее |

### 2.3 ⚗️ ТРЕБУЕТ ТЕСТИРОВАНИЯ: IPv6 как причина начальной задержки

**Гипотеза (из одного источника):** Первая задержка 10–30 секунд перед первым пакетом может быть вызвана таймаутом IPv6 в VPN-сети. VPN-интерфейс не пробрасывает IPv6, попытка подключения через AAAA-запись зависает до автоматического fallback на IPv4.

**Диагностика:**
```bash
python -c "
import socket
socket.setdefaulttimeout(5)
try:
    socket.getaddrinfo('api.telegram.org', 443, socket.AF_INET6)
    print('IPv6 работает')
except Exception as e:
    print(f'IPv6 не работает: {e}')
"
```

**Если IPv6 зависает — принудительно форсировать IPv4:**
```python
import socket
_orig_getaddrinfo = socket.getaddrinfo

def _ipv4_only(host, port, family=0, type=0, proto=0, flags=0):
    return _orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)

socket.getaddrinfo = _ipv4_only  # вызвать до создания TelegramClient
```

> **Статус:** неподтверждённая гипотеза. Проверить: замерить время до первого сообщения с патчем и без.

### 2.4 `GetHistoryRequest` напрямую vs `iter_messages`

Прямой вызов `client(GetHistoryRequest(...))` **не быстрее** `iter_messages` по скорости передачи данных — это один и тот же сетевой запрос. Преимущество — **контроль**: можно настроить адаптивные паузы, кастомные ретраи и точно знать, когда история закончилась.

**Разница в скорости:** нет. **Разница в гибкости:** существенная.

---

## 3. Takeout API — полный разбор

### 3.1 Что такое Takeout

`account.initTakeoutSession` — специализированный интерфейс для экспорта данных.
Каждый последующий запрос оборачивается через `invokeWithTakeout`.

### 3.2 ⚗️ ТРЕБУЕТ ТЕСТИРОВАНИЯ: реальное влияние на скорость текстовых сообщений

| Характеристика | Обычный `iter_messages` | Takeout API |
|---|---|---|
| Сообщений за запрос | 100 | 100 (тот же лимит) |
| Риск явного FloodWait | Высокий | Сниженный |
| Скорость текста (Мбит/с) | Нестабильная | ⚗️ Спорно |
| Скорость медиа | До 9 МБ/с (Premium) | Ниже (~2 МБ/с) |
| Стабильность потока | Низкая (пиковые задержки) | Выше |

**Позиция A (один источник):** Takeout даёт ~2–4× ускорение для текста на зрелой сессии.

**Позиция B (два источника):** Takeout не ускоряет текст — тот же `GetHistory` с теми же 100 сообщениями/запрос. Преимущество — **стабильность** (меньше прерываний на 429), а не пропускная способность.

> **Рабочая гипотеза для теста:** Takeout снижает частоту многоминутных пауз, но не увеличивает скорость каждого отдельного запроса. Итог: то же количество сообщений/час, но без провалов.

### 3.3 Правильный жизненный цикл сессии

```python
import asyncio
from telethon import TelegramClient
from telethon.tl.functions.account import FinishTakeoutSessionRequest

async def parse_with_takeout(client: TelegramClient, chat_entity, progress_cb):
    try:
        async with client.takeout(
            contacts=False,
            users=True,
            chats=True,
            megagroups=True,
            channels=True,
            files=False,      # медиафайлы не нужны
            finalize=True,    # автозавершение при выходе из with
        ) as takeout_client:
            async for message in takeout_client.iter_messages(chat_entity, wait_time=0):
                await progress_cb(message)

    except Exception as e:
        if "Another takeout" in str(e) or "TAKEOUT_INIT" in str(e):
            # Принудительно закрыть зависшую сессию
            await client(FinishTakeoutSessionRequest(success=False))
            await asyncio.sleep(5)
            raise RuntimeError("Зависшая Takeout-сессия закрыта. Повторите попытку.") from e
        raise
```

### 3.4 Защита от краша при аварийном завершении

```python
from PySide6.QtWidgets import QApplication
from telethon.tl.functions.account import FinishTakeoutSessionRequest

def setup_takeout_cleanup(client, loop: asyncio.AbstractEventLoop):
    """Регистрирует cleanup при закрытии приложения."""
    def _on_quit():
        async def _finish():
            try:
                await client(FinishTakeoutSessionRequest(success=False))
            except Exception:
                pass
        asyncio.run_coroutine_threadsafe(_finish(), loop).result(timeout=5)

    QApplication.instance().aboutToQuit.connect(_on_quit)
```

### 3.5 Таймаут Takeout-сессии

Официальной документации по таймаутам нет. Эмпирически: сессия истекает через **24–48 часов**. `FinishTakeoutSessionRequest(success=False)` — корректный метод принудительного закрытия, не нарушает ToS.

---

## 4. Практические рекомендации по ускорению

### 4.1 Прямые запросы с адаптивными паузами

```python
import time
import asyncio
from telethon.tl.functions.messages import GetHistoryRequest
from telethon.errors import FloodWaitError, ServerError

async def fetch_all_messages(client, entity, on_batch=None):
    """
    Замена iter_messages. Скачивает ВСЕ сообщения без ограничения количества.
    Адаптирует паузы на основе времени ответа сервера.
    """
    all_messages = []
    offset_id = 0
    consecutive_empty = 0

    while True:
        t_start = time.monotonic()

        try:
            result = await client(GetHistoryRequest(
                peer=entity,
                offset_id=offset_id,
                offset_date=None,
                add_offset=0,
                limit=100,        # максимум, принимаемый сервером
                max_id=0,
                min_id=0,
                hash=0,
            ))
        except FloodWaitError as e:
            wait_sec = e.seconds + 5
            print(f"[FloodWait] Ждём {wait_sec} сек")
            await asyncio.sleep(wait_sec)
            continue
        except ServerError:
            await asyncio.sleep(10)
            continue

        elapsed = time.monotonic() - t_start
        messages = result.messages

        if not messages:
            consecutive_empty += 1
            if consecutive_empty >= 3:
                break
            await asyncio.sleep(2)
            continue

        consecutive_empty = 0
        all_messages.extend(messages)
        offset_id = messages[-1].id

        if on_batch:
            await on_batch(len(all_messages), messages)

        if len(messages) < 100:
            break  # последняя страница

        # Адаптивная пауза по времени ответа
        if elapsed < 0.5:
            wait = 0.3       # сервер не тротлит — работаем быстро
        elif elapsed < 2.0:
            wait = 0.7
        else:
            wait = elapsed * 0.5  # сервер тормозит — не давим
        await asyncio.sleep(wait)

    return all_messages
```

### 4.2 `reverse=True` — известный баг Telethon 1.42

При `reverse=True` итератор может преждевременно остановиться, если последнее сообщение имеет ID равный 100 (совпадает с размером батча).

**Рекомендация:** итерировать от новых к старым (по умолчанию), разворачивать список локально.

```python
messages = await fetch_all_messages(client, entity)
messages.reverse()  # теперь от старых к новым
```

---

## 5. VPN и FloodWait

### Ключевая проблема

VPN с ротацией IP заставляет Telegram видеть один аккаунт с разных адресов — агрессивный тротлинг. Стабильный exit-IP снижает частоту FloodWait на 20–40%.

### Рекомендуемые решения (по приоритету)

**1. MTProto proxy** — наилучший вариант для заблокированных регионов. Telegram не видит "чужого" IP:

```python
from telethon.network import ConnectionTcpMTProxyRandomizedIntermediate

client = TelegramClient(
    session_path, api_id, api_hash,
    connection=ConnectionTcpMTProxyRandomizedIntermediate,
    proxy=('proxy.host', 443, 'secret_hex_here'),
)
```

**2. VPN с dedicated/static IP** — если MTProto proxy недоступен, выбрать тариф с фиксированным IP.

**3. SOCKS5 с постоянным адресом:**

```python
client = TelegramClient(
    session_path, api_id, api_hash,
    proxy=('socks5', '127.0.0.1', 1080),
)
```

---

## 6. Прогрев сессии

Telegram строит репутацию сессии на основе: длительности жизни, разнообразия активности, стабильности IP.

### Оценки сроков прогрева (противоречивые данные)

| Источник | Оценка | Условие |
|---|---|---|
| Источник A | 2–4 недели | Минимальная органическая активность |
| Источник B | 3–5 дней | Имитация активности 8–15 действий/день |
| Источник C | 24 часа | Активная нагрузка (200+ запросов) |

> Публичных данных Telegram по этому параметру нет. Все цифры — эмпирические наблюдения.

### Практические шаги прогрева

```
1. get_dialogs() — первичная инициализация (занимает долго на новой сессии, это норма)
2. Подождать кэширования диалогов (24 часа)
3. Начинать с малых архивов (до 1 000 сообщений)
4. Постепенно увеличивать объём
5. Резкий старт на 50 000+ сообщений на новой сессии → FloodWait на несколько часов
```

---

## 7. Интеграция asyncio + PySide6

### ⚗️ ТРЕБУЕТ ТЕСТИРОВАНИЯ: QtAsyncio для Telethon

**Позиция A (один источник):** Не рекомендуется. Telethon запускает внутренние корутины (сетевой receiver, обработка updates). При использовании Qt event loop в main thread они конкурируют с отрисовкой UI → фризы.

**Позиция B (два источника):** QtAsyncio — «оптимальный паттерн 2026», объединяет оба цикла в одном потоке, устраняет большинство проблем с SQLite.

> **Для теста:** запустить Telethon через `QtAsyncio.run()` и измерить задержки UI при активном парсинге. Контрольный сценарий: парсинг 1 000 сообщений с нажатием кнопок UI каждые 5 секунд.

### Рекомендуемый паттерн (консервативный): единый поток с постоянным event loop

Вместо создания нового event loop в каждом воркере — один общий поток:

```python
import asyncio
import threading
from PySide6.QtCore import QThread, QObject, Signal

class TelegramEventLoopThread(QThread):
    """Единый поток для всех Telegram-операций."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ready = threading.Event()

    def run(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._ready.set()
        self._loop.run_forever()

    def get_loop(self) -> asyncio.AbstractEventLoop:
        self._ready.wait()
        return self._loop

    def submit(self, coro) -> asyncio.Future:
        """Потокобезопасная отправка корутины из любого потока."""
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    def stop(self):
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)
        self.wait()


class ParseWorker(QObject):
    progress = Signal(int, int)   # (current, total)
    finished = Signal()
    error = Signal(str)

    def __init__(self, client, entity, loop_thread: TelegramEventLoopThread):
        super().__init__()
        self._client = client
        self._entity = entity
        self._loop_thread = loop_thread
        self._stop_event: asyncio.Event | None = None

    def start(self):
        future = self._loop_thread.submit(self._run())
        future.add_done_callback(self._on_done)

    def stop(self):
        """Потокобезопасная остановка из GUI-потока."""
        if self._stop_event:
            self._loop_thread.get_loop().call_soon_threadsafe(
                self._stop_event.set
            )

    async def _run(self):
        self._stop_event = asyncio.Event()
        try:
            count = 0
            offset_id = 0

            while not self._stop_event.is_set():
                from telethon.tl.functions.messages import GetHistoryRequest
                result = await self._client(GetHistoryRequest(
                    peer=self._entity,
                    offset_id=offset_id,
                    offset_date=None,
                    add_offset=0,
                    limit=100,
                    max_id=0, min_id=0, hash=0,
                ))
                if not result.messages:
                    break

                await self._save_batch(result.messages)
                count += len(result.messages)
                offset_id = result.messages[-1].id
                self.progress.emit(count, 0)

                if len(result.messages) < 100:
                    break
                await asyncio.sleep(1.0)

        except Exception as e:
            self.error.emit(str(e))
        finally:
            self.finished.emit()

    async def _save_batch(self, messages):
        pass  # реализация через DBManager

    def _on_done(self, future):
        if future.exception():
            self.error.emit(str(future.exception()))
```

### Передача команд из GUI в воркер

| Механизм | Применение |
|---|---|
| `asyncio.Event` | Пауза / стоп (установить через `call_soon_threadsafe`) |
| `asyncio.Queue` | Очередь задач (следующий чат для парсинга) |
| `loop_thread.submit(coro)` | Одноразовые команды из GUI |

---

## 8. SQLite: синхронизация воркеров

### Сценарии блокировки

1. Два `TelegramClient` открыты на одном `.session` файле
2. Воркер не закрыл соединение до старта следующего
3. `disconnect()` вызван из чужого event loop пока воркер работает

### Правильная синхронизация — явные сигналы вместо `QTimer`

```python
class AuthWorker(QObject):
    client_closed = Signal()  # только после реального disconnect()

    async def _run(self):
        client = TelegramClient(session_path, api_id, api_hash)
        await client.connect()
        # ... авторизация ...

        await self._should_close.wait()  # ждём команды закрытия

        # Закрываем ВНУТРИ того же event loop
        await client.disconnect()

        # Только после этого — сигнал главному потоку
        self.client_closed.emit()

    def request_close(self):
        self._loop.call_soon_threadsafe(self._should_close.set)
```

### Конфигурация SQLite

```python
import sqlite3

def setup_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=30, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=30000")  # 30 сек вместо мгновенного краша
    return conn
```

| Стратегия | Плюсы | Минусы |
|---|---|---|
| WAL mode | Чтение не блокирует запись | Увеличение размера файла |
| `busy_timeout=30000` | Простота, не падает сразу | UI может зависнуть при ожидании |
| Единственный writer thread | Нет конфликтов | Требует архитектурной дисциплины |
| `asyncio.Queue` → writer coroutine | Максимальная надёжность | Сложнее реализация |

> **Рекомендация:** WAL + `busy_timeout` + единственный поток записи через `DBManager`. `QTimer.singleShot(300)` — ненадёжно, заменить на явный сигнал `client_closed`.

---

## 9. Forum-топики: надёжные методы

### Получение названия топика по ID

```python
from telethon.tl.functions.channels import GetForumTopicsByIDRequest

async def get_topic_title(client, channel_entity, topic_id: int) -> str:
    """Надёжное получение названия без сканирования истории."""
    try:
        result = await client(GetForumTopicsByIDRequest(
            channel=channel_entity,
            topics=[topic_id],
        ))
        if result.topics:
            return result.topics[0].title
    except Exception:
        pass

    if topic_id == 1:
        return "General"

    return f"Ветка #{topic_id}"
```

### Почему `GetForumTopicsRequest` иногда не работает

- Требует прав на чтение форума
- Для приватных групп — нужно быть участником
- Иногда возвращает пустой список при первом вызове (кэш не построен) → повторить через 1–2 сек

### Топик General

```python
def is_general_topic(topic_id: int, topic=None) -> bool:
    """ID=1 всегда General. Явного флага нет."""
    if topic_id == 1:
        return True
    if topic:
        return getattr(topic, 'default', False)
    return False
```

### Получение сообщений топика

```python
# Правильный способ — reply_to=topic_id
async for message in client.iter_messages(channel_entity, reply_to=topic_id):
    yield message
```

Сообщения топика General (id=1) часто не имеют `reply_to` или имеют `reply_to.reply_to_top_id == None` — обрабатывать отдельно.

### Комментарии к постам канала

```python
from telethon.tl.functions.messages import GetDiscussionMessageRequest

async def get_post_comments(client, channel_entity, post_id: int):
    """
    Edge cases:
    - Не у всех постов есть обсуждение → обернуть в try/except
    - ID поста в канале ≠ ID сообщения в группе комментариев
    """
    try:
        discussion = await client(GetDiscussionMessageRequest(
            peer=channel_entity,
            msg_id=post_id,
        ))
        # discussion.chats содержит группу обсуждений
        # discussion.messages[0].peer_id — ID группы комментариев
        group_peer = discussion.messages[0].peer_id
        top_msg_id = discussion.max_id

        async for comment in client.iter_messages(group_peer, reply_to=top_msg_id):
            yield comment
    except Exception:
        return  # у этого поста нет обсуждения
```

---

## 10. Pause / Resume парсинга

```python
class ParseController:
    def __init__(self):
        self._pause = asyncio.Event()
        self._pause.set()  # set = разрешено работать
        self._stop = asyncio.Event()

    async def checkpoint(self):
        """Вставлять в цикл. Блокирует при паузе, бросает при стопе."""
        await self._pause.wait()
        if self._stop.is_set():
            raise asyncio.CancelledError("Парсинг остановлен")

    def pause(self):
        self._pause.clear()

    def resume(self):
        self._pause.set()

    def stop(self):
        self._stop.set()
        self._pause.set()  # разблокировать паузу чтобы CancelledError прошёл

# В цикле парсинга:
async def _parse_loop(controller: ParseController, ...):
    offset_id = 0
    while True:
        await controller.checkpoint()  # ← точка паузы/стопа

        result = await fetch_batch(offset_id)
        if not result:
            break

        await save_batch(result)      # offset_id сохранён — данные не потеряются
        offset_id = result[-1].id
        await asyncio.sleep(1.0)
```

---

## 11. Определение типа чата

```python
from telethon.tl.types import Channel, Chat

def detect_chat_type(entity) -> str:
    """Надёжное определение типа по entity в Telethon 1.42."""
    if not isinstance(entity, Channel):
        if isinstance(entity, Chat):
            return "group"      # обычная группа
        return "user"

    if entity.broadcast:
        return "channel"        # канал

    if entity.megagroup:
        if getattr(entity, 'forum', False):
            return "forum"      # супергруппа-форум
        if getattr(entity, 'gigagroup', False):
            return "gigagroup"  # гигагруппа
        return "megagroup"      # супергруппа

    return "unknown"
```

---

## 12. Telethon заморожен — альтернативы

Репозиторий Telethon переведён в read-only **21 февраля 2026**. Новых патчей не будет. При обновлении MTProto-слоя Telegram — часть методов может перестать работать без возможности исправления.

### Сравнение альтернатив

| Библиотека | Статус 2026 | MTProto Layer | Преимущества | Недостатки |
|---|---|---|---|---|
| **Telethon 1.42** | ❌ Заморожен | 1.42 (риск устаревания) | Стабильный API, знакомый код | Нет патчей |
| **Pyrofork** | ✅ Активен | Актуальный | Исправления багов, Topics support | API Pyrogram, переписывание |
| **Hydrogram** | ⚗️ Проверить | Актуальный | `aiosqlite`, современная упаковка | ⚗️ Статус активности неизвестен |
| **Kurigram** | ✅ Активен | Актуальный | TgCrypto на C (быстро) | Меньшее сообщество |
| **Pyrogram v2** | ⚠️ Низкая | Устаревает | Большая кодовая база | Telegram почти бросил |

> **Проверить прямо сейчас:** последний коммит Hydrogram на GitHub — от этого зависит рекомендация.

### Стратегия миграции

**Краткосрочно (6–12 месяцев):** оставаться на Telethon 1.42. Telegram не ломает обратную совместимость быстро.

**Среднесрочно:** оценить Pyrofork. Основные отличия API:

| Telethon | Pyrofork |
|---|---|
| `client.iter_messages(entity)` | `client.get_chat_history(chat_id)` |
| `client.get_entity(id)` | `client.get_chat(id)` |
| `FloodWaitError` | `FloodWait` |
| `TelegramClient` | `Client` |

Расчётное время миграции: **2–4 недели** для приложения уровня RozittaParser.

---

## 13. tdata и opentele в 2026

`opentele` последний раз обновлялась в 2022–2023 году. **Несовместима с Telethon 1.35+** из-за изменений внутреннего API сессий.

### Рекомендации

1. `ToTelethon()` вызывать **только при закрытом Telegram Desktop**
2. Генерировать уникальный `unique_id` для уникального fingerprint устройства
3. При несовместимости с новыми версиями tdata — использовать **QR-авторизацию** как альтернативу

### Безопасная альтернатива tdata-импорту

Предложить пользователю экспортировать session-строку через отдельный скрипт на той же машине, пока Telegram Desktop закрыт. Не требует разбора бинарных форматов.

---

## 14. Лимиты Telegram API 2026

| Параметр | Лимит | Примечание |
|---|---|---|
| Сообщений за `GetHistory` запрос | 100 | Жёсткий, протокольный |
| Запросов в секунду (user API) | ~30 | Мягкий, динамический |
| FloodWait длительность | 1 сек – несколько часов | Зависит от сессии и действия |
| Takeout-сессия таймаут | 24–48 часов | Неофициальные данные |
| `AUTH_KEY_DUPLICATED` | При одновременном использовании одного `.session` | Использовать уникальный файл на поток |
| `FLOOD_PREMIUM_WAIT` | Отдельный FloodWait для non-Premium | Обрабатывать как обычный `FloodWaitError` |

```python
from telethon.errors import FloodWaitError

async def safe_request(client, request):
    while True:
        try:
            return await client(request)
        except FloodWaitError as e:
            # Покрывает и FLOOD_PREMIUM_WAIT
            await asyncio.sleep(e.seconds + 5)
```

---

## 15. Что НЕ помогает — список заблуждений

| Что пробовали | Почему не работает |
|---|---|
| `limit=N` в `iter_messages` для ускорения | Ограничивает **итоговое число** сообщений, не размер батча |
| `wait_time=0` | Убирает паузы в Telethon, но не влияет на серверный тротлинг |
| Понижение уровня логирования | Logging overhead пренебрежимо мал относительно сетевых задержек |
| `_DB_BATCH_SIZE` изменение | Влияет только на дисковые операции, не на сеть |
| Кэш диалогов | Ускоряет `get_dialogs`, не ускоряет `iter_messages` |
| Параллельные `GetHistoryRequest` | Невозможно — следующий запрос требует `offset_id` из предыдущего |
| Частая смена `.session` файла | Новые сессии тормозят сильнее зрелых |
| `device_model` / `app_version` хак | ⚗️ Спорно: Telegram анализирует поведение, а не заголовки; дефолтный `"Telethon"` в device_model маркирует клиент |
| Пользовательские `api_id`/`api_hash` | FloodWait определяется аккаунтом, не клиентом |
| `QTimer.singleShot(300)` между воркерами | Магическое число без гарантий; заменить на явный сигнал закрытия |

---

## Приложение: Матрица нерешённых противоречий

| # | Вопрос | Позиция A | Позиция B | Как тестировать |
|---|---|---|---|---|
| 1 | QtAsyncio для Telethon | ❌ Фризы UI | ✅ Оптимально | Парсинг 1000 сообщений + нажатия кнопок, замер задержки UI |
| 2 | Takeout ускоряет текст | ~2–4× рост скорости | Только стабильность, скорость та же | Замер: 5000 сообщений через Takeout vs обычный, записать время каждого батча |
| 3 | IPv6 как причина задержки | Ключевая причина 10–30 сек | Не упоминается | Патч `socket.getaddrinfo` на IPv4-only, замерить время до первого пакета |
| 4 | Срок прогрева сессии | 24 часа (активно) | 2–4 недели (пассивно) | Новая сессия, замер скорости iter_messages на день 1 / 3 / 7 / 14 |
| 5 | Статус Hydrogram | Активен | Неактивен? | Проверить GitHub: дата последнего коммита, открытые PR |

---

*Документ обновляется по мере прохождения тестов. Дата последнего обновления: март 2026.*


UPD:
комментарии к постам канала не являются обычными сообщениями группы и не должны ожидаться как результат get_participants() или iter_messages(group) без привязки к посту. Для Telethon корректный путь — собирать комментарии отдельно по каждому посту канала через reply_to=post_id, а для привязанной группы (linked_chat_id) явно разделять «прямых участников группы» и «авторов комментариев к постам канала».

Ещё стоит уточнить, что linked_chat_id означает привязанную discussion-группу канала, а не универсальный список всех комментаторов, и что по выбору канала экспорт должен идти в два шага: сначала посты канала, потом комментарии к каждому посту.

Коротко:

linked_chat_id у канала указывает на связанную группу обсуждений, но не делает её источником всех комментаторов автоматически.

Для получения комментариев к постам канала в Telethon нужно использовать iter_messages(..., reply_to=post_id) или GetDiscussionMessageRequest + reply_to.

get_participants() / iter_participants() возвращают участников конкретного чата, а не список пользователей, комментировавших посты канала.
