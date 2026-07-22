# CLAUDE.md — Карта проекта Rozitta Parser

## 📋 О проекте

**Название:** Rozitta Parser (Telegram Archiver)
**Версия:** 5.1 (v1.7.3 bugfix-релиз; Variant A-2 завершён; B1/B3 channel-sender merge; sender ID нормализация; smoke-test правило)
**Тип:** Desktop приложение (PySide6)
**Назначение:** Архивирование сообщений из Telegram чатов с созданием DOCX / JSON / MD / HTML документов

---

## 🎯 Основная функциональность

1. **Авторизация в Telegram** через Telethon (сессия и api_id/hash/phone сохраняются после входа)
2. **Импорт сессии из Telegram Desktop** — кнопка «🖥️ Импорт из tdata», без ввода кода (OpenTele2, ✅ BUG-18 исправлен)
3. **Загрузка списка чатов** (каналы, группы, форумы, диалоги — коллапсируемые секции; кэш 24ч)
4. **Парсинг сообщений** с фильтрацией по глубине / медиа / пользователю
5. **Скачивание медиа** в структурированные папки
6. **Склейка сообщений** (агрессивная эвристика: один автор, ≤60 сек)
7. **Генерация DOCX** с изображениями, ссылками, закладками
8. **Работа с форумами/топиками**
9. **Посты + комментарии** (канал + linked группа)
10. **Распознавание речи** (faster-whisper, ✅ РЕАЛИЗОВАНО — голосовые/кружочки → текст в DOCX)
11. **JSON экспорт** (✅ РЕАЛИЗОВАНО — плоский список объектов, совместим с NotebookLM)
12. **Markdown экспорт** (✅ РЕАЛИЗОВАНО — чистый формат для ИИ-инструментов)
13. **AI-split чанкинг** (✅ РЕАЛИЗОВАНО — разбивка MD/JSON на части по 300к слов)
14. **HTML экспорт** (✅ РЕАЛИЗОВАНО — чистая веб-страница с CSS-стилями)
15. **Thread mode** (✅ РЕАЛИЗОВАНО — экспорт веток с дедупликацией + дерево ответов):
    - HTML: CSS-дерево с `depth-N` классами, `margin-left` нарастает с глубиной
    - DOCX: линейный рендер, отступ 24pt × depth + маркер «↳» + «↩ в ответ на: [автор]»
    - Markdown: линейный рендер, отступ 4 пробела × depth + маркер «↳» + «*(в ответ на: автор)*»
    - JSON: плоский список с полями `depth` + `reply_to_author`, типы `thread_root` / `thread_reply`

---

## 🛠️ Технологический стек

- **Python 3.10+**
- **Telethon 1.35+** — Telegram MTProto API
- **SQLite3** — WAL режим
- **python-docx 1.1+** — Word документы
- **PySide6 6.6+** — Qt GUI
- **asyncio** — Асинхронность (QThread создаёт `new_event_loop`)
- **faster-whisper** — STT движок (✅ реализован, прямая подача .ogg/.mp4)
- **FFmpeg** — системная зависимость (для AudioConverter, опционально)
- **python-socks** — опциональная зависимость для SOCKS5/MTProto прокси (стабильность Telegram в регионах с ограничениями)

---

## 🌐 ПРОКСИ — Стабильность Telegram-соединения

Telegram нестабилен без VPN в ряде регионов. В приложении реализована поддержка прокси
через `AppConfig`. Пользователь выбирает вариант в настройках (или `config.json`).

### Варианты (по убыванию простоты):

| # | Вариант | Сложность | Изменения в коде |
|---|---------|-----------|-----------------|
| 1 | **Системный VPN** | Нулевая | Не нужны — Telethon идёт через системный стек |
| 2 | **SOCKS5 прокси**  | Минимальная | `proxy=` в `TelegramClient`, поле в `config.py` |
| 3 | **MTProto прокси** ✅ Рекомендуется| Минимальная | Аналогично SOCKS5, специфичен для Telegram |
| 4 | **HTTP прокси** | Минимальная | Работает хуже — MTProto поверх TCP, не HTTP-трафик |


### Схема данных прокси в `config.py`:

```python
@dataclass
class ProxyConfig:
    enabled: bool = False
    proxy_type: str = "socks5"    # "socks5" | "mtproto" | "http"
    host: str = "127.0.0.1"
    port: int = 1080
    username: str = ""            # опционально
    password: str = ""            # опционально
    secret: str = ""              # только для MTProto

class AppConfig:
    ...
    proxy: ProxyConfig = field(default_factory=ProxyConfig)
```

### Передача прокси в TelegramClient (во всех воркерах):

