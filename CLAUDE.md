# CLAUDE.md — Карта проекта Rozitta Parser

## 🤖 LLM CODING RULES (Karpathy-inspired)

> **Tradeoff:** Эти правила делают работу медленнее на простых задачах (опечатки, очевидные правки), но спасают от дорогих ошибок на нетривиальных изменениях.

### 1. THINK BEFORE CODING — Не додумывай, спрашивай

- **Никогда не делай предположений о неясном требовании.** Если задача сформулирована неоднозначно → напиши вопрос.
- **Если видишь два возможных пути реализации** → перечисли их в ответе и спроси, какой выбрать.
- **Если предложенный тобой план можно упростить** → сразу предложи более простой вариант и аргументируй.
- **Если что-то непонятно** → остановись, напиши: «Мне не ясно X. Уточни, пожалуйста.»

### 2. SIMPLICITY FIRST — Минимум кода, ничего «на вырост»

- **Не добавляй фич, которые не просили.** Даже если «это может пригодиться в будущем».
- **Не создавай абстракций для однократного использования.** Класс/функция только если код вызывается хотя бы дважды.
- **Не пиши обработку ошибок для невозможных сценариев.** Только реальные исключения, которые могут произойти.
- **Если ты написал 200 строк, а можно было 50** → перепиши.

### 3. SURGICAL CHANGES — Трогай только то, что нужно

**Запрещено:**
- Править орфографию/грамматику в комментариях (если только задача не про грамотность).
- Переформатировать код (менять отступы, переносы строк, кавычки), если это не часть задачи.
- Рефакторить соседние функции/классы, даже если они «выглядят некрасиво».
- Удалять мёртвый код, который существовал до твоих изменений.

**Разрешено:**
- Удалять **только тот** мёртвый код, который **твои изменения** сделали неиспользуемым (импорты, переменные, функции).

### 4. GOAL‑DRIVEN EXECUTION — Сначала критерии, потом код

**Для любой задачи, кроме очевидной опечатки, делай так:**

1. **Сформулируй успешный критерий.**  
2. **Для багфикса:** сначала напиши тест, который воспроизводит баг (даже если тестов мало — создай в `tests/`). Потом исправляй баг так, чтобы тест прошёл.
3. **Для многошаговой задачи:** выведи план с проверками в формате:
   ```
   1. [Что делаем] → проверка: [конкретный критерий]
   2. [Что делаем] → проверка: [конкретный критерий]
   ```
4. **Если не можешь сформулировать критерий** → задай уточняющий вопрос.

---

## 🧱 ARCHITECTURAL RULES (нарушение = баг)

1. **Qt-изоляция** – `features/*/api.py`, `core/*.py` — **НИКАКОГО** импорта PySide6/Qt. Только в `features/*/ui.py`, `core/ui_shared/`, `core/stt/worker.py`, `ui/*.py`.
2. **TelegramClient** – каждый `QThread` создаёт **СВОЙ** клиент → `connect()` → работа → `disconnect()` в `finally`. Все воркеры используют `build_client(cfg)` из `features/auth/api.py`. `MainWindow` **НЕ** хранит `self._client`.
   > **Альтернативный паттерн (рекомендуется для нового кода):** единый поток с постоянным event loop (`TelegramEventLoopThread`) и `qasync` – позволяет избежать проблем с SQLite и упрощает код. См. раздел «Единый event loop».
