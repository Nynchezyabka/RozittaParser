ROZITTA PARSER
Комплексный технический аудит
Performance Engineering  ·  Architecture Analysis  ·  Competitive Benchmarking
Версия 3 — расширенная  (включает сравнение с tdl-master / Go)

Контекст: версии и точка отсчёта
1.1 Хронология трёх веток Rozitta
ПорядокАрхивУсловное названиеХарактеристика1 — прототипRozitta_TG_ParserClaude+gemini2.zipClaude/GeminiМонолит backend.py. Источник всех последующих веток.2 — рефакторингRozitta_v4.zipV4 (модульная)Feature-based архитектура. Лучшая структура, ряд new-регрессов.3 — независимаяrozitta_parser_v0.0.2_src.zipv0.0.2Параллельная ветка от того же прототипа. Лучший batch I/O.
1.2 Внешний ориентир: tdl-master (Go/gotd)
В рамках параллельного аудита (audit_report.docx, 17 февраля 2026) был проанализирован tdl-master — production-grade CLI-инструмент на Go с той же нишей «Telegram data extraction». Его архитектурные решения использованы как эталон в разделах 5–7 данного отчёта.

ПараметрRozitta (все версии)tdl-masterЯзык / стекPython 3.x, Telethon, PySide6, SQLiteGo 1.21+, gotd/td, Cobra CLI, BoltDBЦелевая аудиторияDesktop GUI, конечный пользовательCLI / headless / developer toolingПараллельность загрузки❌ Sequential (все версии)✅ DC-aware goroutines + errgroupFloodWait стратегия⚠️ Ручной sleep (V4 — лучший вариант)✅ Middleware backoff.RetryNotifyТесты❌ 0 строк тестов✅ 1 586 строк integration тестовProgress bar реальный❌ Signal progress всегда = 0✅ bytes/s, ETA, pinned statsMulti-account❌ Один аккаунт✅ Namespace -n флагQR-авторизация❌ Нет✅ ASCII QR с live-токен рефрешемФильтрация сообщений⚠️ Дата / пользователь / топик✅ expr-lang: любые boolean-выраженияУникальные фичи Rozitta✅ MergerService, DOCX 4 режима, форумы, GUI❌ Отсутствуют
Вывод: Rozitta имеет незаменимые продуктовые преимущества (DOCX, склейка, GUI). Критические «долги» — последовательная загрузка медиа, отсутствие тестов и неработающий прогресс-бар — являются конкретными целями для следующих итераций.

2. Root Cause Analysis — полный список
8 проблем в порядке убывания влияния на скорость и стабильность.

RCA-1 ❌ Прототип: новое DB-соединение на каждый INSERT
ПараметрЗначениеВерсияПрототип (Claude/Gemini)Файлbackend.py, строки 148–195СерьёзностьКРИТИЧНО — главный тормоз на больших чатах
save_message() каждый раз вызывает sqlite3.connect() → INSERT → commit() → close(). На 5 000 сообщений это 5 000 полных циклов открытия и закрытия соединения. Каждый синхронный commit() внутри asyncio event loop блокирует обработку входящих TCP-пакетов Telethon, что throttle-ит download_media.

# Прототип — backend.py, строки 176–195:
def save_message(self, message_data):
    conn = self._get_connection()   # ← НОВОЕ соединение каждый раз
    cursor.execute('INSERT OR REPLACE ...')
    conn.commit()                   # ← fsync = блокировка event loop
    conn.close()                    # ← закрыть

def _get_connection(self):  # строка 148
    return sqlite3.connect(self.db_path, timeout=30.0)  # ← новый объект

Исправление в потомках: v0.0.2 — персистентное соединение + batch 500 строк / 1 commit. V4 — персистентное через thread-local, но всё ещё 1 commit / сообщение (→ RCA-5).