```python
# ✅ ПРАВИЛЬНО — применяется в каждом воркере при создании клиента:
import socks  # pip install python-socks

def _build_client(cfg: AppConfig) -> TelegramClient:
    proxy = None
    if cfg.proxy.enabled:
        if cfg.proxy.proxy_type == "socks5":
            proxy = (socks.SOCKS5, cfg.proxy.host, cfg.proxy.port,
                     True, cfg.proxy.username or None, cfg.proxy.password or None)
        elif cfg.proxy.proxy_type == "http":
            proxy = (socks.HTTP, cfg.proxy.host, cfg.proxy.port)
        elif cfg.proxy.proxy_type == "mtproto":
            # MTProto прокси — отдельный формат Telethon:
            proxy = ConnectionTcpMTProxyRandomizedIntermediate
            # + параметры передаются через connection_retries / server_address

    return TelegramClient(
        cfg.session_path,
        cfg.api_id_int,
        cfg.api_hash,
        proxy=proxy,
        connection_retries=5,
        retry_delay=2,
    )

# ❌ ЗАПРЕЩЕНО — создавать TelegramClient без учёта proxy из AppConfig
```

### UI — поле настроек прокси (SettingsPanel или отдельная вкладка):

```
ProxySection (collapse по умолчанию):
├── Toggle: "Использовать прокси"
├── Select: Тип [SOCKS5 | MTProto | HTTP]
├── Input: Хост (по умолчанию 127.0.0.1)
├── Input: Порт (по умолчанию 1080)
├── Input: Логин (опц.)
├── Input: Пароль (опц.)
└── [Проверить соединение] — тест-кнопка → AuthService.check_connection()
```

---

## 📂 Актуальная структура проекта

```
rozitta_parser/
│
├── main.py                          # ✅ Готов
├── config.py                        # ✅ Конфигурация (AppConfig, load/save_config)
├── claude.md                         # Карта проекта для AI
│
├── assets/                          # Медиа-ресурсы приложения
│   ├── rozitta_idle.png             # ✅ Аватар по умолчанию (80×80px, используется в CharSection)
│   └── rozitta_*.gif                # 🔜 Анимированные реакции (будут добавлены постепенно)
│                                    #    Список и поведение: см. AVATAR_ANIMATION_GUIDE.md
│
├── core/                            # ✅ Готова полностью
│   ├── __init__.py
│   ├── utils.py                     # finalize_telegram_id, sanitize_filename, ...
│   ├── database.py                  # DBManager: WAL, thread-local, retry, merge, get_thread_pairs
│   │                                #   Schema v2: sender_type column, PRAGMA user_version migrations
│   ├── logger.py                    # setup_logging, get_logger, set_level
│   ├── exceptions.py                # Полная иерархия ошибок
│   ├── merger.py                    # MergerService: O(n) склейка
│   ├── retry.py                     # ✅ @async_retry декоратор (P1-3)
│   │
│   ├── ui_shared/                   # ✅ Готова полностью
│   │   ├── __init__.py
│   │   ├── widgets.py               # StepperWidget, RozittaWidget, ModernCard, ...
│   │   ├── styles.py                # Цветовые константы, QSS, apply_style()
│   │   └── calendar.py              # DateRangeWidget
│   │
│   └── stt/                         # ✅ РЕАЛИЗОВАНО (2026-03-09)
│       ├── __init__.py
│       ├── audio_converter.py       # AudioConverter (FFmpeg pipeline, резервный)
│       ├── whisper_manager.py       # WhisperManager (Singleton faster-whisper)
│       └── worker.py                # STTWorker(QThread) — пакетная транскрипция
│
├── features/
│   ├── __init__.py
│   ├── auth/                        # ✅ Готова
│   │   ├── api.py                   # AuthService (build_client, sign_in, ...)
│   │   └── ui.py                    # AuthWorker QThread; save_config() после входа
│   │
│   ├── chats/                       # ✅ Готова (ПЕРЕРАБОТАН ui.py 2026-02-22)
│   │   ├── api.py                   # ChatsService, classify_entity()
│   │   │                            #   ⚠️ I9: убрать admin resolution (Variant A-2)
│   │   └── ui.py                    # ChatItemWidget, CollapsibleSection,
│   │                                #   CollapsibleChatsWidget, ChatsScreen,
│   │                                #   ChatsWorker, TopicsWorker
│   │
│   ├── parser/                      # ✅ Готова
│   │   ├── api.py                   # ParserService, CollectParams, CollectResult
│   │   │                            #   _get_sender_name (instance, from_id fallback)
│   │   │                            #   _extract_row_sync (instance method)
│   │   │                            #   C1/C2 fix (2026-05-27)
│   │   └── ui.py                    # ParseWorker QThread (собственный TelegramClient)
│   │
│   └── export/                      # ✅ Готова
│       ├── generator.py             # DocxGenerator + JsonGenerator + MarkdownGenerator + HtmlGenerator
│       │                            #   _dedup_thread_messages() — shared утилита дедупликации тредов
│       │                            #   Удалены: _add_context_block_to_doc, _format_thread_pair
│       │                            #   C3 fix: include_channel_senders=False (2026-05-27)
│       ├── xml_magic.py             # add_bookmark, add_internal_hyperlink, ...
│       └── ui.py                    # ExportWorker QThread, ExportParams
│
├── ui/
│   └── main_window.py               # ✅ MainWindow — цепочка Parse→STT→Export
│
└── tests/
    ├── test_core/
    │   ├── test_database.py         # DBManager: WAL, batch, upsert, transcriptions
    │   ├── test_merger.py           # MergerService edge cases
    │   └── test_utils.py            # finalize_telegram_id, DownloadTracker
    └── test_features/
        ├── test_export.py           # DocxGenerator, xml_magic
        └── test_parser.py           # collect_data с моками
```