3. **Сигналы** – `Signal(dict)` **ЗАПРЕЩЁН** → только `Signal(object)`. Все `.connect()` → `Qt.UniqueConnection`. Лямбды в `connect()` **ЗАПРЕЩЕНЫ**.
4. **База данных** – только через `DBManager`. Никогда `sqlite3.connect()` напрямую. Batch insert: `insert_messages_batch()`.
5. **`download_media`** – адаптивный подход: для файлов ≤50 МБ использовать `asyncio.wait_for(..., timeout=120.0)`, для файлов >50 МБ – без таймаута (или через `teleget`). См. раздел «Скачивание больших файлов».
6. **`ui_shared`** – импорт: `from core.ui_shared.widgets import ...`. Корневой `ui_shared/` — legacy, не импортировать.
7. **Новые файлы/папки** – каждый новый файл/папка → `__init__.py` с комментарием.
8. **Форматы экспорта** – `ExportParams.export_formats: list[str]` – активные форматы из toggle-чипов `[DOCX | JSON | MD | HTML]`. По умолчанию `["docx"]`. **НЕ** `QButtonGroup`, **НЕ** radio. Каждая кнопка `setCheckable(True)` без `setExclusive(True)`.
9. **AI‑сплит чанкинг** – применяется **только** к MD, JSON (не к DOCX и HTML). Размер чанка настраивается через UI‑спинбокс (`ai_split_chunk_words`).
10. **Аватар Розитты** – `assets/rozitta_idle.png`. При отсутствии файла — пустой `QLabel`.
11. **Прокси** – поддержка SOCKS5 и MTProto реализована в коде. Однако их работоспособность крайне нестабильна и зависит от текущей сетевой ситуации (особенно в РФ с апреля 2026 наблюдаются массовые блокировки). Рекомендации по выбору типа прокси должны основываться на **актуальных тестах**, а не на документации. Пользователь может экспериментировать, но стабильность не гарантируется. Конфигурация в `config.py` (`AppConfig.proxy_*`), `build_client()` — единственное место применения прокси.
12. **topic_id в pipeline** – хранится в `chat["selected_topic_id"]` после выбора в `ChatsScreen`. `ParseParams` **не имеет** поля `topic_id` — читается из `p.chat["selected_topic_id"]`. В `_run_export()` читается из `self._settings_screen._current_chat.get("selected_topic_id")`.
13. **Запрет на использование `limit` в `iter_messages` для ускорения** – `limit` ограничивает **общее количество** сообщений, а не размер батча. Для пакетной загрузки всегда используйте `limit=100` (максимум) и цикл с `offset_id`. См. раздел «Прямые запросы с адаптивными паузами».

---

## 📤 RESPONSE FORMAT (ОБЯЗАТЕЛЬНО)

**Никогда не присылай полные файлы целиком** (это приводит к обрезке, потере функций и ошибкам).

**Всегда выдавай изменения в виде Python‑скрипта‑патча**, который можно сохранить как `.py` и запустить из корня проекта.

### Требования к патчу:

1. Файл самодостаточен: содержит блоки `OLD` и `NEW`, заменяет их и сохраняет файл.
2. Каждый патч — отдельный блок с комментарием, что он делает.
3. **Старый блок (`OLD_X`)** — точный фрагмент кода **с отступами**, включая 3–5 строк контекста до и после изменений.
4. **Новый блок (`NEW_X`)** — такой же по отступам, но с изменениями.
5. Проверяй наличие `OLD_X` в файле перед заменой. Если нет — выводи предупреждение, но не заменяй.
6. Для больших методов (более 20 строк) используй **регулярное выражение** с `re.DOTALL` и поиском по маркеру (например, `"    async def _get_post_replies("`).
7. В конце скрипта — проверка `if src != original` и запись только при изменениях.
8. Сопровождай патч кратким описанием (2–3 предложения): что меняется, зачем, возможные побочные эффекты.

### Пример правильного ответа (каркас):

