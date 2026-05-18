# 📊 АНАЛИЗ ПРОЕКТА ROZITTA PARSER

---

## 🗺️ 0. Интерактивная карта зависимостей

**Онлайн:** https://nynchezyabka.github.io/RozittaParser/map.html
**Локально:** `docs/map.html` — открыть в браузере напрямую.

### Модульные метки GitHub Issues (обязательно добавлять при создании задачи)

| Метка | Модуль | Файлы |
|-------|--------|-------|
| `module:auth` | Авторизация | `features/auth/` |
| `module:chats` | Список чатов | `features/chats/` |
| `module:parser` | Парсер сообщений | `features/parser/` |
| `module:export` | Экспорт | `features/export/` |
| `module:database` | База данных | `core/database.py` |
| `module:stt` | Распознавание речи | `core/stt/` |
| `module:ui` | Интерфейс | `ui/main_window.py` |
| `module:config` | Настройки | `config.py` |

---

## 🚨 1. CRITICAL HOTFIX (2026-02-17) — ЗАВЕРШЕНО

| ID | Тип | Описание | Статус |
|----|-----|----------|--------|
| CR-1 | 🔴 CRITICAL | Schema Mismatch: `file_type`, `file_size`, `linked_chat_id` | ✅ Исправлен |
| CR-2 | 🔴 CRITICAL | Infinite Loop при FloodWait: `continue` → `break` | ✅ Исправлен |
| CR-3 | 🔴 CRITICAL | Silent Failures в `_get_post_replies` | ✅ Исправлен |
| TD-5 | 🟡 TECH DEBT | Воркеры без `character_state = Signal(str)` | ✅ Добавлен |

---

## 🏗️ 2. АРХИТЕКТУРА (Feature-based)

```
rozitta_parser/
│
├── main.py                     ✅ Full-версия
├── main_lite.py                🟡 Lite-версия (в разработке)
├── config.py                   ✅ AppConfig с ProxyConfig
│
├── core/
│   ├── utils.py                ✅ finalize_telegram_id, sanitize_filename, is_image_path
│   ├── database.py             ✅ WAL, batch I/O, transcriptions, merge_group
│   ├── logger.py               ✅ разделитель сессий
│   ├── exceptions.py           ✅
│   ├── merger.py               ✅ MergerService O(n)
│   ├── retry.py                ✅ @async_retry
│   ├── ui_shared/              ✅ widgets, styles, calendar
│   └── stt/                    ✅ WhisperManager (instance восстановлен) + STTWorker
│
├── features/
│   ├── auth/api.py             ✅ build_client (api_id баг исправлен)
│   ├── auth/ui.py              ✅ cancel btn; MTProto вручную/ссылка
│   ├── chats/api.py            ✅ MTProto-ускорение
│   ├── chats/ui.py             ✅ selected_topic_id, selected_topic_name в chat dict
│   ├── parser/api.py           ✅ batch I/O, форумы, topic_id
│   ├── parser/ui.py            ✅ ParseParams с username, user_ids, thread_mode
│   ├── export/generator.py     ✅ все генераторы; topic_name/username в именах файлов
│   ├── export/xml_magic.py     ✅
│   └── export/ui.py            ✅ ExportParams с topic_name, username
│
├── ui/
│   └── main_window.py          ✅ рабочий SettingsPanel; _run_export с username
│
└── docs/
    └── map.html                ✅ Граф + GitHub Issues
```

---

## 🎨 3. UI — Текущий макет (вкладки)

```
QMainWindow
└── QWidget (central)
    ├── Header (52px): лого + StatusPill
    └── Workspace
        ├── Sidebar (196px): NavBtn × 3 (Авторизация / Чаты / Настройки)
        ├── MainContent (QStackedWidget):
        │   ├── Tab 1: AuthScreen
        │   │   ├── API ID / Hash / Phone
        │   │   ├── ProxySection: SOCKS5 | MTProto (ссылка / вручную)
        │   │   ├── [🔐 Войти] + [✕ Отмена]
        │   │   └── [🖥️ Импорт из Telegram Desktop]
        │   ├── Tab 2: ChatsScreen (коллапсируемые секции + выбор топика)
        │   └── Tab 3: SettingsPanel
        │       ├── MediaGrid: Фото/Видео/Кружки/Голос/Файлы
        │       ├── STT chips: Голосовые / Кружочки
        │       ├── DateBox: dateFrom / dateTo
        │       ├── UserFilter: теги участников + режим (только сообщения / все ветки)
        │       ├── SplitGrid: Единый / Дни / Месяцы / Посты
        │       └── ExportSection:
        │           ├── FormatRow: [DOCX | JSON | MD | HTML]
        │           └── AI-split тоггл + спинбокс размера чанка
        └── RightPanel (308px):
            ├── CharSection: аватар rozitta_idle.png
            ├── LogSection: фильтры + QTextEdit
            ├── ProgressSection
            └── StartSection: кнопка ▶ НАЧАТЬ ПАРСИНГ
```