RCA-2 ❌ Прототип: await get_sender() на каждое сообщение
ПараметрЗначениеВерсияПрототип (Claude/Gemini)Файлbackend.py, строки 478, 324, 386СерьёзностьКРИТИЧНО — лишний Telegram API round-trip на каждое сообщение
await msg.get_sender() инициирует отдельный сетевой запрос к Telegram DC, если объект не кэширован. В iter_messages Telethon автоматически наполняет entity-кэш — явный get_sender() избыточен в 99% случаев. При 1 000 сообщений = 1 000 лишних round-trip.

# Прототип — backend.py, строка 478:
async for msg in self.client.iter_messages(entity, **kwargs):
    sender = await msg.get_sender()  # ← API-запрос к Telegram DC

# Правильный паттерн (v0.0.2, V4):
    sender = getattr(message, 'sender', None)  # ← из кэша, без await

Исправление в потомках: v0.0.2 и V4 читают message.sender из кэша Telethon без сетевых запросов.

RCA-3 ❌ Прототип: все посты канала в RAM перед обработкой
ПараметрЗначениеВерсияПрототип (Claude/Gemini)Файлbackend.py, строки 310–321СерьёзностьВЫСОКОЕ — OOM на каналах с 5 000+ постов
В _download_comments() прототип сначала загружает весь список постов в память (posts = []), затем делает второй проход по нему. 10 000 постов ≈ 20–100 MB RAM в Telethon Message-объектах.

# Прототип — backend.py, строки 310–321:
posts = []
async for msg in self.client.iter_messages(channel_entity, limit=None):
    posts.append(msg)              # ← всё в RAM

for idx, post in enumerate(posts, 1):  # ← второй проход
    sender = await post.get_sender()    # ← + API-запрос на каждый пост
    self.db.save_message({...})         # ← + новое DB-соединение

Исправление в потомках: v0.0.2 и V4 обрабатывают сообщения в streaming-режиме прямо внутри async for.

RCA-4 ❌ Прототип: нет обработки FloodWaitError
ПараметрЗначениеВерсияПрототип (Claude/Gemini)Файлbackend.py: все except-блокиСерьёзностьВЫСОКОЕ — FloodWait = аварийное завершение парсинга
Ни один из методов прототипа не ловит TelethonFloodWaitError явно. Исключение либо проглочено тихим except pass, либо залогировано как строка и игнорировано. При FloodWait от Telegram-сервера итерация продолжается немедленно и получает следующий FloodWait — каскад ошибок.

# Прототип — backend.py, строки 507–509:
    except Exception as e:
        self.log(f'⚠️ Ошибка скачивания файла: {e}')
        # FloodWaitError = просто строка в лог, нет sleep(), нет retry

# Прототип — строка 408:
    except Exception as e:
        pass  # ← FloodWait при скачивании медиа — тихо игнорируется

Лучшая реализация (V4): Ловит TelethonFloodWaitError отдельно, делает asyncio.sleep(seconds + 3), сохраняет last_message_id и перезапускает итератор с нужного места — без потери данных.

RCA-5 ⚠️ V4: per-message commit через _cursor()
ПараметрЗначениеВерсияV4 (модульная)Файлcore/database.py строки 186–210, features/parser/api.py строка ~303СерьёзностьСРЕДНЕЕ — лучше прототипа (нет reconnect), хуже v0.0.2 (нет batch)
V4 использует персистентное соединение (прогресс), но _cursor() context manager делает conn.commit() после каждого insert_message(). Это 1 fsync per сообщение. v0.0.2 делает 1 commit на 500 сообщений — разница в скорости записи до 500×.

# V4 — core/database.py, строки 200–204:
@contextmanager
def _cursor(self):
    cursor = conn.cursor()
    yield cursor
    conn.commit()   # ← 1 fsync ПОСЛЕ КАЖДОГО insert_message()

# v0.0.2 — features/parser/api.py, строки 279–285:
if len(messages_batch) >= 500:
    insert_fn(messages_batch)   # ← 1 commit на 500 строк
    messages_batch.clear()

