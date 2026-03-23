# 📊 АНАЛИЗ ПРОЕКТА ROZITTA PARSER

---

## 🚨 0. CRITICAL HOTFIX (2026-02-17)

| ID | Тип | Описание | Статус |
|----|-----|----------|--------|
| CR-1 | 🔴 CRITICAL | Schema Mismatch: `file_type`, `file_size`, `linked_chat_id` | ✅ Исправлен |
| CR-2 | 🔴 CRITICAL | Infinite Loop при FloodWait: `continue` → `break` | ✅ Исправлен |
| CR-3 | 🔴 CRITICAL | Silent Failures в `_get_post_replies` | ✅ Исправлен |
| TD-5 | 🟡 TECH DEBT | Воркеры без `character_state = Signal(str)` | ✅ Добавлен |

---

## 🏗️ 1. АРХИТЕКТУРА (Feature-based) ✅ ЗАВЕРШЕНА

### Реализованная структура:

```
rozitta_parser/
│
├── main.py                     ✅ Финальный этап завершён
├── config.py                   ✅
│
├── core/
│   ├── utils.py                ✅ — finalize_telegram_id, sanitize_filename
│   ├── database.py             ✅ — DBManager, WAL, batch I/O, transcriptions
│   ├── logger.py               ✅
│   ├── exceptions.py           ✅ — 14 типизированных исключений
│   ├── merger.py               ✅ — MergerService O(n)
│   ├── ui_shared/
│   │   ├── widgets.py          ✅ — StepperWidget, RozittaWidget, ModernCard
│   │   ├── styles.py           ✅
│   │   └── calendar.py         ✅
│   └── stt/
│       ├── __init__.py         ✅
│       ├── audio_converter.py  ✅ — AudioConverter (FFmpeg → WAV, резервный)
│       ├── whisper_manager.py  ✅ — WhisperManager Singleton (faster-whisper)
│       └── worker.py           ✅ — STTWorker(QThread) пакетная транскрипция
│
├── features/
│   ├── auth/api.py             ✅
│   ├── auth/ui.py              ✅ — SessionCheckWorker + AuthScreen guard
│   ├── chats/api.py            ✅
│   ├── chats/ui.py             ✅ — CollapsibleSection, форум-топики, CSS-фикс
│   ├── parser/api.py           ✅ — batch I/O, прогресс, date_from/to, форумы
│   ├── parser/ui.py            ✅ — ParseWorker (собственный TelegramClient)
│   ├── export/generator.py     ✅ — DocxGenerator + транскрипции в DOCX
│   ├── export/xml_magic.py     ✅
│   └── export/ui.py            ✅
│
└── ui/
    └── main_window.py          ✅ — цепочка Parse → STT → Export
```

---

## 🎨 2. НОВЫЙ UI ДИЗАЙН — Redesign (docs/rozitta-redesign.html)

### Ключевые отличия нового дизайна от текущего:

| Аспект | Текущий UI (v3.5) | Новый дизайн (redesign.html) |
|--------|-------------------|------------------------------|
| Навигация | Stepper/Wizard (последовательно) | Tab-based (3 вкладки, любой порядок) |
| Правая панель | Отдельный виджет Rozitta | Постоянная правая колонка (308px) |
| Журнал | В нижней части | В правой панели (flex 1) |
| Кнопка «Начать» | В ParseSettingsScreen | Всегда видна в правой панели |
| Прогресс-бар | В ParseSettingsScreen | Всегда видна в правой панели |
| Настройки парсинга | Отдельный экран (шаг 3) | Вкладка "Настройки" (шаг 3) |
| Цвета | Текущие | `--orange: #FF9500`, `--pink: #FF6BC9`, glassmorphism |
| Шапка | Нет | Header: лого + status pill (online/busy dot) |
| Layout | QStackedWidget | 3 колонки: sidebar(196) + main(1fr) + right(308) |

### Состав нового `main_window.py` (redesign):