---

## 🗺️ 4. ROADMAP (2026-05-16)

---

### ✅ ЗАВЕРШЁННЫЕ ФАЗЫ

| Фаза | Описание | Дата |
|------|----------|------|
| UI-1 | Redesign Main Window — вкладки | 2026-03 |
| UI-2 | Redesign Settings Tab | 2026-03 |
| EXPORT | Форматы DOCX/JSON/MD/HTML, AI-split, чанкинг | 2026-04-03 |
| TDL-AUTH | tdata импорт (частично) | 2026-03 |
| CFG-1 | Proxy Support (SOCKS5 + MTProto) | 2026-03 |
| AUTH-UX | Улучшение UX авторизации | 2026-04-03 |
| NAMES-1 | topic_name + username в именах файлов экспорта | 2026-05-16 |

---

### 🔴 ФАЗА BUG-FIX (ТЕКУЩИЙ ПРИОРИТЕТ)

| # | Задача | Файл | Статус |
|---|--------|------|--------|
| **BF-2** | **Посты + комментарии** — подробный Issue ниже | `features/parser/api.py` | 🔴 В работе |
| **BUG-18** | **OpenTele**: при импорте всегда предлагается установить библиотеку | `features/auth/ui.py`, `api.py` | 🔴 |
| **BUG-19** | **DOCX**: нет превью видео (thumbnail или placeholder) | `features/export/generator.py` | 🟡 |
| **DB-LOCK-2** | «database is locked» периодически при параллельной записи | `core/database.py` | 🟡 |

---

### 🟡 ФАЗА REF — Рефакторинг (личные задачи автора)

| # | Задача | Файл | Статус | Примечание |
|---|--------|------|--------|------------|
| **REF-1** | `build_export_filename()` — единая функция именования файлов | `features/export/generator.py` | 🟡 | Личная задача |
| **REF-2** | Анализ кода на дублирование, запахи, неиспользуемые участки | все модули | 🟡 | Личная задача |
| **REF-3** | Анализ покрытия тестами — проверить, все ли ключевые сценарии покрыты | `tests/` | 🟡 | Личная задача |

---

### 🟡 ФАЗА ARCH-1 — Анализ задвоенного SettingsPanel

**Проблема:** в проекте существуют два отдельных класса настроек.

| Файл | Статус | Используется? |
|------|--------|---------------|
| `ui/main_window.py` — старый `SettingsPanel` | ✅ работает | ДА — `_settings_screen` указывает на него |
| `features/parser/ui.py` — новый `SettingsPanel` | написан | НЕТ — не подключён к `_run_export` |

**Что нужно сделать:** проанализировать оба варианта — что есть в каждом, чего не хватает, стоит ли переключать. Это отдельная задача для изучения кода, решение принимается после анализа.

**Симптомы задвоения:**
- `get_params()` существует в двух файлах
- `_members_combo` (старый виджет) vs `_member_tags` (новый виджет с тегами)
- `username` пришлось добавлять в старый `get_params()`, хотя в новом он уже есть правильно

---

### 🟡 ФАЗА UI-CLEAN — Очистка интерфейса

| # | Задача | Статус |
|---|--------|--------|
| **UI-CLEAN-1** | Убрать неработающие/неактуальные настройки из UI | 🟡 |
| **UI-CLEAN-2** | Уточнить что делает `filter_expression` — работает или нет | 🟡 |

---

### 🟡 ФАЗА UI-REDESIGN — Редизайн интерфейса

На основе прототипа. Все задачи требуют предварительного анализа текущего кода.

| # | Задача | Описание | Статус |
|---|--------|----------|--------|
| **RD-1** | Wizard-навигация | 4 пронумерованных шага вместо вкладок; шаги 2-4 заблокированы пока не выполнен предыдущий; кнопка «Начать парсинг» заблокирована пока не заполнены обязательные поля | 🟡 |
| **RD-2** | Авторизация — QR-код | Вкладка QR-код рядом с «Телефон» | 🟡 |
| **RD-3** | Список чатов — иерархия | Бейдж «есть обсуждение» на канале; linked group показывается с отступом под каналом | 🟡 |
| **RD-4** | Настройки — выбор папки | Поле выбора папки сохранения (по умолчанию `output/` рядом с .exe, можно изменить) | 🟡 |
| **RD-5** | Настройки — дополнительные фильтры | Поле ключевых слов; чекбоксы «Только с медиа» / «Только с видео» | 🟡 |
| **RD-6** | Экран запуска — Сводка | Новый шаг 4: список всех выбранных параметров с кнопками «Изменить» для каждого | 🟡 |
| **RD-7** | Модальное подтверждение | Диалог «Подтвердите запуск» с перечнем параметров перед стартом парсинга | 🟡 |
| **RD-8** | Оценка экспорта | Карточка с предварительным подсчётом сообщений и размера по данным из БД. Если данных в БД нет — карточку скрыть | 🟡 |
| **RD-9** | Компоновка настроек | Переработать порядок и расположение элементов: компактнее, с прокруткой как в прототипе, логичный порядок секций. Убрать ползунок глубины скачивания (занимает место, дублирует календарь) | 🟡 |
| **RD-10** | Прокси → дополнительные настройки | Убрать ProxySection с главного экрана авторизации, перенести в скрытый раздел «Дополнительные настройки» | 🟡 |