```python
"""
Apply patches to features/parser/api.py
Run: python apply_parser_patches.py
"""
import re
import sys

PATH = "features/parser/api.py"

with open(PATH, encoding="utf-8") as f:
    src = f.read()
original = src

# --- PATCH 1: fix something ---
OLD_1 = "..."
NEW_1 = "..."
if OLD_1 not in src:
    print("WARN: PATCH 1 not found")
else:
    src = src.replace(OLD_1, NEW_1, 1)
    print("OK: PATCH 1 applied")

# --- PATCH 2: replace method using regex ---
OLD_MARKER = "    async def _get_post_replies(\n"
NEW_METHOD = "..."
pattern = r'    async def _get_post_replies\(.*?(?=\n    async def _process_message)'
match = re.search(pattern, src, re.DOTALL)
if match:
    src = src[:match.start()] + NEW_METHOD + src[match.end():]
    print("OK: PATCH 2 applied")
else:
    print("WARN: PATCH 2 not found")

if src != original:
    with open(PATH, "w", encoding="utf-8") as f:
        f.write(src)
    print(f"\nSaved: {PATH}")
else:
    print("\nNo changes made")
```

**Исключения, когда допустим полный файл:**
- Пользователь явно запрашивает: «Покажи мне полное содержимое файла X».
- Файл очень маленький (до 30 строк) и патч будет сложнее, чем сам файл.
- Восстановление после критической поломки (тогда сначала полный файл, потом патчи).

---

## 🎯 CURRENT PRIORITIES (обновлено 2026-04-15)

| Приоритет | Задача | Файлы | Статус |
|-----------|--------|-------|--------|
| 🔴 | **Активные участники (BUG-20)** — три подзадачи: <br> 1. Исправить отображение username <br> 2. Фильтрация сообщений по участнику <br> 3. Экспорт списка активных участников | `ui/main_window.py`, `features/parser/api.py`, `features/export/generator.py` | Открыт |
| 🔴 | **BUG-18**: OpenTele2 всегда предлагает установить библиотеку, даже если она есть | `features/auth/ui.py`, `api.py` | Открыт |
| 🔴 | **BUG-19**: DOCX — нет превью видео (thumbnail/placeholder) | `features/export/generator.py` | Открыт |
| 🔴 | **DB-LOCK-2**: Периодический «database is locked» при параллельной записи | `core/database.py`, `core/retry.py` | Открыт |
| 🟡 | **Lite-версия** — `ui/lite/main_window.py` по макету | `ui/lite/main_window.py` | В разработке |
| 🟡 | **Английский интерфейс (i18n)** — переключатель, файл локалей | `core/i18n.py`, `config.py`, все `ui/*.py` | Запланировано |
| 🟡 | **Тестирование на macOS и Linux** | — | Запланировано |
| ⚪ | **Параллельная загрузка медиа** — `asyncio.Semaphore(3)` | `features/parser/api.py` | Запланировано |
| ⚪ | **STT для видео** (расширить `STT_FILE_TYPES`) | `core/stt/worker.py` | Запланировано |
| ⚪ | **STT-GPU** — выбор устройства (cuda/cpu) в `AppConfig` | `config.py`, `core/stt/whisper_manager.py` | Запланировано |
| ⚪ | **Takeout API** — опциональный режим для стабильности парсинга | `features/parser/api.py` | Запланировано |

---

## 🔗 Дополнительные ресурсы

- **Интерактивная карта проекта:** `https://nynchezyabka.github.io/RozittaParser/map.html` (локально `docs/map.html`)
- **Модульные метки GitHub Issues** (добавлять при создании задачи): `module:auth`, `module:export`, `module:database`, `module:parser`, `module:chats`, `module:stt`, `module:ui`, `module:ui-lite`, `module:config`. Привязка к карте — автоматическая.
- **Детальный анализ и roadmap** смотри в `PROJECT_ANALYSIS.md`.

---

## 📋 О проекте

**Название:** Rozitta Parser (Telegram Archiver)
**Версия:** 5.1 (актуальная сборка)
**Тип:** Desktop приложение (PySide6)
**Назначение:** Архивирование сообщений из Telegram чатов с созданием DOCX / JSON / MD / HTML документов

---

## 🎯 Основная функциональность

