```markdown
# Инструкция для Claude: разработка высокопроизводительного архиватора Telegram (апрель 2026)

## Цель документа

Эта инструкция содержит проверенные практические рекомендации, архитектурные решения и предупреждения для создания надёжного приложения для скачивания истории сообщений из Telegram на базе **Telethon 1.42** (заморожен), **Python 3.10+**, **asyncio** и **PySide6**.  
Документ адресован ИИ-ассистенту Claude для помощи в написании, отладке и рефакторинге кода.

## Общие ограничения и контекст

- Используется **Telethon 1.42** (февраль 2026, репозиторий переведён в read-only). Новых исправлений не будет.  
- Основная задача — скачивание **только текстовых сообщений** из чатов, групп, каналов (до 50 000+ сообщений).  
- Абсолютное правило: **не пытаться ускорять `iter_messages` с помощью параметра `limit`**.  
  `limit` задаёт общее количество сообщений, возвращаемых итератором, а не размер сетевого пакета.  
  Серверный лимит на один вызов `GetHistoryRequest` — **100 сообщений**. Это ограничение протокола.

## Архитектура взаимодействия с Telegram API

### Причины медленной работы `iter_messages` на молодых сессиях

1. **Серверный неявный тротлинг**  
   Telegram может задерживать ответы на несколько минут **без** явного `FloodWaitError`.  
   Особенно агрессивно ведёт себя по отношению к новым аккаунтам, частой смене IP и слишком быстрым последовательным запросам.

2. **VPN с ротацией IP**  
   Один аккаунт, приходящий с разных адресов, расценивается как подозрительная активность.  
   Рекомендуется использовать **статический IP** или **MTProto-прокси**.

3. **Параметр `wait_time=0`**  
   Убирает клиентские паузы, но провоцирует серверный тротлинг.  
   Рекомендуется заменять `iter_messages` прямыми вызовами `GetHistoryRequest` с адаптивными паузами.

### Прямой вызов `GetHistoryRequest` (рекомендованная замена `iter_messages`)

Используйте следующий шаблон для гарантированного получения всех сообщений без преждевременной остановки и с контролем пауз:

```python
import asyncio
import time
from telethon.tl.functions.messages import GetHistoryRequest
from telethon.errors import FloodWaitError, ServerError

async def fetch_all_messages(client, entity, on_batch=None):
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
                limit=100,
                max_id=0,
                min_id=0,
                hash=0,
            ))
        except FloodWaitError as e:
            wait = e.seconds + 5
            print(f"FloodWait: {wait} сек")
            await asyncio.sleep(wait)
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
            break

        # Адаптивная пауза на основе времени ответа сервера
        if elapsed < 0.5:
            wait = 0.3
        elif elapsed < 2.0:
            wait = 0.7
        else:
            wait = elapsed * 0.5
        await asyncio.sleep(wait)

    return all_messages
```

### Проблема `reverse=True` в Telethon 1.42

При использовании `iter_messages(..., reverse=True)` итератор может преждевременно остановиться, если последнее сообщение имеет ID = 100.  
**Рекомендация:** получать сообщения от новых к старым (по умолчанию) и разворачивать список локально:  
```python
messages = await fetch_all_messages(client, entity)
messages.reverse()
```

## Takeout API: когда применять

Takeout-сессия (`account.initTakeoutSession`) **не увеличивает скорость передачи текста**, но **снижает частоту и длительность пауз**, вызванных тротлингом.  
Используйте её, если наблюдаете частые остановки на несколько минут при обычном парсинге.

### Корректный жизненный цикл

```python
async with client.takeout(
    contacts=False,
    users=True,
    chats=True,
    megagroups=True,
    channels=True,
    files=False,      # медиафайлы не нужны
    finalize=True,
) as takeout_client:
    async for message in takeout_client.iter_messages(chat):
        process(message)
```

### Обработка ошибки «Another takeout session is active»

```python
from telethon.tl.functions.account import FinishTakeoutSessionRequest