---

### 🟡 ФАЗА FEAT — Новые функции

| # | Задача | Файл | Статус |
|---|--------|------|--------|
| **FEAT-1** | **Thread mode** — скачивать ветки с выбранным участником (его сообщения + те, на которые он отвечает) | `features/parser/api.py`, `ui` | 🟡 |
| **FEAT-2** | **Роль участника** — добавить обозначение admin/member в экспорт участников | `features/export/participants.py` | 🟡 |
| **FEAT-3** | **STT постобработка** — улучшение качества транскрипции после Whisper (локальная эвристика или внешний API) | `core/stt/` | 🟡 |
| **FEAT-4** | **STT для видео** — добавить `"video"` в `STT_FILE_TYPES`; **постобработка текста** (капитализация, знаки препинания); транскрипции сохранять частями (по мере готовности) | `core/stt/worker.py`, `core/stt/whisper_manager.py` | 🟡 |

---

### 🟡 ФАЗА P2 — Performance & Filters

| # | Задача | Файл | Статус |
|---|--------|------|--------|
| P2-1 | `asyncio.Semaphore(3)` параллельная загрузка медиа | `features/parser/api.py` | ⚪ |
| P2-3 | `upsert_messages_batch` — идемпотентность | `core/database.py` | ⚪ |
| P2-5 | STT-GPU — CUDA через `AppConfig` | `config.py`, `core/stt/whisper_manager.py` | ⚪ |

---

### ⚪ ФАЗА P3 — Quality

| # | Задача | Статус |
|---|--------|--------|
| P3-2..4 | pytest покрытие >80% (проверить AI-тесты сначала) | ⚪ |
| P3-5 | QR-авторизация | ⚪ |
| P3-6 | CI GitHub Actions: pytest + mypy | ⚪ |
| P3-8 | Пауза/отмена парсинга (asyncio.Event) | ⚪ |

---

## 📋 5. ПОДРОБНЫЕ ISSUES

---

### 🔴 BF-2: Посты + комментарии из связанной группы

**Проблема:** `split_mode="post"` технически работает, но комментарии к постам собираются некорректно из-за спама в группе обсуждения.

**Схема которую нужно реализовать:**

```
Канал (основной)
  └── пост "Новый урок"
          ↓ Telegram автоматически пересылает в группу
Группа обсуждения
  ├── [forwarded] "Новый урок"  ← точка привязки, искать по forward_from_message_id
  │     ├── reply: "спасибо!"   ← комментарий ✅
  │     └── reply: "классно"   ← комментарий ✅
  ├── "привет всем"             ← параллельное сообщение, НЕ reply — игнорировать
  └── "кто здесь?"             ← параллельное сообщение, НЕ reply — игнорировать
```

**Алгоритм:**
1. Для каждого поста из канала — найти его копию в группе через `forward_from_message_id` (надёжно) или совпадение текста (резервный вариант)
2. Собрать все сообщения где `reply_to_msg_id == id_пересланного_поста`
3. Всё остальное — игнорировать

**Метки:** `module:parser`, `module:database`
**Файлы:** `features/parser/api.py`, `core/database.py`

---

### 🟡 FEAT-1: Thread mode

**Описание:** при выборе участника — два режима:
- «Только сообщения» (реализовано) — только сообщения выбранного участника
- «Все ветки» (нужно сделать) — сообщения участника + те сообщения других людей, на которые он отвечал (контекст переписки)

**Метки:** `module:parser`, `module:ui`
**Файлы:** `features/parser/api.py`, `ui/main_window.py`

---

## 🐛 6. ИСТОРИЯ БАГОВ

### Критические (исправлены 2026-02-17)
CR-1, CR-2, CR-3 — Schema Mismatch, Infinite Loop, Silent Failures.

### Системные баги (исправлены до 2026-04-03)
RCA-5 — RCA-13, BUG-1 — BUG-17 — см. версию 4.7 документа.