1. **Авторизация в Telegram** через Telethon (сессия и api_id/hash/phone сохраняются после входа)
2. **Импорт сессии из Telegram Desktop** — кнопка «🖥️ Импорт из tdata» (opentele2, требуется закрытый Telegram Desktop)
3. **Загрузка списка чатов** (каналы, группы, форумы, диалоги — коллапсируемые секции; кэш 24ч)
4. **Парсинг сообщений** с фильтрацией по глубине / медиа / пользователю
5. **Скачивание медиа** в структурированные папки (адаптивный таймаут)
6. **Склейка сообщений** (агрессивная эвристика: один автор, ≤60 сек)
7. **Генерация DOCX** с изображениями, ссылками, закладками
8. **Работа с форумами/топиками**
9. **Посты + комментарии** (канал + linked группа) — комментарии собираются отдельно по каждому посту через `reply_to=post_id`
10. **Распознавание речи** (faster-whisper, ✅ РЕАЛИЗОВАНО — голосовые/кружочки → текст в DOCX)
11. **JSON экспорт** (✅ РЕАЛИЗОВАНО — плоский список объектов, совместим с NotebookLM)
12. **Markdown экспорт** (✅ РЕАЛИЗОВАНО — чистый формат для ИИ-инструментов)
13. **AI-split чанкинг** (✅ РЕАЛИЗОВАНО — разбивка MD/JSON на части по настраиваемому количеству слов)

---

## 🛠️ Технологический стек

- **Python 3.10+**
- **Telethon 1.42** (заморожен в феврале 2026, но стабилен)
- **SQLite3** — WAL режим
- **python-docx 1.1+** — Word документы
- **PySide6 6.6+** — Qt GUI
- **asyncio** — Асинхронность (QThread создаёт `new_event_loop`)
- **faster-whisper** — STT движок (✅ реализован, прямая подача .ogg/.mp4)
- **FFmpeg** — системная зависимость (для AudioConverter, опционально)
- **python-socks** — опциональная зависимость для SOCKS5 прокси
- **opentele2** — импорт tdata (активный форк, совместим с Telethon 1.42)

> **⚠️ Прокси:** В коде реализована поддержка SOCKS5 и MTProto, но их стабильность крайне низка и может меняться ежедневно (особенно в РФ). Рекомендации по использованию должны основываться на актуальных тестах, а не на документации.

---

## 📂 Актуальная структура проекта

```
rozitta_parser/
│
├── main.py                          # ✅ Готов
├── config.py                        # ✅ Конфигурация (AppConfig, load/save_config)
├── CLAUDE.md                        # Карта проекта для AI (этот файл)
│
├── assets/                          # Медиа-ресурсы приложения
│   ├── rozitta_idle.png             # ✅ Аватар по умолчанию (80×80px, используется в CharSection)
│   └── rozitta_*.gif                # 🔜 Анимированные реакции (будут добавлены постепенно)
│
├── core/                            # ✅ Готова полностью
│   ├── __init__.py
│   ├── utils.py                     # finalize_telegram_id, sanitize_filename, ...
│   ├── database.py                  # DBManager: WAL, thread-local, retry, merge
│   ├── logger.py                    # setup_logging, get_logger, set_level
│   ├── exceptions.py                # Полная иерархия ошибок
│   ├── merger.py                    # MergerService: O(n) склейка
│   ├── retry.py                     # ✅ @async_retry декоратор
│   │
│   ├── ui_shared/                   # ✅ Готова полностью
│   │   ├── __init__.py
│   │   ├── widgets.py               # StepperWidget, RozittaWidget, ModernCard, ...
│   │   ├── styles.py                # Цветовые константы, QSS, apply_style()
│   │   └── calendar.py              # DateRangeWidget
│   │
│   └── stt/                         # ✅ РЕАЛИЗОВАНО
│       ├── __init__.py
│       ├── audio_converter.py       # AudioConverter (FFmpeg pipeline, резервный)
│       ├── whisper_manager.py       # WhisperManager (Singleton faster-whisper)
│       └── worker.py                # STTWorker(QThread) — пакетная транскрипция
│
├── features/
│   ├── __init__.py
│   ├── auth/                        # ✅ Готова
│   │   ├── api.py                   # AuthService (build_client, sign_in, import_from_tdata)
│   │   └── ui.py                    # AuthWorker QThread; save_config() после входа
│   │
│   ├── chats/                       # ✅ Готова
│   │   ├── api.py                   # ChatsService, classify_entity()
│   │   └── ui.py                    # ChatItemWidget, CollapsibleSection, ...
│   │
│   ├── parser/                      # ✅ Готова
│   │   ├── api.py                   # ParserService, CollectParams, CollectResult
│   │   └── ui.py                    # ParseWorker QThread (собственный TelegramClient)
│   │
│   └── export/                      # ✅ Готова
│       ├── generator.py             # DocxGenerator + JsonGenerator + MarkdownGenerator + HtmlGenerator
│       ├── xml_magic.py             # add_bookmark, add_internal_hyperlink, ...
│       └── ui.py                    # ExportWorker QThread, ExportParams
│
├── ui/
│   └── main_window.py               # ✅ MainWindow — цепочка Parse→STT→Export
│
└── tests/
    ├── test_core/
    └── test_features/
```