> ⚠️ **Важно:** `ui_shared` расположен в `core/ui_shared/`, а **не** в `ui_shared/` в корне.
> Файлы в `ui_shared/` корня — legacy, не импортируются.

---

## 🗄️ Схема базы данных

### Таблица: `messages`
```sql
CREATE TABLE messages (
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
    merge_part_index   INTEGER,
    sender_type        TEXT    DEFAULT 'user'   -- Schema v2: "user" | "channel" | "deleted"
);
```

### Schema v2 миграция
- `PRAGMA user_version` используется для миграций
- v1→v2: добавлена колонка `sender_type TEXT DEFAULT 'user'`
- `sender_type` позволяет различать типы отправителей при экспорте и фильтрации
- `"user"` — обычный пользователь
- `"channel"` — сообщение от канала/чата (sender_id = chat_id)
- `"deleted"` — удалённый аккаунт

### Таблица: `transcriptions` (✅ реализована — 2026-03-09)
```sql
CREATE TABLE transcriptions (
    message_id  INTEGER NOT NULL,
    peer_id     INTEGER NOT NULL,
    text        TEXT    NOT NULL,
    model_type  TEXT    NOT NULL DEFAULT 'base',
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (message_id, peer_id)
);
```

---

## 🏷️ Принятые дизайнерские решения

### Variant A-2: Канал как участник
- Канал/чат включается в participant list как равноправный отправитель
- **Нет** резолва channel-sender → admin (ненадёжно, не соответствует отображению в Telegram)
- Сообщения от канала отображаются под именем канала, как в самом Telegram
- `sender_type` поле в DB позволяет различать типы отправителей
- При фильтрации по пользователю: `include_channel_senders = False` — канал не подтягивается автоматически
- **Следствие:** выбор конкретного человека в группе не покажет его сообщения от имени канала (sender_id=group_id). Для этого нужно выбрать канал как участника (I6)

### «По постам» — только для каналов
- Режим `split_mode="post"` имеет смысл только для broadcast-каналов
- Для групп (megagroups) кнопка «По постам» должна быть неактивна/серой
- Группы не имеют постов в том же смысле, что каналы

---

## 📡 Signals воркеров (Qt)

| Воркер | Сигналы |
|--------|---------|
| `AuthWorker` | `log_message(str)`, `auth_complete(object,object)`, `error(str)`, `request_input(str,str,bool)`, `character_state(str)` |
| `ChatsWorker` | `log_message(str)`, `chats_loaded(list)`, `error(str)`, `character_state(str)` |
| `TopicsWorker` | `log_message(str)`, `topics_loaded(dict)`, `error(str)`, `character_state(str)` |
| `ParseWorker` | `log_message(str)`, `progress(int)`, `finished(object)`, `error(str)`, `character_state(str)` |
| `ExportWorker` | `log_message(str)`, `export_complete(list)`, `error(str)`, `character_state(str)` |
| `STTWorker` | `log_message(str)`, `transcription_ready(int,str)`, `error(str)`, `progress(int)`, `finished()` |

> ⚠️ `auth_complete` передаёт `(None, user)` — client=None, он отключается внутри AuthWorker
> до эмита сигнала (защита от race condition на SQLite-сессии).

---

## 🔑 ChatsScreen API (features/chats/ui.py)

```python
# Ключевые классы:

ChatItemWidget(chat: dict, parent=None)
    # chat dict: {id, title, type, username, participants_count,
    #             linked_chat_id, ...}
    # Signals: clicked(dict), dclicked(dict), topics_clicked(int)
    # type: "channel" | "group" | "forum" | "private"

CollapsibleSection(chat_type: str, parent=None)
    # Один коллапсируемый блок (Каналы / Группы / Форумы / Диалоги)
    # Signals: item_clicked(dict), item_dclicked(dict), topics_clicked(int)

CollapsibleChatsWidget(parent=None)
    # QScrollArea с 4 секциями
    # Signals: item_selected(dict), item_activated(dict), topics_clicked(int)
    # Methods: populate(chats: List[dict]), filter_by_text(text: str)

ChatsScreen(cfg: AppConfig, parent=None)
    # Signals: chat_selected(dict), log_message(str),
    #          request_topics(int), refresh_requested()
    # Methods: load_chats(limit=200), inject_chats(chats), selected_chat()
```

---

## 📰 ТРЕБОВАНИЕ: Режим "Посты + Комментарии" (split=by_posts)

### Ожидаемое поведение

При выборе режима разделения **"Посты"** и включённом toggles **"Скачивать комментарии"**:

- Источник постов: **broadcast channel** (основной канал)
- Источник комментариев: **linked discussion group** (привязанная супергруппа)
- Связь: через `GetDiscussionMessageRequest(peer=channel, msg_id=post_id)`

### ⚠️ Ограничение: только для каналов

Режим «По постам» не имеет смысла для групп (megagroups) — у групп нет постов.
Кнопка должна быть неактивна при выбранной группе. См. I3.

### Структура выходных файлов