```
QMainWindow
└── QWidget (central)
    ├── Header (52px)
    │   ├── Logo ("✦ Rozitta / Parser")
    │   └── StatusPill (dot + text)
    │
    └── Workspace (grid: 196px | 1fr | 308px)
        ├── Sidebar (196px)
        │   ├── Section label "Шаги"
        │   ├── NavBtn #1 — Авторизация  [step-num + icon + text]
        │   ├── NavBtn #2 — Чаты
        │   ├── NavBtn #3 — Настройки
        │   ├── Spacer
        │   └── SidebarInfo ("Выбранный чат")
        │
        ├── MainContent (QStackedWidget / 3 панели)
        │   ├── Tab 1: AuthScreen (существующий виджет)
        │   ├── Tab 2: ChatsScreen (существующий виджет)
        │   └── Tab 3: SettingsPanel (НОВЫЙ / объединяет ParseSettingsScreen)
        │
        └── RightPanel (308px)
            ├── CharSection
            │   ├── Avatar: QLabel с QPixmap("assets/rozitta_idle.png")  ← [UI-SPEC]
            │   │   Размер: 80×80px, borderRadius: 40px, objectFit: cover
            │   │   При смене состояния — менять через setPixmap(QPixmap(...))
            │   ├── Name label ("Rozitta")
            │   └── Tip label (подсказка по текущему шагу)
            ├── LogSection (flex 1)
            │   ├── LogTop (heading + clear/copy btns)
            │   ├── LogFilters (Все/Инфо/Успех/Предупр./Ошибки)
            │   └── LogOutput (QTextEdit, monospace)
            ├── ProgressSection
            │   ├── ProgressLabel ("Прогресс" + percent)
            │   └── ProgressBar (gradient pink→orange)
            └── StartSection
                └── StartBtn ("▶ НАЧАТЬ ПАРСИНГ") — btn-primary
```

### Settings Tab (вкладка 3) — полный состав:

```
SettingsPanel
├── Выбранный чат (readonly input — из шага 2)
├── Скачивание медиафайлов
│   ├── MediaGrid: [Фото | Видео | Кружки | Голос | Файлы] — toggle chips
│   ├── Slider: параллельных загрузок (1–8)
│   └── Toggle: пропускать скачанные (DownloadTracker)
├── Распознавание речи (STT)
│   └── Chips: [Видео | Аудио | Кружки] — on/off
├── Диапазон скачивания
│   └── DateBox: dateFrom / dateTo
├── Фильтр по пользователям
│   ├── Btn: Загрузить участников
│   ├── ModeSelect: Только сообщения / Все ветки
│   ├── UserTags: chips участников
│   └── AdvancedFilters (collapse):
│       ├── Keywords
│       ├── Checkboxes: только с медиа / только с видео
│       └── MinViews
├── Параметры разделения
│   ├── SplitGrid: [Единый | Дни | Месяцы | Посты]
│   └── Toggle: скачивать комментарии (показывается при режиме "Посты")
└── Экспорт
    ├── FormatRow: [DOCX | JSON | HTML]  ← НЕЗАВИСИМЫЕ TOGGLE-ЧИПЫ
    │   ⚠️ НЕ radio-group! Каждый чип включается/выключается независимо.
    │   Можно выбрать один, два или все три формата одновременно.
    │   Реализация: QPushButton с setCheckable(True), без ButtonGroup.
    │   ExportParams.export_formats: list[str] = ["docx"] по умолчанию.
    │   Пример: ["docx", "html"] — экспортирует оба формата параллельно.
    └── ExportPath (input + folder icon)
```

---

## 🗺️ 3. ОБНОВЛЁННЫЙ ROADMAP (2026-03-14)

### Принципиальное решение по порядку работы:

**UI Redesign ПЕРВЫМ, затем P1 Backend.**

**Обоснование:**
1. Новый UI меняет архитектуру `main_window.py` фундаментально (stepper → tabs). Все последующие UI-элементы (STT toggle, DownloadTracker checkbox, Expression filter поле) будут добавляться уже в новый SettingsPanel.
2. Backend P1 (DownloadTracker, retry.py) — UI-агностичны, не зависят от структуры окна. Их можно добавить в любой момент.
3. P2 задачи (Semaphore, Expression filter) требуют UI-элементов в Settings Tab — значит, UI должен быть готов заранее.
4. Нет смысла добавлять STT-toggle в старый ParseSettingsScreen, если через неделю он будет переписан.

---

### ✅ ФАЗА UI-1 — Redesign Main Window (ЗАВЕРШЕНА)

> **Задача:** Переписать `ui/main_window.py` + обновить `core/ui_shared/styles.py` под новый дизайн.
> **Трогаем:** ТОЛЬКО `ui/main_window.py` и `core/ui_shared/styles.py`. Все воркеры и api.py — БЕЗ ИЗМЕНЕНИЙ.