try:
    async with client.takeout(...) as tc:
        ...
except Exception as e:
    if "Another takeout" in str(e) or "TAKEOUT_INIT" in str(e):
        await client(FinishTakeoutSessionRequest(success=False))
        await asyncio.sleep(5)
        raise RuntimeError("Зависшая Takeout-сессия закрыта, повторите.")
    raise
```

### Принудительное закрытие при выходе из приложения (PySide6)

```python
from PySide6.QtWidgets import QApplication
from telethon.tl.functions.account import FinishTakeoutSessionRequest

def setup_takeout_cleanup(client, loop):
    def on_quit():
        async def finish():
            try:
                await client(FinishTakeoutSessionRequest(success=False))
            except Exception:
                pass
        asyncio.run_coroutine_threadsafe(finish(), loop).result(timeout=5)
    QApplication.instance().aboutToQuit.connect(on_quit)
```

## Интеграция asyncio и PySide6

### Рекомендованная модель: отдельный поток с единым event loop

Создайте **один** фоновый `QThread`, в котором работает `asyncio` event loop.  
Все вызовы Telethon направляйте в этот поток через `asyncio.run_coroutine_threadsafe()`.

```python
class TelegramEventLoopThread(QThread):
    def __init__(self):
        super().__init__()
        self._loop = None
        self._ready = threading.Event()

    def run(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._ready.set()
        self._loop.run_forever()

    def get_loop(self):
        self._ready.wait()
        return self._loop

    def submit(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    def stop(self):
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)
        self.wait()
```

### Воркер парсинга с поддержкой паузы / остановки

```python
class ParseWorker(QObject):
    progress = Signal(int, int)
    finished = Signal()
    error = Signal(str)

    def __init__(self, client, entity, loop_thread):
        super().__init__()
        self._client = client
        self._entity = entity
        self._loop_thread = loop_thread
        self._pause = asyncio.Event()
        self._pause.set()
        self._stop = asyncio.Event()

    def start(self):
        self._loop_thread.submit(self._run())

    def pause(self):
        self._loop_thread.get_loop().call_soon_threadsafe(self._pause.clear)

    def resume(self):
        self._loop_thread.get_loop().call_soon_threadsafe(self._pause.set)

    def stop(self):
        loop = self._loop_thread.get_loop()
        loop.call_soon_threadsafe(self._stop.set)
        loop.call_soon_threadsafe(self._pause.set)  # разблокировать

    async def _run(self):
        try:
            offset_id = 0
            while not self._stop.is_set():
                await self._pause.wait()
                if self._stop.is_set():
                    break

                result = await self._client(GetHistoryRequest(...))
                if not result.messages:
                    break

                await self._save_batch(result.messages)
                offset_id = result.messages[-1].id
                self.progress.emit(offset_id, 0)

                if len(result.messages) < 100:
                    break
                await asyncio.sleep(1.0)
        except Exception as e:
            self.error.emit(str(e))
        finally:
            self.finished.emit()
```

## SQLite: синхронизация и блокировки

### Основные правила

- **Один `.session` файл = один экземпляр `TelegramClient` в один момент времени**.  
  Одновременное открытие из разных потоков вызывает `AUTH_KEY_DUPLICATED`.

- Используйте **WAL-режим** и увеличенный `busy_timeout`:

```python
conn = sqlite3.connect(db_path, timeout=30, check_same_thread=False)
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA synchronous=NORMAL")
conn.execute("PRAGMA busy_timeout=30000")
```

- **Не полагайтесь на `QTimer.singleShot(300)`** для ожидания закрытия клиента.  
  Вместо этого дождитесь сигнала `client_closed`, отправленного **после** завершения `await client.disconnect()` в том же event loop.

## Forum-топики и комментарии к постам канала

### Получение названия топика

```python
from telethon.tl.functions.channels import GetForumTopicsByIDRequest

async def get_topic_title(client, channel, topic_id):
    try:
        result = await client(GetForumTopicsByIDRequest(
            channel=channel,
            topics=[topic_id]
        ))
        if result.topics:
            return result.topics[0].title
    except Exception:
        pass
    return "General" if topic_id == 1 else f"Ветка #{topic_id}"
```

### Получение сообщений конкретного топика

```python
async for msg in client.iter_messages(channel, reply_to=topic_id):
    ...
```

### Комментарии к постам канала (отдельный процесс)

Комментарии **не являются обычными сообщениями группы обсуждений**.  
Для их получения необходимо для каждого поста выполнить:

```python
from telethon.tl.functions.messages import GetDiscussionMessageRequest

async def get_comments(client, channel, post_id):
    try:
        disc = await client(GetDiscussionMessageRequest(
            peer=channel,
            msg_id=post_id
        ))
        group_peer = disc.messages[0].peer_id
        top_msg_id = disc.max_id
        async for comment in client.iter_messages(group_peer, reply_to=top_msg_id):
            yield comment
    except Exception:
        # у поста может не быть обсуждения
        return
```

- `linked_chat_id` канала указывает на привязанную группу, но не даёт прямого доступа к комментариям.  
- `get_participants()` возвращает участников самой группы, а не список авторов комментариев к постам.

## Прогрев сессии и снижение FloodWait

Telegram оценивает «репутацию» сессии по совокупности факторов:  
длительность жизни, разнообразие действий, стабильность IP.

**Практические рекомендации:**
1. После создания сессии дайте ей «отлежаться» 24–48 часов, периодически вызывая `get_dialogs()`.
2. Начинайте парсинг с небольших чатов (до 1000 сообщений).
3. Избегайте резкого старта с 50 000+ сообщений на новой сессии — получите `FloodWait` на несколько часов.
4. Используйте **MTProto-прокси** (наилучший вариант для обхода блокировок и сохранения стабильного IP).

## Что точно не помогает ускорить парсинг

| Ошибочное действие | Почему бесполезно |
|--------------------|-------------------|
| `limit=100` в `iter_messages` | Ограничивает общее количество сообщений, а не размер батча. |
| `wait_time=0` | Провоцирует серверный тротлинг. |
| Понижение уровня логирования | Накладные расходы на логгирование ничтожны. |
| Изменение `_DB_BATCH_SIZE` | Влияет только на дисковые операции. |
| Параллельные `GetHistoryRequest` | Невозможно — каждый запрос зависит от `offset_id` предыдущего. |
| Частая смена `.session` файла | Новые сессии тормозят сильнее. |
| Кастомные `device_model` / `app_version` | Telegram анализирует поведение, а не заголовки. |
| Использование `opentele` | Библиотека несовместима с Telethon 1.35+. Альтернатива — QR-авторизация или ручной экспорт session-строки. |

## Альтернативы Telethon после заморозки

Если текущий проект планируется поддерживать более 6–12 месяцев, рассмотрите миграцию на **Pyrofork** (активный форк Pyrogram).  
Основные отличия API:

| Telethon | Pyrofork |
|----------|----------|
| `client.iter_messages(entity)` | `client.get_chat_history(chat_id)` |
| `client.get_entity(id)` | `client.get_chat(id)` |
| `FloodWaitError` | `FloodWait` |

Оценочное время миграции для среднего приложения — 2–4 недели.

## Лимиты Telegram API (апрель 2026)

| Ограничение | Значение |
|-------------|----------|
| Сообщений за `GetHistoryRequest` | 100 (жёстко) |
| Рекомендуемая частота запросов | ~30 в секунду (динамический тротлинг) |
| Таймаут Takeout-сессии | 24–48 часов (эмпирически) |
| `AUTH_KEY_DUPLICATED` | При параллельном использовании одного `.session` |

---

*Инструкция составлена на основе итогового отчёта по высокопроизводительной архивации Telegram и отражает актуальное состояние технологий на апрель 2026 года.*
```