**Один DOCX = один пост канала + все его комментарии.**
```
output/
└── Название канала/
    ├── Post_001_[дата].docx
    ├── Post_002_[дата].docx
    └── ...
```

---

## 🧵 ТРЕБОВАНИЕ: Thread mode (✅ РЕАЛИЗОВАНО)

### Архитектура дедупликации тредов

При экспорте веток (thread mode) `get_thread_pairs()` возвращает пары `(context→reply)`.
Одно сообщение может входить в несколько пар (как reply в одной и context в другой),
что приводило к дублированию. Решение — общая утилита `_dedup_thread_messages()`:

```python
# _dedup_thread_messages(pairs) → [(row, depth, reply_author), ...]
#
# 1. Собирает все уникальные сообщения из всех пар (по message_id)
# 2. Вычисляет depth (глубину в дереве ответов):
#    - root сообщение (ни на что не отвечает) → depth=0
#    - ответ на root → depth=1
#    - ответ на ответ → depth=2, и т.д.
# 3. Определяет reply_to_author — автор сообщения, на которое ответили
# 4. Возвращает плоский список без дубликатов
```

### Рендер по форматам

| Формат | Стиль рендера | Отступ | Маркер ответа |
|--------|---------------|--------|---------------|
| **HTML** | CSS-дерево | `margin-left` через классы `depth-0`..`depth-5` | «↳ в ответ на: [автор]» |
| **DOCX** | Линейный | 24pt × depth + `↳` | «↩ в ответ на: [автор]» |
| **Markdown** | Линейный | 4 пробела × depth + `↳` | *(в ответ на: автор)* |
| **JSON** | Плоский список | Поле `depth` (int) | Поле `reply_to_author` (str), `type`: `thread_root` / `thread_reply` |

### Удалённые устаревшие методы

При реализации tree-based рендера следующие методы стали ненужными и удалены:
- `DocxGenerator._add_context_block_to_doc` — заменён на dedup + linear render
- `MarkdownGenerator._format_thread_pair` — заменён на dedup + linear render

---

## 🧷 ПРАВИЛА КОДИРОВАНИЯ (строго соблюдать)

### 1. FormatRow — независимые toggle-чипы (⚠️ НЕ radio-group)

```python
# ✅ ПРАВИЛЬНО — каждая кнопка независима:
self.btn_docx = QPushButton("DOCX")
self.btn_json = QPushButton("JSON")
self.btn_md   = QPushButton("MD")
self.btn_html = QPushButton("HTML")
for btn in [self.btn_docx, self.btn_json, self.btn_md, self.btn_html]:
    btn.setCheckable(True)
    btn.setChecked(False)
self.btn_docx.setChecked(True)  # по умолчанию DOCX активен

# Сбор выбранных форматов:
def _get_export_formats(self) -> list[str]:
    fmt = []
    if self.btn_docx.isChecked(): fmt.append("docx")
    if self.btn_json.isChecked():  fmt.append("json")
    if self.btn_md.isChecked():    fmt.append("md")
    if self.btn_html.isChecked():  fmt.append("html")
    return fmt or ["docx"]  # fallback

# ❌ ЗАПРЕЩЕНО — не использовать QButtonGroup с setExclusive(True)
```

### 2. AI-split чанкинг — только MD и JSON

```python
# ✅ ПРАВИЛЬНО — ai_split НЕ влияет на DOCX:
if "docx" in formats:
    gen = DocxGenerator(db=db, output_dir=p.output_dir)
    files = gen.generate(...)          # без ai_split
    all_files.extend(files)

if "json" in formats:
    jgen = JsonGenerator(db=db, output_dir=p.output_dir)
    paths = jgen.generate(..., ai_split=p.ai_split)   # с ai_split
    all_files.extend(paths)

if "md" in formats:
    mdgen = MarkdownGenerator(db=db, output_dir=p.output_dir)
    paths = mdgen.generate(..., ai_split=p.ai_split)  # с ai_split
    all_files.extend(paths)

# ❌ ЗАПРЕЩЕНО — передавать ai_split в DocxGenerator
```

### 3. Avatar в CharSection — rozitta_idle.png

```python
# ✅ ПРАВИЛЬНО — загрузка статичного аватара:
self.avatar_label = QLabel()
self.avatar_label.setFixedSize(80, 80)
pixmap = QPixmap("assets/rozitta_idle.png").scaled(
    80, 80, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
)
self.avatar_label.setPixmap(pixmap)
self.avatar_label.setStyleSheet("border-radius: 40px; overflow: hidden;")
```

### 4. Signal(dict) — запрещено

```python
# ✅ ПРАВИЛЬНО:
Signal(object)   # для dict, list

# ❌ ЗАПРЕЩЕНО:
Signal(dict)     # RuntimeError в PySide6
```

### 5. CSS каскад для дочерних виджетов

```python
# ✅ ПРАВИЛЬНО — стили через родителя:
self.setStyleSheet("""
    MyWidget QLabel#title { color: #F0F0F0; background: transparent; }
    MyWidget QLabel#meta  { color: #CCCCCC; background: transparent; }
""")

# ❌ НЕПРАВИЛЬНО — separate setStyleSheet на каждом дочернем QLabel
```

### 6. Расположение ui_shared