RCA-6 ❌ V4: рассинхронизация сигнатур ui.py ↔ api.py
ПараметрЗначениеВерсияV4 (модульная)Файлfeatures/parser/ui.py строки ~819–823 vs api.py строки ~167–173СерьёзностьБЛОКИРУЮЩЕЕ — TypeError при запуске парсинга
# ui.py передаёт:
service = ParserService(client=..., cfg=self._cfg, ...)

# api.py принимает:
def __init__(self, client, db, log=None):  # нет cfg!

RCA-7 ⚠️ Все версии: последовательное скачивание медиа
ПараметрЗначениеВерсияПрототип, V4, v0.0.2ФайлЦикл iter_messages во всех версияхСерьёзностьСРЕДНЕЕ — упущенная оптимизация, не регресс. Tdl-master: параллельно через goroutines.
Все версии скачивают медиафайлы строго последовательно. Telethon поддерживает параллельные download_media в рамках одного клиента через asyncio.create_task() + asyncio.Semaphore. tdl-master реализует DC-aware параллельную загрузку через Go errgroup с пулом по датацентрам Telegram.

# Текущий паттерн (все версии):
async for message in iter_messages(...):
    await download_media(message)  # ← ждём завершения перед следующим

# Оптимум (asyncio.Semaphore — см. раздел 4):
sem = asyncio.Semaphore(3)
async with sem:
    await download_media(message)  # ← 3 параллельных загрузки

RCA-8 ⚠️ v0.0.2: двойной проход по сообщениям
ПараметрЗначениеВерсияv0.0.2Файлfeatures/parser/api.py, строки ~161–172СерьёзностьНИЗКОЕ — удваивает нагрузку на API, не критично для скорости
# Проход 1 — подсчёт для прогресс-бара в процентах:
async for m in client.iter_messages(entity, ...): total_messages += 1

# Проход 2 — реальная обработка:
async for message in client.iter_messages(entity, ...): ...


3. Расширенный анализ: проблемы выявленные при сравнении с tdl-master
Следующие критерии выявлены в ходе сравнительного аудита context_core3 vs tdl-master и ранее не рассматривались.

3.1 ❌ Progress Signal всегда равен 0
ПараметрЗначениеЗатронутоВсе версии RozittaФайлfeatures/parser/ui.py — Signal progress(int) объявлен, но не эмититсяСерьёзностьUX — пользователь видит бесконечный spinner без информации о прогрессе
В ParseWorker объявлен progress = Signal(int), но в цикле обработки сообщений emit(n) не вызывается ни в одной версии. tdl-master отображает real-time bytes/s, ETA, pinned CPU stats через go-pretty. Пользователи Rozitta не получают обратной связи при парсинге чата с 10 000 сообщений.

Решение: двухфазный прогресс — подробнее в разделе 5 (Merge Strategy).

3.2 ❌ Ручной retry-loop вместо декоратора/middleware
ПараметрЗначениеЗатронутоV4 (лучший вариант), v0.0.2 (частичный), прототип (нет)Файлfeatures/parser/api.py — retry реализован in-line в 4 местахСерьёзностьТЕХДОЛГ — дублирование кода, линейный backoff неоптимален
V4 реализует retry-логику вручную в каждом месте: while attempts <= _MAX_RETRIES с фиксированным base_delay * attempt (линейный backoff). tdl-master выносит это в middleware-слой (recovery.go): backoff.RetryNotify с экспоненциальным backoff — единый механизм для всех Telegram-вызовов.

Решение: вынести retry в декоратор core/utils/retry.py — устранит дублирование из 4 мест в parser/api.py и сделает backoff экспоненциальным (1s, 2s, 4s, 8s вместо 5s, 10s, 15s).

3.3 ❌ Отсутствие тестов (0 строк)
ПараметрЗначениеЗатронутоВсе версии RozittaФайлtests/ папки существуют, но пустыеСерьёзностьКРИТИЧЕСКИЙ РИСК — рефакторинг без regression coverage
В репозитории есть папки tests/, но ни одного тестового файла с реальными тестами. tdl-master: 1 586 строк integration тестов с mock-сервером testserver. Это означает: любой из рекомендуемых рефакторингов (batch insert, retry middleware, progress bar) невозможно верифицировать автоматически.