> ⚠️ **Важно:** `ui_shared` расположен в `core/ui_shared/`, а **не** в `ui_shared/` в корне.

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
    merge_part_index   INTEGER
);
```

### Таблица: `transcriptions` (✅ реализована)
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

## 📡 Signals воркеров (Qt)

| Воркер | Сигналы |
|--------|---------|
| `AuthWorker` | `log_message(str)`, `auth_complete(object,object)`, `error(str)`, `request_input(str,str,bool)`, `character_state(str)` |
| `ChatsWorker` | `log_message(str)`, `chats_loaded(list)`, `error(str)`, `character_state(str)` |
| `TopicsWorker` | `log_message(str)`, `topics_loaded(dict)`, `error(str)`, `character_state(str)` |
| `ParseWorker` | `log_message(str)`, `progress(int)`, `finished(object)`, `error(str)`, `character_state(str)` |
| `ExportWorker` | `log_message(str)`, `export_complete(list)`, `error(str)`, `character_state(str)` |
| `STTWorker` | `log_message(str)`, `transcription_ready(int,str)`, `error(str)`, `progress(int)`, `finished()` |

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
    # Methods: load_chats(limit=500), inject_chats(chats), selected_chat()
```

---

## 📰 ТРЕБОВАНИЕ: Режим "Посты + Комментарии" (split=by_posts)

### Ожидаемое поведение

При выборе режима разделения **"Посты"** и включённом toggles **"Скачивать комментарии"**:

- Источник постов: **broadcast channel** (основной канал)
- Источник комментариев: **linked discussion group** (привязанная супергруппа)
- Связь: через `GetDiscussionMessageRequest(peer=channel, msg_id=post_id)`
- **Важно:** комментарии собираются отдельно по каждому посту через `reply_to=post_id`. `linked_chat_id` — это группа обсуждений, но она не отдаёт всех комментаторов автоматически. Нельзя использовать `iter_messages(group)` без привязки к посту.

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

## 🧷 ДОПОЛНИТЕЛЬНЫЕ ПРАВИЛА КОДИРОВАНИЯ (строго соблюдать)

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
```

### 6. Расположение ui_shared

```python
# ✅ ПРАВИЛЬНО:
from core.ui_shared.widgets import ModernCard, CharacterWindow
from core.ui_shared.styles  import ACCENT_PINK, apply_style
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
- **Вместо `QTimer.singleShot(300)` используйте явный сигнал `client_closed`**:
  ```python
  # В AuthWorker:
  class AuthWorker(QObject):
      client_closed = Signal()  # добавить сигнал

      async def _auth(self):
          # ... после client.disconnect()
          self.client_closed.emit()  # вместо QTimer
          self.auth_complete.emit(None, user)

  # В MainWindow:
  def _on_auth_complete(self, client, user):
      # ChatsWorker запустится только после client_closed
      auth_worker.client_closed.connect(self._load_chats, Qt.UniqueConnection)
  ```
