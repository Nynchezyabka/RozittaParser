# Архитектура Rozitta Parser

Актуальная схема модулей, потоки данных, список критических багов и план исправлений.  
Для разработчиков и тех, кто хочет разобраться в проекте.

---

## Три уровня системы

### Уровень А – Данные (SQLite)

| Таблица | Назначение | Статус |
|---------|------------|--------|
| messages | Все сообщения, медиа-пути, типы файлов, merge_group_id | ✅ работает |
| chats | Метаданные чатов (тип, linked_chat_id) | ✅ |
| topics | Ветки форумов (topic_id, title) | ✅ |
| transcriptions | Результаты STT | ⚠️ падает в .exe |
| cached_dialogs | Кэш списка диалогов (24 ч) | ✅ |

⚠️ **Критическое ограничение:** `DBManager.get_messages()` не принимает `date_from/date_to`. Экспорт выгружает всё из БД, игнорируя выбранный период.

---

### Уровень Б – Ядро (Telethon + бизнес-логика)

| Модуль | Вход | Выход | Файл | Статус |
|--------|------|-------|------|--------|
| auth | `AppConfig` | `User` | `features/auth/api.py` | ✅ |
| chats | `TelegramClient`, `limit`, `force_refresh` | `List[ChatDict]` | `features/chats/api.py` | ✅ |
| parser | `CollectParams` | `CollectResult` | `features/parser/api.py` | ⚠️ видео >50 МБ |
| export | `ExportParams` | `List[FilePath]` | `features/export/generator.py` | 🔴 нет фильтра дат |
| stt | `db_path`, `chat_id`, `model_size` | транскрипции в БД | `core/stt/worker.py` | 🔴 не работает в .exe |
| merger | `DBManager`, `chat_id`, `time_delta` | обновляет `merge_group_id` | `core/merger.py` | ✅ |

---

### Уровень В – Интерфейс (PySide6)

| Компонент | Функция | Статус |
|-----------|---------|--------|
| `AuthScreen` | Ввод api_id/hash/phone, прокси | ✅ |
| `ChatsScreen` | Список чатов, выбор топиков | ✅ |
| `SettingsPanel` | Выбор дат, медиа, участников, форматов | ✅ (UI) |
| `MainWindow._run_export` | Передача `ExportParams` в `ExportWorker` | ⚠️ не кладёт `date_from/date_to` |
| `RozittaWidget`, `LogWidget` | Статус, логи | ✅ |

---

## Схема потока данных

**Основной поток:**  
`Telegram API → ✅ AUTH → ✅ CHATS → ⚠️ PARSER (видео >50 МБ) → ✅ DB → 🔴 EXPORT (нет дат) → 📤 Файлы`

**Параллельный процесс STT:**  
`🔴 STT (в .exe сломан) → ✅ DB (transcriptions)`

> **Примечание:** PARSER содержит проблему с видео >50 МБ.


**Куда идут файлы:** NotebookLM, Mem.ai, Word/PDF (обработка не входит в приложение).

---

## Три критических бага для релиза

### 1. 🔴 Экспорт игнорирует выбранный период дат

- **Где сбой:** Уровень Б (SQL-запрос) + Уровень В (ExportParams)
- **Файлы:** `core/database.py` (`get_messages`), `features/export/generator.py`, `ui/main_window.py` (`_run_export`)
- **Причина:** `ExportParams` не имеет полей `date_from`/`date_to`; `get_messages` не добавляет `WHERE date >= ? AND date <= ?`
- **Исправление:** добавить поля в `ExportParams` → передать в генераторы → модифицировать SQL

### 2. ⚠️ Большие видео (>50 МБ) не скачиваются

- **Где сбой:** Уровень Б (`features/parser/api.py` → `_download_media`)
- **Причина:** единый `asyncio.wait_for` для всех файлов; большие файлы падают по таймауту
- **Исправление:** для файлов >50 МБ не использовать `wait_for` (или очень большой таймаут). Документировать, что >200 МБ требуют TeleGet.

### 3. 🔴 STT не работает в .exe-сборке

- **Где сбой:** инфраструктурный (PyInstaller + C-extensions)
- **Причина:** `faster-whisper` и `numpy` требуют динамических библиотек, которые PyInstaller не упаковывает автоматически
- **Рекомендуемое исправление:** не bundлить STT в .exe; при первом запуске устанавливать `faster-whisper` в отдельное venv (`%APPDATA%\RozittaParser\venv`) и вызывать через subprocess

---

## План действий (очередность)

1. **Smoke test** – зафиксировать текущие ошибки 
2. **Исправить фильтрацию дат** – добавить `date_from/date_to` в `ExportParams` и `get_messages` 
3. **Поправить скачивание больших видео** – адаптивный таймаут 
4. **Решить STT в exe** – внешний venv или bundling 
5. **Финальный тест** – все форматы + даты + .exe 

---

## Контракты модулей (для разработчиков)

### `CollectParams` (вход парсера)

| Поле | Тип | Описание |
|------|-----|-----------|
| `chat_id` | int | Нормализованный ID чата |
| `topic_id` | Optional[int] | ID топика форума |
| `days_limit` | int | Глубина (0 = всё) |
| `media_filter` | List[str] | `['photo','video','voice','video_note','file']` |
| `download_comments` | bool | Скачивать комментарии |
| `output_dir` | str | Папка для медиа |
| `re_download` | bool | Перезапись трекера |

### `ExportParams` (вход экспорта) – требует обновления

| Поле | Тип | Описание |
|------|-----|-----------|
| `chat_id` | int | |
| `chat_title` | str | |
| `split_mode` | str | `'none'|'day'|'month'|'post'` |
| `export_formats` | List[str] | `['docx','json','md','html']` |
| `ai_split` | bool | Чанкинг |
| `ai_split_chunk_words` | int | Размер чанка |
| `date_from` | Optional[str] | **ДОБАВИТЬ** – начало периода |
| `date_to` | Optional[str] | **ДОБАВИТЬ** – конец периода |

---

*Последнее обновление: апрель 2026.*