Минимальный план: pytest + unittest.mock для Telethon. Приоритет тестирования: DBManager.insert_messages_batch() → ParserService._download_media() → MergerService.merge_messages() → AuthService.sign_in().

3.4 ❌ Фиксированные фильтры без expression engine
ПараметрЗначениеЗатронутоВсе версии RozittaФайлfeatures/parser/api.py — CollectParamsСерьёзностьПРОДУКТОВОЕ — опытные пользователи не могут задать сложные условия
Rozitta поддерживает фильтрацию только по дате, пользователю и топику. tdl-master использует expr-lang — пользователь пишет произвольные boolean-выражения: 
# tdl-master filter examples:
code.text contains 'keyword' && code.date > '2024-01-01'
code.media.type == 'video' && code.views > 100

# В Rozitta — только:
date_from='2024-01-01', user_id=12345, topic_id=7

Решение: добавить filter_expression: Optional[str] = None в CollectParams + безопасный eval через библиотеку simpleeval. В UI — необязательное текстовое поле «Расширенный фильтр».

3.5 ⚠️ Нет QR-авторизации и импорта .tdata
ПараметрЗначениеЗатронутоВсе версии RozittaФайлfeatures/auth/api.pyСерьёзностьПРОДУКТОВОЕ — популярный способ входа недоступен
AuthService поддерживает только Phone+Code+2FA. tdl-master добавляет: QR-авторизацию (ASCII QR с live-рефрешем токена), импорт из Telegram Desktop (.tdata с Passcode), namespace-изоляцию для нескольких аккаунтов.

Решение для следующей версии: QR-авторизация через client.qr_login() (поддерживается Telethon 1.x). Добавить отдельный AuthMethod enum в AuthService: Phone | QR | Session.

3.6 ⚠️ Нет CI/CD и отсутствует Docker
ПараметрЗначениеЗатронутоВсе версии RozittaСерьёзностьОПЕРАЦИОННЫЙ ДОЛГ — ручные релизы, нет автоматической проверки
tdl-master: GitHub Actions с build/test/release/Docker + dependabot. Rozitta: нет .github/workflows. Каждый релиз — ручной процесс. Без CI каждое исправление из плана Merge Strategy (раздел 5) требует ручной проверки.


4. Feature Comparison — расширенная таблица

КритерийПрототип (Claude/Gemini)V4 (модульная)v0.0.2 (независимая)── ПРОИЗВОДИТЕЛЬНОСТЬ ──────────────DB: тип соединения❌ Новое на каждый INSERT✅ Персистентное thread-local✅ Персистентное thread-localDB: batch-вставка❌ 1 commit / сообщение⚠️ 1 commit / сообщение (persistent)✅ 1 commit / 500 сообщенийget_sender() паттерн❌ await get_sender() (API round-trip)✅ message.sender (из кэша)✅ message.sender (из кэша)Параллельная загрузка медиа❌ Последовательно❌ Последовательно❌ ПоследовательноПосты комментариев в RAM❌ Весь список в memory✅ Streaming в async for✅ Streaming в async forДвойной проход по сообщениям✅ Нет✅ Нет❌ Есть (count + collect)── НАДЁЖНОСТЬ ──────────────────────FloodWait обработка❌ Нет (except pass)✅ Sleep + restart с last_id⚠️ Sleep, нет restart iteratorRetry backoff❌ Нет retry⚠️ Линейный (5s, 10s, 15s)⚠️ МинимальныйRetry как middleware/декоратор❌ Нет❌ In-line, 4 копии❌ In-lineТипизированные исключения❌ Только Exception / pass✅ Иерархия 14 исключений⚠️ ЧастичнаяWAL + busy_timeout⚠️ WAL, timeout=30s✅ WAL + timeout=60s + PRAGMA✅ WAL + timeout=5s── UX / ПРОДУКТ ────────────────────Progress bar реальный❌ Нет эмита (только счётчик в логе)❌ Signal = 0 (объявлен, не работает)⚠️ % через двойной проходDownloadTracker (инкремент)❌ Нет❌ Нет✅ downloaded.txtФильтр: expression engine❌ Нет❌ Дата/юзер/топик❌ Дата/юзер/топикQR-авторизация❌ Нет❌ Нет❌ НетMulti-account / namespace❌ Нет❌ Нет❌ Нет── АРХИТЕКТУРА ─────────────────────Структура кода⚠️ Монолит (backend.py 845 стр.)✅ Feature-based, SOLID✅ Feature-based, SOLIDТипизация / dataclass❌ Минимальная✅ Полная✅ ПолнаяСогласованность ui ↔ api✅ Согласована❌ cfg-рассинхронизация✅ СогласованаТесты❌ 0 строк❌ 0 строк❌ 0 строкCI/CD❌ Нет❌ Нет❌ Нет