- Каждый воркер (`ChatsWorker`, `ParseWorker`) создаёт СВОЙ `TelegramClient`,
  вызывает `await client.connect()`, выполняет работу, вызывает `await client.disconnect()` в `finally`.
- `MainWindow` НЕ хранит постоянный `self._client`.

> **Альтернативный паттерн (рекомендуется для нового кода):** единый поток с постоянным event loop и `qasync`. См. раздел «Единый event loop».

### 10. Сохранение конфига после авторизации — ОБЯЗАТЕЛЬНО

```python
# ✅ ПРАВИЛЬНО — в AuthScreen._on_auth_complete():
try:
    from config import save_config
    save_config(self._cfg)   # api_id, api_hash, phone → config_modern.json
except Exception as exc:
    logger.warning("auth: не удалось сохранить config: %s", exc)
```

### 11. Прогресс-бар — ОБЯЗАТЕЛЬНО эмитировать

```python
# Паттерн двухфазного прогресса (уже реализован в parser/api.py):
self._progress_cb(5)
pct = 5 + int(processed / total * 85)
self._progress_cb(min(pct, 90))
self._progress_cb(100)
```

### 12. Скачивание больших файлов — адаптивный подход

**Правило:** Не использовать единый таймаут для всех файлов.  
Для файлов размером **> 50 МБ** таймаут приводит к ошибке, такие файлы нужно скачивать без `wait_for`.

```python
# ✅ ПРАВИЛЬНО — адаптивный выбор метода:
file_size = getattr(message.document, 'size', 0) if message.document else 0

if file_size > 50 * 1024 * 1024:  # >50 MB
    # Большой файл — без таймаута
    result = await message.download_media(file=target_path)
else:
    # Маленький файл — с таймаутом
    try:
        result = await asyncio.wait_for(
            message.download_media(file=target_path),
            timeout=120.0,
        )
    except asyncio.TimeoutError:
        logger.warning("download_media timeout for small file: msg_id=%s", message.id)
        return None
```

> Если используется `teleget`, то замените `message.download_media` на вызов `teleget` с его собственной логикой повторных попыток.

### 13. Qt.UniqueConnection — ОБЯЗАТЕЛЬНО

```python
# ✅ ПРАВИЛЬНО — именованный метод + UniqueConnection:
worker.finished.connect(self._on_stt_finished_slot, Qt.UniqueConnection)
worker.error.connect(self._on_parse_error,          Qt.UniqueConnection)

# ❌ ЗАПРЕЩЕНО — лямбда блокирует UniqueConnection:
worker.finished.connect(lambda: self._on_stt_finished(result), Qt.UniqueConnection)
```

### 14. Запрет на использование `limit` в `iter_messages` для ускорения

```python
# ❌ НЕПРАВИЛЬНО — limit не размер батча, а потолок:
messages = await client.iter_messages(chat, limit=100)  # вернёт только 100 сообщений

# ✅ ПРАВИЛЬНО — использовать цикл с offset_id и limit=100 (максимум):
async for message in client.iter_messages(chat, limit=None, offset_id=offset_id):
    # limit=None означает "без ограничения", Telethon сам сделает пагинацию
    # Но лучше явный GetHistoryRequest (см. раздел «Прямые запросы с адаптивными паузами»)
```

---

## 🔄 Основные потоки выполнения

### Авторизация:
```
UI → AuthWorker(QThread)
  async: AuthService.sign_in(client, providers...)
  → client.disconnect() внутри AuthWorker (до эмита!)
  → save_config(cfg)  — api_id/hash/phone на диск
  → Signal: client_closed() (явный сигнал)
  → Signal: auth_complete(None, User)
  → _load_chats() (по сигналу client_closed, не по QTimer)
```