```python
# ✅ ПРАВИЛЬНО:
from core.ui_shared.widgets import ModernCard, CharacterWindow
from core.ui_shared.styles  import ACCENT_PINK, apply_style

# ❌ НЕПРАВИЛЬНО (старая документация):
from ui_shared.widgets import ...   # не импортировать!
```

### 7. Указывать путь файла для VS Code (ОБЯЗАТЕЛЬНО)

```
FILE: features/chats/ui.py
FILE: core/stt/whisper_manager.py
```

### 8. Конвенция `__init__.py`

При создании **любой** новой папки — сразу создавать `__init__.py` с комментарием.

### 9. Сессионный файл Telegram — race condition

Telethon хранит сессию в SQLite-файле. Race condition между AuthWorker и ChatsWorker
приводит к `sqlite3.OperationalError: database is locked`.

**Правила:**
- `AuthWorker._auth()` — отключает client **внутри своего event loop** ДО эмита `auth_complete`.
  Передаёт `(None, user)` — живой client не передаётся наверх.
- `MainWindow._on_auth_complete()` — запускает `ChatsWorker` через `QTimer.singleShot(300)`,
  давая AuthWorker завершить `finally: loop.close()`.
- Каждый воркер (`ChatsWorker`, `ParseWorker`) создаёт СВОЙ `TelegramClient`,
  вызывает `await client.connect()`, выполняет работу, вызывает `await client.disconnect()` в `finally`.
- `MainWindow` НЕ хранит постоянный `self._client`.

```python
# ✅ ПРАВИЛЬНО — auth_complete без живого client:
async def _auth(self) -> None:
    ...
    await self._client.disconnect()   # здесь, в loop воркера
    self.auth_complete.emit(None, user)

# ✅ ПРАВИЛЬНО — задержка перед ChatsWorker:
def _on_auth_complete(self, client, user):
    QTimer.singleShot(300, self._load_chats)

# ❌ ЗАПРЕЩЕНО:
# loop = asyncio.new_event_loop()
# loop.run_until_complete(client.disconnect())  # cross-loop вызов
```

### 10. Сохранение конфига после авторизации — ОБЯЗАТЕЛЬНО

```python
# ✅ ПРАВИЛЬНО — в AuthScreen._on_auth_complete():
try:
    from config import save_config
    save_config(self._cfg)   # api_id, api_hash, phone → config_modern.json
except Exception as exc:
    logger.warning("auth: не удалось сохранить config: %s", exc)

# Без этого при следующем запуске поля формы пустые
```

### 11. Прогресс-бар — ОБЯЗАТЕЛЬНО эмитировать

```python
# Паттерн двухфазного прогресса (уже реализован в parser/api.py):
self._progress_cb(5)
pct = 5 + int(processed / total * 85)
self._progress_cb(min(pct, 90))
self._progress_cb(100)
```

### 12. Таймаут на download_media — ОБЯЗАТЕЛЬНО

```python
# ✅ ПРАВИЛЬНО:
async with self._sem:
    try:
        result = await asyncio.wait_for(
            message.download_media(file=target_path),
            timeout=120.0,
        )
    except asyncio.TimeoutError:
        logger.warning("download_media timeout: msg_id=%s", message.id)
        return None
```

### 13. Qt.UniqueConnection — ОБЯЗАТЕЛЬНО

```python
# ✅ ПРАВИЛЬНО — именованный метод + UniqueConnection:
worker.finished.connect(self._on_stt_finished_slot, Qt.UniqueConnection)
worker.error.connect(self._on_parse_error,          Qt.UniqueConnection)

# ❌ ЗАПРЕЩЕНО — лямбда блокирует UniqueConnection:
worker.finished.connect(lambda: self._on_stt_finished(result), Qt.UniqueConnection)
```

### 14. Instance-методы парсера — НЕ @staticmethod

`_get_sender_name` и `_extract_row_sync` в `features/parser/api.py` — **instance-методы**
класса `ParserService`, не `@staticmethod`. Это необходимо для доступа к `self._chat_title`
и корректного fallback на `from_id` при удалённых аккаунтах и авторах-каналах.

```python
# ✅ ПРАВИЛЬНО:
def _get_sender_name(self, message) -> str:
    ...
    # fallback на from_id для каналов и удалённых аккаунтов

# ❌ ЗАПРЕЩЕНО — делать эти методы @staticmethod:
@staticmethod
def _get_sender_name(message) -> str:  # потеряет доступ к self._chat_title
```

### 15. `_dedup_thread_messages()` — единая точка дедупликации тредов

Все 4 генератора (Docx/Markdown/Html/Json) используют **общую** функцию
`_dedup_thread_messages(pairs)` для дедупликации и вычисления depth.
Не реализовать собственную логику дедупликации в отдельном генераторе.

### 16. Перед патчем — проверь контекст

Прежде чем писать патч, прочитай текущее состояние файла. Не предполагай, что код выглядит
как в прошлом патче или как ты его оставил — между сессиями могли быть ручные правки или
другие патчи. Старый код в памяти ≠ текущий код на диске.

### 17. После патча — проверь ссылки