5. Merge Strategy — расширенный пошаговый план
База: архитектура V4 (лучшая структура). Переносим batch I/O из v0.0.2, добавляем решения из практики tdl-master.

Шаг 1 (P0 — БЛОКИРУЮЩЕЕ): Исправить cfg-рассинхронизацию V4
Привести сигнатуру ParseWorker._collect() в ui.py к сигнатуре ParserService.__init__() в api.py. До этого V4 не запускается. Время: < 1 часа.

Шаг 2 (P0 — СРОЧНО): Batch-вставка из v0.0.2 → V4
1. Добавить insert_messages_batch() в core/database.py (взять из v0.0.2 без изменений).
2. Заменить in-loop вызов _process_message() на буфер:

_batch: list[dict] = []

async for message in self._client.iter_messages(...):
    row  = self._extract_row(message, ...)       # без I/O
    path = await self._download_media(...)       # сеть
    if path: row.update({'media_path': path, ...})
    _batch.append(row)

    if len(_batch) >= 200:
        self._db.insert_messages_batch(_batch)
        _batch.clear()

if _batch:
    self._db.insert_messages_batch(_batch)   # финальный flush

Шаг 3 (P0 — СРОЧНО): Реальный progress bar
Исправляет «progress Signal = 0» из пункта 3.1. Двухфазная реализация:
3. До iter_messages — получить приближение total через первый быстрый запрос (GetHistory count=0) или из кэша диалога. Emit progress(5).
4. В цикле — emit progress(5 + int(processed / total * 85)).
5. После завершения — emit progress(95) → 100.

# В ParseWorker._collect() — добавить:
self.progress.emit(5)   # начало

# В цикле iter_messages:
if self._msg_count % 50 == 0:
    pct = 5 + int(self._msg_count / estimated_total * 85)
    self.progress.emit(min(pct, 90))

self.progress.emit(100) # завершение

Шаг 4 (P1): Retry декоратор — устраняет дублирование
Вынести retry-логику из 4 мест в parser/api.py в core/utils/retry.py. Сделать backoff экспоненциальным по образцу tdl-master:

# core/utils/retry.py — новый файл:
import asyncio, functools
from telethon.errors import FloodWaitError as TelethonFWE

def async_retry(max_attempts=3, base_delay=1.0, backoff=2.0):
    def decorator(fn):
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            for attempt in range(1, max_attempts + 1):
                try:
                    return await fn(*args, **kwargs)
                except TelethonFWE as e:
                    await asyncio.sleep(e.seconds + 3)
                except OSError as e:
                    if attempt >= max_attempts: raise
                    await asyncio.sleep(base_delay * (backoff ** (attempt - 1)))
        return wrapper
    return decorator

# Использование:
@async_retry(max_attempts=3, base_delay=1.0, backoff=2.0)
async def _download_media(self, message, target_path):
    return await message.download_media(file=target_path)

Шаг 5 (P1): DownloadTracker из v0.0.2
Перенести класс DownloadTracker в core/utils.py. Добавить в collect_data() проверку перед скачиванием. Даёт инкрементальный режим — повторный парсинг пропускает уже скачанные файлы.

Шаг 6 (P2): Параллельное скачивание медиа
asyncio.Semaphore(3) + create_task(). Детальный пример — в разделе 6.