| # | Задача | Файл | Зависимости |
|---|--------|------|-------------|
| UI-1.1 | Обновить дизайн-токены в `styles.py`: `--orange #FF9500`, `--pink #FF6BC9`, glassmorphism-переменные, QSS для кнопок/инпутов/карточек | `core/ui_shared/styles.py` | — |
| UI-1.2 | Новый `MainWindow`: header (лого + StatusPill) + 3-колоночный workspace | `ui/main_window.py` | UI-1.1 |
| UI-1.3 | Sidebar с NavBtn (step-num + icon + label), состояния: default / active / done | `ui/main_window.py` | UI-1.2 |
| UI-1.4 | Правая панель: CharSection (**аватар `rozitta_idle.png`** + имя + подсказка) + LogSection + ProgressSection + StartBtn | `ui/main_window.py` | UI-1.2 |
| UI-1.5 | LogSection: фильтры (Все/Инфо/Успех/Предупр./Ошибки) + кнопки очистки/копирования | `ui/main_window.py` | UI-1.4 |
| UI-1.6 | Встроить существующие AuthScreen и ChatsScreen как Tab 1 / Tab 2 | `ui/main_window.py` | UI-1.2 |
| UI-1.7 | Toast-уведомления (замена QMessageBox): success / error / warning / info | `core/ui_shared/widgets.py` | — |

**Ожидаемый результат:** Приложение запускается, Auth и Chats работают в новой оболочке. Правая панель видна всегда.

---

### ✅ ФАЗА UI-2 — Redesign Settings Tab (ЗАВЕРШЕНА)

> **Задача:** Создать новый `SettingsPanel` виджет (вкладка 3), который заменяет старый ParseSettingsScreen.
> **Трогаем:** `ui/main_window.py` (добавить SettingsPanel) и подключить к существующим воркерам.

| # | Задача | Файл | Зависимости |
|---|--------|------|-------------|
| UI-2.1 | MediaGrid — 5 toggle-кнопок (Фото/Видео/Кружки/Голос/Файлы) | `ui/main_window.py` | UI-1 |
| UI-2.2 | Slider параллельных загрузок (1–8) + label | `ui/main_window.py` | UI-1 |
| UI-2.3 | DateBox с двумя полями (dateFrom / dateTo) | `ui/main_window.py` | UI-1 |
| UI-2.4 | UserFilter: btn "Загрузить участников" + ModeSelect + UserTags | `ui/main_window.py` | UI-1 |
| UI-2.5 | AdvancedFilters (collapse): keywords, чекбоксы, minViews | `ui/main_window.py` | UI-2.4 |
| UI-2.6 | SplitGrid (Единый/Дни/Месяцы/Посты) + toggle комментариев | `ui/main_window.py` | UI-1 |
| UI-2.7 | ExportSection: FormatRow (**независимые toggle-чипы** DOCX/JSON/HTML — см. ниже) + путь + выбор папки | `ui/main_window.py` | UI-1 |
| UI-2.8 | STT chips в Settings: [Видео \| Аудио \| Кружки] — включение/выключение | `ui/main_window.py` | UI-1 |
| UI-2.9 | Подключить StartBtn к цепочке Parse→STT→Export через существующие воркеры | `ui/main_window.py` | UI-2.1..8 |
| UI-2.10 | SidebarInfo: обновлять "Выбранный чат" при выборе в ChatsScreen | `ui/main_window.py` | UI-1.6 |

> **⚠️ UI-2.7 УТОЧНЕНИЕ (2026-03-14):** FormatRow [DOCX | JSON | HTML] — это **независимые toggle-чипы**,
> НЕ QButtonGroup / radio-group. Каждая кнопка `setCheckable(True)`, без `setExclusive(True)`.
> Пользователь выбирает любую комбинацию форматов. `ExportParams.export_formats: list[str]` собирается
> из всех активных (checked) кнопок. По умолчанию активен только DOCX.

**Ожидаемый результат:** Полный функциональный цикл работает через новый UI. Старый ParseSettingsScreen выведен из использования.

---

### 🔴 ФАЗА BUG-FIX (ТЕКУЩИЙ ПРИОРИТЕТ)