После каждого патча проверяй целостность: все имена, на которые ссылается изменённый код,
должны существовать. Если переименовал переменную/метод — сделай grep по файлу на старое имя.
Если добавил вызов — убедись, что целевая функция/метод существует с той же сигнатурой.

### 18. Smoke-тест перед каждым релизом — ОБЯЗАТЕЛЬНО

**Урок из v1.7.2:** три регрессии (C1, C2, B6) прошли незамеченными больше месяца, потому что
регулярное тестирование покрывало только сценарии из чейнджлога, а не смежные пути (видео,
HTML-экспорт, парсинг после переключения режимов).

**Перед каждым релизом — обязательный smoke-тест (5 минут):**

1. **Авторизация** — вход через Telegram Desktop ИЛИ через api_id/hash
2. **Парсинг тестового чата** — небольшой чат (~50-100 сообщений) с разными типами медиа:
   - Фото (одиночные + grouped)
   - Видео (обычные)
   - Кружочки (videomessage)
   - Голосовые
   - Файлы
3. **Проверка медиа** — после парсинга открыть `output/<чат>/` и убедиться, что:
   - Фото скачались (не 0 файлов в `photo/`)
   - Видео скачались (не 0 файлов в `video/`)
   - Голосовые скачались
4. **Экспорт во ВСЕ 4 форматах** — DOCX, JSON, MD, HTML. Каждый должен:
   - Сгенерироваться без ошибки
   - Содержать сообщения (не пустой файл)
   - Открыться в соответствующем приложении
5. **Фильтр по участнику** — выбрать участника, экспортировать, проверить что:
   - Сообщения фильтруются (не все подряд)
   - Режим «Все ветки» работает (видны ответы других людей)

**Если что-то из этого не работает — релиз СТАВИТСЯ НА ХОЛД**, баги чинятся, smoke-тест
повторяется полностью. Нельзя выпускать релиз с известными нарушениями smoke-теста.

**Минимальный smoke-тест (если нет времени полный):**
- Парсинг → проверка что видео скачалось
- Экспорт в HTML (это наименее покрытый формат)
- Экспорт в DOCX с фильтром по участнику

### 19. Sender ID нормализация — `_telegram_user_id_variants()`

В Telegram один и тот же entity (канал, группа) может быть представлен двумя ID:
- **bare ID** — положительное число (например, `3508193296`)
- **marked ID** — отрицательное, с префиксом `-100` (например, `-1003508193296`)

Telethon в разных контекстах возвращает разные форматы. БД хранит один формат (обычно
marked-negative для каналов), а UI может передавать другой.

**Решение:** в `core/database.py` метод `_telegram_user_id_variants(uid)` возвращает
оба варианта для SQL-фильтрации:

```python
def _telegram_user_id_variants(uid: int) -> list[int]:
    if uid > 0:
        return [uid, -(1_000_000_000_000 + uid)]  # bare + marked
    else:
        return [uid, -uid - 1_000_000_000_000]     # marked + bare
```

**Использовать в:**
- `get_messages()` — SQL-фильтр `WHERE sender_id IN (?, ?)`
- `get_thread_pairs()` — то же самое для пар тредов
- Любой запрос, фильтрующий по sender_id канала/группы

**НЕ использовать для:** обычных пользователей (у них всегда положительный ID без marked-варианта).

**B1/B3 урок:** `linked_chat_id=None` на megagroup entity из Telethon — нельзя обнаружить
связанный broadcast-канал для прямой нормализации. Поэтому в `get_user_stats()` дубликат
channel-sender entries (bare + marked ID одного канала) сливается в одну запись с
marked-negative ID уже после запроса.

### 20. Сигнатуры методов — `self` для instance, без `self` для `@staticmethod`

**Урок из C2/B6:** между сессиями патчи теряли `self` при копировании/переименовании.
Ошибка `takes N positional arguments but N+1 were given` = пропущен `self` в сигнатуре
instance-метода.

### #21. Пресет базы знаний (KB) — YAML-обогащение НЕ в MarkdownGenerator

Пресет `"kb"` добавляет YAML front-matter и 5 артефактов **пост-обработкой**
в `features/export/knowledge_base.py`. `MarkdownGenerator` и другие генераторы
НЕ меняются. Чекбокс KB в UI — редактируемый (не залочен пресетом). Переключение
KB не сбрасывает текущий пресет в «Свой вариант» (`_toggle_build_kb` НЕ в
`_wire_preset_watchers`).

При `build_kb=True` и отсутствии MD в форматах — MD добавляется автоматически
(в `ExportParams.__post_init__`).

ИНСТРУКЦИЯ_ДЛЯ_ИИ.md, CLAUDE.md и AGENTS.md — НЕ идентичные копии:
ИНСТРУКЦИЯ_ДЛЯ_ИИ.md — базовая инструкция, CLAUDE.md — базовая + добавка
для Claude Code, AGENTS.md — базовая + добавка для OpenAI Agents.

**Правила:**

```python
# ✅ Instance-метод — ОБЯЗАТЕЛЬНО self:
def _should_download(self, message: Message, media_filter: List[str]) -> bool:
    ...

# ✅ Static-метод — ОБЯЗАТЕЛЬНО @staticmethod, БЕЗ self:
@staticmethod
def _detect_media_type(message: Message) -> Optional[str]:
    ...

# ✅ Class-метод — ОБЯЗАТЕЛЬНО cls:
@classmethod
def instance(cls) -> "WhisperManager":
    ...
```