Шаг 7 (P2): Убрать двойной проход из v0.0.2
Заменить предварительный count на running counter. Прогресс показывать как абсолютное число сообщений.

Шаг 8 (P2): Expression filter engine
Добавить filter_expression: Optional[str] = None в CollectParams. Использовать simpleeval:

# В CollectParams добавить:
filter_expression: Optional[str] = None  # напр. "'keyword' in text"

# В _process_message перед insert:
if params.filter_expression:
    from simpleeval import simple_eval
    env = {'text': message.text or '', 'sender': sender_name,
           'date': message.date, 'has_media': bool(message.media)}
    if not simple_eval(params.filter_expression, names=env):
        return None  # пропустить сообщение

Шаг 9 (P3): QR-авторизация
Добавить AuthMethod enum и ветку QR в AuthService.sign_in():

# features/auth/api.py — добавить:
from enum import Enum
class AuthMethod(Enum):
    PHONE = 'phone'
    QR    = 'qr'

# В sign_in() — новая ветка:
if method == AuthMethod.QR:
    qr_login = await client.qr_login()
    # Эмитировать qr_login.url в UI для отображения
    await qr_login.wait(timeout=120)
    return await AuthService.get_me(client, log)

Шаг 10 (P3): Минимальный CI с pytest
6. Установить pytest, pytest-asyncio, unittest.mock.
7. Создать tests/test_database.py — тест insert_messages_batch() с in-memory SQLite.
8. Создать tests/test_merger.py — тест MergerService.merge_messages() с фиктивными данными.
9. Добавить .github/workflows/tests.yml — запуск на push/PR.


6. Оптимизированный метод скачивания
Образец объединяет все улучшения: batch I/O + параллельная загрузка + retry декоратор + DownloadTracker + progress emit.

6.1 Ядро оптимизированного collect_data()
async def collect_data(self, params: CollectParams) -> CollectResult:
    # --- семафор для параллельных загрузок (Semaphore(3) — безопасный лимит) ---
    sem  = asyncio.Semaphore(3)

    # --- инкрементальный трекер (из v0.0.2) ---
    tracker = DownloadTracker(params.output_dir, self._chat_title, normalized_id)

    _batch:       list[dict]  = []
    _tasks:       list[tuple] = []   # (asyncio.Task, batch_row_index)
    total_est:    int         = 0    # приближённое число сообщений
    processed:    int         = 0

    # --- быстрый count для прогресс-бара (без двойного прохода) ---
    try:
        history = await self._client.get_messages(entity, limit=1)
        total_est = getattr(history, 'total', 0)
        self._log(f'📊 Примерно сообщений: {total_est}')
        self._progress(5)
    except Exception:
        pass  # total_est = 0 → прогресс без %

    async def _dl(message, target) -> str | None:
        async with sem:
            return await self._download_media(message, target)

    async def _flush():
        if _tasks:
            results = await asyncio.gather(*[t for t, _ in _tasks],
                                           return_exceptions=True)
            for (_, idx), res in zip(_tasks, results):
                if isinstance(res, str) and res:
                    _batch[idx]['media_path'] = res
                    _batch[idx]['file_size']  = os.path.getsize(res)
                    self._media_count += 1
            _tasks.clear()
        if _batch:
            self._db.insert_messages_batch(_batch)   # ← 1 commit / 200 msgs
            _batch.clear()

    last_id, attempts = None, 0
    while attempts <= _MAX_RETRIES:
        try:
            async for message in self._client.iter_messages(
                entity, max_id=last_id - 1 if last_id else 0, reverse=False
            ):
                last_id = message.id

                if cutoff_date and ensure_aware_utc(message.date) < cutoff_date: break
                if params.user_id and message.sender_id != params.user_id: continue
                if tracker.is_downloaded(message.id): continue

                # expression filter (шаг 8)
                if params.filter_expression:
                    if not _eval_filter(params.filter_expression, message): continue

                row = self._extract_row(message, ...)   # без I/O

                if self._should_download(message, params.media_filter):
                    row['file_type'] = self._detect_media_type(message)
                    task = asyncio.create_task(_dl(message, self._media_path(message)))
                    _tasks.append((task, len(_batch)))

                _batch.append(row)
                tracker.mark_downloaded(message.id)
                self._msg_count += 1
                processed += 1

                # прогресс
                if self._msg_count % MESSAGES_LOG_INTERVAL == 0:
                    self._log(f'📨 Обработано: {self._msg_count}')
                    if total_est:
                        pct = 5 + int(processed / total_est * 85)
                        self._progress(min(pct, 90))

                if len(_batch) >= 200:
                    await _flush()

            break  # нормальный выход из while

        except TelethonFloodWaitError as exc:
            await asyncio.sleep(exc.seconds + _FLOOD_BUFFER)
            attempts += 1   # last_id сохранён → рестарт с нужного места

    await _flush()   # финальный flush
    self._progress(100)

    return CollectResult(success=True, messages_count=self._msg_count, ...)