| # | Задача | Файл | Статус |
|---|--------|------|--------|
| BF-1 | `GetForumTopicsRequest` — позиционные аргументы + InputChannel | `features/chats/api.py` | ✅ ЗАВЕРШЁН |
| BF-2 | `GetDiscussionMessageRequest` для пост+комментарии | `features/parser/api.py` | ⚪ В очереди |
| BF-3 | linked_chat_id — ленивая загрузка при выборе канала вместо bulk | `features/chats/api.py`, `ui/main_window.py` | ✅ ЗАВЕРШЁН 2026-03-18 |
| BF-4 | Фильтрация по участникам | `features/parser/api.py` | ✅ ЗАВЕРШЁН |
| PERF-1 | **Медленная загрузка чатов** — FloodWait на новых сессиях. Частичные меры: кэш диалогов, лимит 500, lazy linked_chat. Ожидаем анализ от сообщества (Habr/GitHub issues) | — | 🔴 В работе |

---

### ✅ ФАЗА EXPORT — Форматы экспорта (ЗАВЕРШЕНА)

| # | Задача | Файл | Статус |
|---|--------|------|--------|
| EX-1 | **JSON экспорт** — `JsonGenerator`, плоский список объектов, STT-поле | `features/export/generator.py` | ✅ РЕАЛИЗОВАНО |
| EX-2 | **HTML экспорт** | `features/export/generator.py` | ⚪ В очереди |
| EX-3 | **FormatRow** — DOCX / JSON / MD / HTML toggle-чипы | `ui/main_window.py` | ✅ РЕАЛИЗОВАНО |
| EX-4 | **ExportParams** — `export_formats` + `ai_split` | `features/export/ui.py` | ✅ РЕАЛИЗОВАНО |
| EX-5 | **Markdown экспорт** — `MarkdownGenerator` | `features/export/generator.py` | ✅ РЕАЛИЗОВАНО |
| EX-6 | **AI-split чанкинг** — разбивка MD/JSON по 300к слов | `features/export/generator.py` | ✅ РЕАЛИЗОВАНО |

---

### ✅ ФАЗА TDL-AUTH — Авторизация без кода (ЗАВЕРШЕНА)

| # | Задача | Файл | Статус |
|---|--------|------|--------|
| TDL-1 | **tdata импорт** — `detect_tdata_path()` + `import_from_tdata()` | `features/auth/api.py` | ✅ РЕАЛИЗОВАНО |
| TDL-2 | **UI кнопка** — `TdataImportWorker` + диалог + автодетект пути | `features/auth/ui.py` | ✅ РЕАЛИЗОВАНО |
| TDL-3 | QR-авторизация | `features/auth/*.py` | ⚪ P3-5 |
| TDL-4 | Takeout API для медиа | `features/parser/api.py` | ⚪ В очереди |

---

### 🔧 ФАЗА CFG-1 — Proxy Support (не начата)

| # | Задача | Файл |
|---|--------|------|
| CFG-1-1 | `ProxyConfig` dataclass в `AppConfig` | `config.py` |
| CFG-1-2 | Хелпер `_build_client(cfg)` с прокси | `core/utils.py` |
| CFG-1-3 | UI-секция "Прокси" в SettingsPanel | `ui/main_window.py` |
| CFG-1-4 | Сохранение `ProxyConfig` в `config.json` | `config.py` |

---

### 🟡 ФАЗА P1 — Backend Improvements (не начата)

| # | Задача | Файл |
|---|--------|------|
| P1-1 | **DownloadTracker** — инкрементальный трекер | `core/utils.py`, `features/parser/api.py` |
| P1-2 | Toggle "Перекачать медиа" в SettingsPanel | `ui/main_window.py` |
| P1-3 | **@async_retry** — декоратор с exponential backoff | `core/retry.py` ✅ уже есть |

---

### 🔵 ФАЗА P2 — Performance & Filters (после P1)

| # | Задача | Файл |
|---|--------|------|
| P2-1 | `asyncio.Semaphore(3)` параллельная загрузка медиа | `features/parser/api.py` |
| P2-2 | Expression filter (`simpleeval`) + UI-поле | `features/parser/api.py`, `ui/main_window.py` |
| P2-3 | `upsert_messages_batch` — идемпотентность | `core/database.py` |
| P2-4 | STT-video — добавить `video` в `STT_FILE_TYPES` | `core/stt/worker.py` |
| P2-5 | STT-GPU — CUDA через `AppConfig` | `config.py`, `core/stt/whisper_manager.py` |