**Перед коммитом проверить:**

1. Если метод вызывается как `self._method(...)` — это instance-метод, нужен `self`
2. Если метод вызывается как `ClassName._method(...)` — это static/class method, нужен декоратор
3. VS Code подсвечивает несоответствие — НЕ игнорировать предупреждения
4. Если VS Code предлагает «добавить self» — значит потерян `@staticmethod` декоратор, а НЕ нужно добавлять `self`

**Греп-проверка перед коммитом:**

```bash
# Найти все методы без self в signature (потенциальные баги):
grep -n "^    def [^_]" features/parser/api.py features/export/generator.py
# Проверить что у каждого либо есть self, либо есть @staticmethod строкой выше
```

---

## 🔄 Основные потоки выполнения

### Авторизация:
```
UI → AuthWorker(QThread)
  async: AuthService.sign_in(client, providers...)
  → client.disconnect() внутри AuthWorker (до эмита!)
  → save_config(cfg)  — api_id/hash/phone на диск
  → Signal: auth_complete(None, User)
  → QTimer.singleShot(300) → _load_chats()
```

### Список чатов:
```
UI → ChatsWorker(QThread)
  async: ChatsService.get_dialogs(limit=200)
  → Signal: chats_loaded(List[dict])
  → CollapsibleChatsWidget.populate(chats)
```

### Парсинг:
```
UI → ParseWorker(QThread)
  async: ParserService.collect_data(CollectParams)
  → Signal: finished(CollectResult)
```

### STT (✅ реализовано):
```
ParseWorker.finished
  → MainWindow._run_stt(collect_result)
    → STTWorker(db_path, chat_id, model_size="base", language="ru")
      → WhisperManager.instance().transcribe(media_path)
      → Signal: finished()
  → MainWindow._on_stt_finished()
    → _run_export(collect_result)
```

### Export:
```
_run_export(collect_result)
  → ExportWorker(ExportParams)
    ExportParams.export_formats: list[str]  ← из активных toggle-чипов [DOCX|JSON|MD|HTML]
    ExportParams.ai_split: bool             ← чекбокс "Адаптировать для ИИ"
    → DocxGenerator (всегда единый файл, ai_split игнорируется)
    → JsonGenerator (с ai_split → part_1.json, part_2.json, ...)
    → MarkdownGenerator (с ai_split → part_1.md, part_2.md, ...)
    → HtmlGenerator (полноценная веб-страница с CSS-стилями)
  → Signal: export_complete(list[str])  ← пути созданных файлов
```

### Thread mode (✅ реализовано):
```
user_filter_mode == "threads"
  → parser: collect_data() собирает сообщения + пары тредов
  → database: get_thread_pairs(chat_id, user_id, ...) → List[sqlite3.Row]
  → generator: _dedup_thread_messages(pairs) → [(row, depth, reply_author), ...]
     → HTML: CSS depth-N классы + margin-left
     → DOCX: 24pt indent × depth + "↳" маркер
     → MD: 4 spaces × depth + "↳" маркер
     → JSON: flat list + depth + reply_to_author fields
```

---

## 📊 Состояние рефакторинга

| Файл | Статус | Последнее изменение |
|------|--------|---------------------|
| `config.py` | ✅ Готов | — |
| `core/utils.py` | ✅ Готов | — |
| `core/database.py` | ✅ Готов | 2026-06 B1/B3: _telegram_user_id_variants для bare↔marked ID; get_thread_pairs; sender_type (v2) |
| `core/logger.py` | ✅ Готов | — |
| `core/exceptions.py` | ✅ Готов | — |
| `core/merger.py` | ✅ Готов | — |
| `core/retry.py` | ✅ Готов | 2026-03-15 @async_retry декоратор |
| `core/ui_shared/widgets.py` | ✅ Готов | — |
| `core/ui_shared/styles.py` | ✅ Готов | — |
| `core/ui_shared/calendar.py` | ✅ Готов | — |
| `core/stt/audio_converter.py` | ✅ Готов | — |
| `core/stt/whisper_manager.py` | ✅ Готов | 2026-03-09 Singleton |
| `core/stt/worker.py` | ✅ Готов | 2026-03-09 STTWorker |
| `features/auth/api.py` | ✅ Готов | 2026-03-18 tdata import + detect_tdata_path |
| `features/auth/ui.py` | ✅ Готов | 2026-03-18 TdataImportWorker + кнопка импорта + диалог pip |
| `features/chats/api.py` | ✅ Готов | 2026-06 I9 завершён; канал как участник; B1/B3 fix: channel-sender merge в get_user_stats |
| `features/chats/ui.py` | ✅ Готов | 2026-03-18 лимит 500, LinkedGroupWorker |
| `features/parser/api.py` | ✅ Готов | 2026-07-03 C2-reg fix: восстановлен self в _should_download |
| `features/parser/ui.py` | ✅ Готов | — |
| `features/export/generator.py` | ✅ Готов | 2026-07-03 B6 fix: восстановлен self в HtmlGenerator._format_message |
| `features/export/xml_magic.py` | ✅ Готов | — |
| `features/export/ui.py` | ✅ Готов | 2026-05-25 duplicate user_filter_mode fixed |
| `ui/main_window.py` | ✅ Готов | 2026-05-25 duplicate user_filter_mode fixed |
| `core/ui_shared/widgets.py` | ✅ Готов | 2026-03-18 fix SectionTitle HLine артефакт |
| `core/ui_shared/styles.py` | ✅ Готов | 2026-03-18 fix FilterButton min-width |
| `main.py` | ✅ Готов | — |