ВАЖНО: asyncio.create_task() и Semaphore(3) корректно работают в event loop, созданном QThread через asyncio.new_event_loop(). Limit=3 — безопасный предел для одного Telegram-аккаунта без риска DC rate-limit. Для задач свыше 5 параллельных соединений потребуется Takeout API (как в tdl-master).

7. Итоговая таблица задач

#ЗадачаИсточник решенияПриоритетОжидаемый эффект1Исправить cfg-рассинхронизацию ui↔apiV4 (fix)P0 — блокирующееУстранение TypeError при запуске2Batch insert (200 msg / 1 tx)v0.0.2 → V4P0 — срочно10–500× быстрее записи в БД3Реальный progress bar (emit %)tdl-master паттернP0 — срочноБазовый UX — пользователь видит прогресс4Retry декоратор (exponential backoff)tdl-master recovery.goP1Меньше дублирования, надёжнее при нестабильной сети5DownloadTracker инкрементальный режимv0.0.2 → V4P1Повторный парсинг без скачивания дублей6Убрать двойной проход (v0.0.2 fix)V4-логика → v0.0.2P12× меньше нагрузки на Telegram API7asyncio.Semaphore(3) параллельная загрузкаtdl-master паттернP22–4× быстрее на медиа-каналах8Expression filter (simpleeval)tdl-master expr-langP2Продвинутая фильтрация для опытных пользователей9QR-авторизация (client.qr_login)tdl-master QRP3Дополнительный способ входа10pytest + минимальный CI (GitHub Actions)tdl-master практикаP3 — но критически важно долгосрочноБезопасный рефакторинг без регрессий11PRAGMA wal_autocheckpoint = 100НовоеP3WAL-файл не растёт > 1.6MB
Задачи 1–3 (P0) решают 90% проблем производительности и UX. Задача 10 (тесты) — единственное, что отделяет проект от production-ready статуса независимо от всех оптимизаций.
Уникальные преимущества Rozitta (не требуют изменений)
Следующие возможности отсутствуют в tdl-master и являются конкурентным преимуществом — их нужно сохранять при любом рефакторинге:

ФункцияЦенностьMergerService (O(n) склейка сообщений)Уникальный алгоритм восстановления семантических блоков из фрагментированных Telegram-сообщенийDOCX экспорт с 4 режимами splitWord-документы с закладками, внутренними ссылками, вставкой изображений, разбивкой по дням/месяцам/постамLinked group commentsДвухпроходный сбор комментариев с привязкой post_id → channelForum topics: 3 стратегии topic_idreply_to_top_id → reply_to_msg_id → forum_topic flagGlassmorphism GUI + design tokensDesktop-приложение с дизайн-системой — 90% целевой аудитории не используют CLISQLite с полной схемой + WALPersistent storage с merge_group, topic, is_comment, from_linked_group14 типизированных исключенийПолная доменная модель ошибок для каждого слоя

Rozitta Parser — Комплексный технический аудит v3  ·  Performance Engineering + Competitive Analysis