---

### 🌍 ФАЗА I18N — Поддержка английского языка (запланирована)

> **Подход:** переключатель ru/en в настройках, строки вынесены в словари.
> **Приоритет:** после стабилизации P2 — не блокирует текущий функционал.

| # | Задача | Файл |
|---|--------|------|
| I18N-1 | Создать `core/i18n.py` — словари `STRINGS_RU` / `STRINGS_EN`, функция `t(key)` | `core/i18n.py` (новый) |
| I18N-2 | Переключатель языка в SettingsPanel (сохраняется в `config_modern.json`) | `ui/main_window.py`, `config.py` |
| I18N-3 | Заменить все строки UI на `t(...)` | все `ui/` и `features/*/ui.py` |
| I18N-4 | README и документация на EN уже добавлены | `README.md` | ✅ |

---

### ⚪ ФАЗА P3 — Quality & Features (пауза)

| # | Задача | Файл |
|---|--------|------|
| P3-1 | `PRAGMA wal_autocheckpoint = 100` | `core/database.py` |
| P3-2..4 | pytest: database, merger, utils, export, parser | `tests/` |
| P3-5 | QR-авторизация | `features/auth/*.py` |
| P3-6 | CI GitHub Actions: pytest + mypy | `.github/workflows/` |
| P3-7 | PyInstaller .exe bundle (opentele в hiddenimports) | `rozitta_parser.spec` |
| P3-8 | Пауза/отмена парсинга (asyncio.Event) | `features/parser/api.py` |

---

## 🐛 4. ИСТОРИЯ ИСПРАВЛЕНИЙ

### ✅ ВСЕ КРИТИЧЕСКИЕ ПРОБЛЕМЫ ИСПРАВЛЕНЫ:

| # | Проблема | Решение | Дата |
|---|----------|---------|------|
| CR-1..CR-3 | Критические баги парсера | Hotfix | 2026-02-17 |
| TD-5 | character_state Signal | Hotfix | 2026-02-17 |
| CSS-текст | Невидимый текст в ChatsListWidget | `_refresh_style()` с правилами для дочерних QLabel | 2026-02-22 |
| RCA-6 | cfg-рассинхронизация ui↔api (TypeError на парсинге) | Правильная сигнатура | 2026-03-08 |
| RCA-5 | per-message commit в `_cursor()` | `insert_messages_batch()` | 2026-03-08 |
| RCA-5b | progress Signal всегда 0 | двухфазный emit | 2026-03-08 |
| DB-LOCK | database is locked при загрузке чатов | SessionCheckWorker disconnect в finally, AuthScreen guard, ParseWorker создаёт собственный клиент | 2026-03-08 |
| RCA-7 | Парсер зависает молча на приватных чатах | Добавлены `[DIAG]` логи в 9 ключевых точках | 2026-03-09 |
| RCA-8 | `message.download_media()` зависает навсегда | `asyncio.wait_for(..., timeout=120.0)` внутри семафора | 2026-03-09 |
| RCA-9 | `asyncio.gather()` в `_flush_tasks` зависает | `asyncio.wait_for(gather(...), timeout=300.0)` | 2026-03-09 |
| RCA-10 | DOCX генерируется 4 раза | `Qt.UniqueConnection` + именованный слот | 2026-03-09 |
| RCA-11 | 10 воркеров без `UniqueConnection` | Добавлен `Qt.UniqueConnection` на все 22 `.connect()` | 2026-03-10 |
| RCA-12 | DOCX не открывается (битая XML-ссылка) | `os.path.exists(media_path)` перед `add_external_hyperlink` | 2026-03-10 |
| BF-1 | `GetForumTopicsRequest`: позиционные аргументы + entity + functions.messages | Исправлено | 2026-03-10 |
| BUG-1-fix | `entity = first_chat` перезаписывал entity без access_hash | Строка удалена | 2026-03-10 |
| RCA-13 | DOCX битые файлы — NameError + двойной ExportWorker | `comments: list = []` guard + logger | 2026-03-10 |

### 🎙️ STT — ✅ РЕАЛИЗОВАНО (2026-03-09)