### Критические баги сессии 2026-04-03 (исправлены)
CR-4 — STT (`WhisperManager.instance()` не был `@classmethod`)
CR-5 — `ValueError: API ID cannot be empty`
CR-6 — `ExportWorker` не запускался

### Открытые баги

| # | Описание | Файл | Приоритет |
|---|----------|------|-----------|
| **BUG-18** | OpenTele: всегда предлагается установить библиотеку | `features/auth/ui.py` | 🔴 |
| **BUG-19** | DOCX: нет превью видео | `features/export/generator.py` | 🟡 |
| **DB-LOCK-2** | «database is locked» при параллельной записи | `core/database.py` | 🟡 |

---

## 📐 7. ПРИНЯТЫЕ АРХИТЕКТУРНЫЕ РЕШЕНИЯ

### ID нормализация
`finalize_telegram_id(raw_id, entity_type)` из `core/utils.py`

### TelegramClient изоляция
- `build_client(cfg)` — единственная точка создания клиента
- Каждый воркер: `build_client()` → `connect()` → работа → `disconnect()` в `finally`
- `MainWindow` НЕ хранит постоянный `self._client`

### Имена файлов экспорта
Шаблон: `{chat_title}[_{topic_name}][_{username}]_{kind}_{period_label}.{ext}`

Примеры:
```
Чат_новости_Natalia Lishak_archive_fullchat.docx   # topic + user
Чат_новости_archive_fullchat.docx                  # только topic
Чат_Natalia Lishak_archive_fullchat.docx           # только user
Чат_archive_fullchat.docx                          # ничего не выбрано
```

`username` берётся из `UserTag.username` → `ParseParams.username` → `ExportParams.username` → `generate(username=...)` → `_build_path()`.

### SQLite
- thread-local соединения через `DBManager`
- WAL + `busy_timeout=30000` + `synchronous=NORMAL`
- `insert_messages_batch()` — 1 commit / 200 сообщений
- STT: сохранение после каждого файла (не в конце батча) — защита от потери данных при падении

### Qt-изоляция
- `features/*/api.py` + `core/*.py` (кроме worker.py) — никакого Qt
- `features/*/ui.py` + `core/ui_shared/` + `core/stt/worker.py` — весь Qt-код

### ui_shared расположение
- `core/ui_shared/` — правильный импорт
- `ui_shared/` в корне — legacy, НЕ импортировать

## 🧩 Известные архитектурные проблемы (на будущее)

### MainWindow как координатор (нарушение SRP)
`MainWindow` совмещает: построение layout, навигацию, управление воркерами, обработку сигналов, тосты, прогресс, состояние персонажа. Это затрудняет тестирование и поддержку.

**Рекомендация (не срочно):** выделить `AppController` или `SessionManager` для управления потоком приложения, оставив в `MainWindow` только отображение.

---

## 📈 8. МЕТРИКИ КАЧЕСТВА КОДА

Для получения актуальных метрик запустите скрипт `metrics.py` из корня проекта
(см. инструкцию внутри скрипта). Он заполнит эту таблицу реальными данными.

| Метрика                       | Значение  | Норма | Инструмент  |
|-------------------------------|-----------|-------|-------------|
| Покрытие тестами              | 52.4%     | >80%  | pytest-cov  |
| Цикломатическая сложность avg | 3.2 (A)   | <10   | radon cc    |
| Типизация (mypy ошибок)       | 32 ошибок | 0     | mypy        |


---

## 🗺️ Интерактивная карта проекта

В планах — создание автоматически обновляемой карты зависимостей (Mermaid/d3). Однако анализ показал высокую сложность из-за множества связей между модулями. Требуется отдельное исследование, в приоритете не стоит.

---


## 🚀 9. ПЛАН РЕЛИЗА

### Желательно перед публичным релизом

| # | Задача | Файл |
|---|--------|------|
| R-1 | Исправить OpenTele detection (BUG-18) | `features/auth/ui.py` |
| R-2 | DOCX видео placeholder (BUG-19) | `features/export/generator.py` |
| R-3 | Smoke test: авторизация → чаты → парсинг → все форматы | — |
| R-4 | Проверить .spec и onefile-сборку | `rozitta_parser.spec` |

### После релиза (по приоритету)
1. BF-2 — посты + комментарии
2. UI-REDESIGN (RD-1..9)
3. FEAT-1 — thread mode
4. REF-1..3 — рефакторинг (личные задачи)
5. FEAT-3 — STT постобработка
6. P3 — тесты, CI

---

**Анализ создан:** 2025-02-12
**Последнее обновление:** 2026-05-18
**Версия:** 5.0
**Автор:** Claude (Anthropic)