---

## 📝 DATA CONTRACTS (Контракты данных и Сигналы)

### 1. Передача словарей (dict) через Сигналы PySide6
✅ **Правильно:** `Signal(object)` для передачи любых словарей (dict) и списков (list).

### 2. Стандартный словарь Чата (Chat Object)
```python
chat_dict = {
    "id": int,             # ID чата (нормализованный через finalize_telegram_id)
    "title": str,          # Название чата/группы/канала
    "type": str,           # "dialog" | "group" | "channel" | "forum"
    "unread_count": int,
    "is_forum": bool
}
```

### 3. ExportParams — контракт форматов
```python
@dataclass
class ExportParams:
    chat_id:          int
    chat_title:       str
    period_label:     str           = "fullchat"
    split_mode:       str           = "none"       # "none" | "day" | "month" | "post"
    topic_id:         Optional[int] = None
    user_id:          Optional[int] = None
    username:         Optional[str] = None
    include_comments: bool          = False
    output_dir:       str           = "output"
    db_path:          str           = "output/telegram_archive.db"
    export_formats:   list          = None         # ["docx","json","md","html"]
    ai_split:         bool          = False        # разбивка MD/JSON по 300к слов
    user_filter_mode: str           = "messages"   # "messages" | "threads"
    # DOCX всегда единый файл, ai_split на него не влияет
```

### 4. Форматы экспорта и генераторы

| Формат | Класс | ai_split | Выходные файли |
|--------|-------|----------|----------------|
| `docx` | `DocxGenerator` | ❌ не влияет | `chat_history.docx` |
| `json` | `JsonGenerator` | ✅ да | `_history.json` или `_part_1.json`, `_part_2.json` |
| `md`   | `MarkdownGenerator` | ✅ да | `_history.md` или `_part_1.md`, `_part_2.md` |
| `html` | `HtmlGenerator` | ❌ не влияет | `_history.html` |

### 5. Markdown формат сообщения
```markdown
**[YYYY-MM-DD HH:MM] Имя Автора:**
Текст сообщения

*(STT: текст расшифровки)*   ← только если есть STT

---
```

### 6. Типизация сигналов (рекомендация)
По возможности документируйте структуру данных, передаваемых через `Signal(object)`. Для списков используйте `Signal(list)`, но с комментарием о типе элементов.

Пример:
```python
# сигнал передаёт словарь чата: {id, title, type, ...}
chat_selected = Signal(object)
```

---

## 📦 Поставка (дистрибутив)

### Файлы рядом с .exe

```
📁 Любая папка/
├── RozittaParser.exe        ← основной исполняемый файл (onefile, ~65MB)
├── config_modern.json       ← настройки: api_id, api_hash, phone (создаётся автоматически после первого входа)
└── rozitta_session.session  ← сессия Telegram (создаётся при первом входе)
```

> Папка `output\` создаётся **автоматически** при первом запуске.
> `config_modern.json` создаётся **автоматически** после первой успешной авторизации.

### config_modern.json (минимальный пример)

```json
{
  "api_id": "12345678",
  "api_hash": "abcdef1234567890abcdef1234567890",
  "phone": "+79991234567"
}
```

### Важные пути

| Путь | Описание |
|------|----------|
| `config_modern.json` | Рядом с .exe — создаётся автоматически после первого входа |
| `rozitta_session.session` | Рядом с .exe (путь из `session_path` в config) |
| `output\` | Создаётся автоматически. Внутри — папки чатов |
| `output\<чат>\telegram_archive.db` | SQLite база конкретного чата |
| `output\<чат>\<медиа>\` | Скачанные медиафайлы |
| `output\<чат>\*.docx` | Сгенерированные документы |
| `output\<чат>\*_telegram_history.json` | JSON-архив (или `_part_N.json` с ai_split) |
| `output\<чат>\*_telegram_history.md` | Markdown-архив (или `_part_N.md` с ai_split) |
| `output\<чат>\*_telegram_history.html` | HTML-архив |
| `rozitta.log` | Лог приложения (рядом с .exe) |

### Сборка .exe

```bash
pyinstaller rozitta_parser.spec --noconfirm
# Результат: dist\RozittaParser.exe  (~65MB, onefile)
```

> ⚠️ Режим `--onefile`: при запуске распаковывается в `%TEMP%\_MEIxxxxxx` (~5-10 сек).
> После закрытия временная папка удаляется автоматически.

---

**Последнее обновление:** 2026-07-03
**Версия документа:** 5.1
**Автор:** Claude (Anthropic)