| Файл | Что сделано |
|------|-------------|
| `core/stt/audio_converter.py` | AudioConverter (резервный, без WAV для WhisperManager) |
| `core/stt/whisper_manager.py` | WhisperManager Singleton — прямая подача .ogg/.mp4 |
| `core/stt/worker.py` | STTWorker(QThread) — пакетная транскрипция, прогресс |
| `core/database.py` | Таблица `transcriptions` + 4 метода |
| `ui/main_window.py` | Цепочка Parse → STT → Export |
| `features/export/generator.py` | Транскрипции в DOCX («🎙 Распознанная речь:») |

---

## 🐛 4b. БАГИ (обновлено 2026-03-23)

| # | Описание | Файл | Статус |
|---|----------|------|--------|
| BUG-2 | Посты + комментарии: `include_comments` не передавался в ExportParams | `ui/main_window.py` | ✅ ИСПРАВЛЕН |
| BUG-3 | linked_chat_id: lazy-загрузка при выборе канала | `features/chats/api.py` | ✅ ИСПРАВЛЕН |
| BUG-4 | Фильтрация по участникам: `user_id` → `user_ids: List[int]` | `features/parser/api.py` | ✅ ИСПРАВЛЕН |
| BUG-5 | `Signal(dict)` → RuntimeError в PySide6 | `features/chats/ui.py` | ✅ ИСПРАВЛЕН |
| BUG-6 | TopicsWorker: 0 веток | `features/chats/ui.py` | ✅ ИСПРАВЛЕН |
| BUG-7 | `database is locked` race condition | `features/auth/ui.py` | ✅ ИСПРАВЛЕН |
| BUG-8 | api_id/hash/phone не сохранялись | `features/auth/ui.py` | ✅ ИСПРАВЛЕН |
| BUG-9 | STT запускался при выключенных чипах | `ui/main_window.py` | ✅ ИСПРАВЛЕН |
| BUG-10 | Статус «Генерация DOCX» — хардкод | `ui/main_window.py` | ✅ ИСПРАВЛЕН |
| BUG-11 | Артефакт-линия в заголовках секций | `core/ui_shared/widgets.py` | ✅ ИСПРАВЛЕН |
| BUG-12 | Кнопки фильтра лога обрезались | `core/ui_shared/styles.py` | ✅ ИСПРАВЛЕН |
| BUG-13 | GetForumTopicsRequest: Channel вместо InputChannel | `features/chats/api.py` | ✅ ИСПРАВЛЕН |
| BUG-14 | faster-whisper автоустановка запускала второй .exe | `core/stt/whisper_manager.py` | ✅ ИСПРАВЛЕН 2026-03-23 |
| BUG-15 | Файлы JSON/MD не содержали дату и топик в имени — перезаписывали друг друга | `features/export/generator.py` | ✅ ИСПРАВЛЕН 2026-03-23 |
| BUG-16 | GetForumTopicsRequest: именованные аргументы + пагинация + get_input_entity | `features/chats/api.py` | ✅ ИСПРАВЛЕН 2026-03-23 |
| PERF-1 | Загрузка чатов ~30 мин — Telegram FloodWait на новых сессиях | — | 🟡 Частично (кэш + lazy + адаптивные паузы) |

---

### ✅ ФАЗА TDL-AUTH — Авторизация без кода (ЧАСТИЧНО РЕАЛИЗОВАНА)

| # | Задача | Файл | Статус |
|---|--------|------|--------|
| TDL-1 | **tdata импорт** — `AuthService.import_from_tdata()` + `detect_tdata_path()` | `features/auth/api.py` | ✅ РЕАЛИЗОВАНО 2026-03-18 |
| TDL-2 | **UI кнопка** — «🖥️ Импорт из Telegram Desktop» + `TdataImportWorker` + диалог выбора папки | `features/auth/ui.py` | ✅ РЕАЛИЗОВАНО 2026-03-18 |
| TDL-3 | **QR-авторизация** — `client.qr_login()` + QLabel с QPixmap | `features/auth/api.py`, `features/auth/ui.py` | ⚪ В очереди (P3-5) |
| TDL-4 | **Takeout API** — `async with client.takeout(files=True)` для медиа | `features/parser/api.py` | ⚪ В очереди |

> **Зависимость:** `pip install opentele` (включена в `requirements.txt`, в `.spec` в hiddenimports)
> **Результат:** пользователь нажимает кнопку, выбирает папку tdata — вход без кода за ~5 сек.

---

---

## 📈 5. МЕТРИКИ КАЧЕСТВА КОДА