### Список чатов:
```
UI → ChatsWorker(QThread)
  async: ChatsService.get_dialogs(limit=500)
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
  → Signal: export_complete(list[str])  ← пути созданных файлов
```

---

## 🧵 Единый event loop (альтернативный паттерн)

> **Этот раздел описывает рекомендуемый для нового кода подход, который решает проблемы с SQLite и упрощает архитектуру. Он не требует немедленного рефакторинга существующего кода, но его стоит учитывать при добавлении новых воркеров.**

### Проблемы текущего подхода (каждый воркер создаёт свой event loop):
- Сложно синхронизировать доступ к SQLite (database is locked).
- `QTimer.singleShot(300)` ненадёжен.
- Требуется осторожно передавать команды паузы/остановки.

### Альтернатива: единый поток с постоянным event loop + `qasync`

```python
import asyncio
import threading
from PySide6.QtCore import QThread, QObject, Signal
import qasync  # pip install qasync

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


# Использование в MainWindow:
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self._telegram_thread = TelegramEventLoopThread()
        self._telegram_thread.start()

    def _run_parse(self, params):
        # Отправляем задачу в единый поток
        future = self._telegram_thread.submit(self._parse_async(params))
        future.add_done_callback(self._on_parse_done)

    async def _parse_async(self, params):
        # Здесь можно безопасно использовать Telethon и DBManager
        # (в одном потоке, без race condition)
        async with self._telegram_thread.get_loop():
            client = build_client(cfg)
            await client.connect()
            try:
                result = await collect_data(client, params)
            finally:
                await client.disconnect()
        return result
```

### Более простой вариант: `qasync` в главном потоке

```python
# В main.py:
import qasync
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)
loop = qasync.QEventLoop(app)
asyncio.set_event_loop(loop)

with loop:
    loop.run_forever()
```

После этого можно вызывать асинхронные функции прямо из UI-обработчиков без `QThread` и ручного управления event loop'ами.

**Решение о внедрении:** пока не требуется, но при появлении новых воркеров или рефакторинге существующих стоит рассмотреть `qasync`.

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
    include_comments: bool          = False
    output_dir:       str           = "output"
    db_path:          str           = "output/telegram_archive.db"
    export_formats:   list          = None         # ["docx","json","md","html"]
    ai_split:         bool          = False        # разбивка MD/JSON по 300к слов
    ai_split_chunk_words: int       = 300000       # настраиваемый размер чанка
    # DOCX всегда единый файл, ai_split на него не влияет
```

### 4. Форматы экспорта и генераторы

| Формат | Класс | ai_split | Выходные файлы |
|--------|-------|----------|----------------|
| `docx` | `DocxGenerator` | ❌ не влияет | `chat_history.docx` |
| `json` | `JsonGenerator` | ✅ да | `_history.json` или `_part_1.json`, `_part_2.json` |
| `md`   | `MarkdownGenerator` | ✅ да | `_history.md` или `_part_1.md`, `_part_2.md` |
| `html` | `HtmlGenerator` | ❌ не влияет | `chat_history.html` |

### 5. Markdown формат сообщения
```markdown
**[YYYY-MM-DD HH:MM] Имя Автора:**
Текст сообщения

*(STT: текст расшифровки)*   ← только если есть STT

---
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
| `rozitta.log` | Лог приложения (рядом с .exe) |

### Сборка .exe

```bash
pyinstaller rozitta_parser.spec --noconfirm
# Результат: dist\RozittaParser.exe  (~65MB, onefile)
```

> ⚠️ Режим `--onefile`: при запуске распаковывается в `%TEMP%\_MEIxxxxxx` (~5-10 сек).
> После закрытия временная папка удаляется автоматически.

---

**Последнее обновление:** 2026-04-15 (уточнён раздел прокси: нестабильность, необходимость актуальных тестов; исправлены таймаут download_media, явный сигнал вместо QTimer, уточнены комментарии к постам, добавлен раздел про единый event loop, запрет на limit, статус opentele2)
**Версия документа:** 5.2