| Метрика | Было | Сейчас | Норма | Статус |
|---------|------|--------|-------|--------|
| Строк в монолите | 3279 | 0 | — | ✅ |
| Средний размер модуля | — | ~390 | <400 | ✅ |
| Цикломатическая сложность | ~40 | ~7 | <10 | ✅ |
| Дублирование кода | ~15% | ~3% | <5% | ✅ |
| Покрытие тестами | 0% | ~30% | >80% | 🔄 P3 |
| Типизация (type hints) | ~30% | ~95% | >90% | ✅ |

---

## 📐 6. ПРИНЯТЫЕ АРХИТЕКТУРНЫЕ РЕШЕНИЯ

### ID нормализация:
- `finalize_telegram_id(raw_id, entity_type)` из `core/utils.py`

### Соединения с БД:
- thread-local — каждый поток получает своё соединение
- Только через `DBManager`, никогда `sqlite3.connect()` напрямую

### Qt-изоляция:
- `features/*/api.py` + `core/merger.py` + `core/stt/*.py` — **никакого Qt**
- `features/*/ui.py` + `core/ui_shared/` + `core/stt/worker.py` — весь Qt-код

### TelegramClient изоляция:
- Каждый воркер создаёт свой `TelegramClient`, connect → work → disconnect в finally
- MainWindow НЕ хранит постоянный `self._client`

### ui_shared расположение:
- `core/ui_shared/` — правильный импорт: `from core.ui_shared.widgets import ...`
- `ui_shared/` в корне — legacy, НЕ импортировать

### CSS в Qt:
- Цвета дочерних QLabel — через stylesheet РОДИТЕЛЯ (правило каскада)
- Отдельный `setStyleSheet()` на каждом дочернем виджете не использовать

### STT архитектура:
- Singleton через `WhisperManager.instance()` — модель грузится один раз
- Кэш в SQLite: проверка по `(message_id, peer_id)` перед транскрипцией
- `WhisperManager.unload()` в finally STTWorker

### Batch I/O (обязательно):
- `insert_messages_batch()` — 1 commit / 200 сообщений
- НЕ `insert_message()` в цикле (500× медленнее)

### Формат Export (обязательно):
- FormatRow [DOCX | JSON | MD | HTML] — **независимые toggle-чипы**, НЕ radio-group
- `QPushButton.setCheckable(True)` без `QButtonGroup.setExclusive(True)`
- `ExportParams.export_formats: list[str]` — список всех активных форматов
- `ExportParams.ai_split: bool` — чанкинг JSON/MD по 300к слов; **DOCX всегда единый файл**
- `JsonGenerator.generate()` и `MarkdownGenerator.generate()` возвращают `List[str]` (список путей)

### AuthWorker → ChatsWorker race condition (обязательно):
- `AuthWorker._auth()` отключает client внутри своего event loop **до** `auth_complete.emit`
- `auth_complete` передаёт `(None, user)` — живой client не покидает воркер
- `MainWindow._on_auth_complete()` запускает ChatsWorker через `QTimer.singleShot(300)` — даёт AuthWorker завершить `loop.close()`
- ❌ ЗАПРЕЩЕНО: `asyncio.new_event_loop().run_until_complete(client.disconnect())` в главном потоке

### Сохранение конфига (обязательно):
- `save_config(self._cfg)` вызывается в `AuthScreen._on_auth_complete()` после успешного входа
- Сохраняет: `api_id`, `api_hash`, `phone` → `config_modern.json`
- Обеспечивает автозаполнение формы при следующем запуске

### Прокси / стабильность Telegram (CFG-1):
- Все воркеры создают `TelegramClient` через хелпер `_build_client(cfg)` — единая точка, где применяется прокси
- `ProxyConfig` хранится в `AppConfig`, сериализуется в `config.json`
- Рекомендуемый тип: **SOCKS5** (`python-socks`) — универсален для любого локального VPN-клиента
- MTProto прокси — второй тип, специфичен для Telegram
- Детали реализации и UI-спецификация: см. раздел **🌐 ПРОКСИ** в `CLAUDE.md`

---

**Анализ создан:** 2025-02-12
**Последнее обновление:** 2026-03-23 (SOCKS5/Tor прокси, имена файлов с датой/топиком, кэш бессрочный, fix whisper в .exe, скролл авторизации, логи авторизации)
**Версия:** 4.5
**Автор:** Claude (Anthropic)
