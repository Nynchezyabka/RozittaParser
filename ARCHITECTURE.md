## 📐 Архитектура Rozitta Parser (контрибьюторская версия)

> 🗺️ [Интерактивная карта проекта](https://nynchezyabka.github.io/RozittaParser/map.html) — показывает модули и их связи с подсветкой issues.

### 🔥 Критические баги (срочно нужны правки)

| Проблема | Issue | Модуль | Файлы |
|----------|-------|--------|-------|
| **Посты + комментарии** — не собираются корректно из-за спама в linked‑группе; требуется связывание пересланных постов с комментариями через `forward_from_message_id` | [#27-2](https://github.com/Nynchezyabka/RozittaParser/issues/27-2), [#BF-2](https://github.com/Nynchezyabka/RozittaParser/issues/... ) | `parser`, `database` | `features/parser/api.py`, `core/database.py` |
| **Канал как участник** — сообщения Натальи в группе = 0 (sender_id=группы). Нужно включить канал/чат в participant list (Variant A-2) | I6 | `chats`, `parser`, `export` | `features/chats/api.py`, `features/export/generator.py` |
| **«По постам» для групп** — режим не имеет смысла для megagroups, кнопка должна быть неактивна | I3 | `ui`, `export` | `features/export/ui.py`, `ui/main_window.py` |

### 🟡 Известные проблемы (не критичные)

| Проблема | Модуль | Файлы | Примечание |
|----------|--------|-------|------------|
| **Пустые сообщения в экспорте канала** — из 3 постов 2 пустых, 1 корректный | `export` | `features/export/generator.py` | I1 |
| **Порядок grouped_media** — часть 2 идёт перед частью 1 | `parser`, `export` | `features/parser/api.py`, `features/export/generator.py` | I2 |
| **«Перекачать медиа»** — непонятное название кнопки | `ui`, `parser` | `features/parser/ui.py`, `ui/main_window.py` | I7 |
| **media=0 при обычном парсинге** — медиа скачивается только через отдельную кнопку | `parser` | `features/parser/api.py` | I8 |
| **Admin resolution в chats/api.py** — логика резолва channel→admin не нужна (Variant A-2) | `chats` | `features/chats/api.py` | I9 |
| **Дубли ExportWorker** — предупреждения о дублировании воркеров | `ui` | `ui/main_window.py` | I10 |
| **Channel-author "Unknown"** — будет решено в I6 (канал как участник) | `parser` | `features/parser/api.py` | UNKNOWN-1 → I6 |
| **DOCX: нет превью видео** | `export` | `features/export/generator.py` | BUG-19 |
| **«database is locked»** периодически при параллельной записи | `database` | `core/database.py` | DB-LOCK-2 |

### ✅ Исправлено в сессии 2026-05-27

| Баг | Описание | Файл |
|-----|----------|------|
| **C1** | `_iter_msg_count` не определена — парсинг падал | `features/parser/api.py` |
| **C2** | `_should_download()` — пропущен `self` в сигнатуре | `features/parser/api.py` |
| **C3** | Экспорт по пользователю возвращает все сообщения (include_channel_senders=True) | `features/export/generator.py` |
| **BUG-18** | OpenTele2: всегда предлагалось установить библиотеку | `features/auth/ui.py`, `features/auth/api.py` |

### 🧱 Модули (куда смотреть)

| Модуль | Задача | Основной файл |
|--------|--------|---------------|
| `auth` | Вход, сессии, tdata, прокси | `features/auth/api.py` |
| `chats` | Загрузка списка чатов, топиков | `features/chats/api.py` |
| `parser` | Скачивание сообщений и медиа | `features/parser/api.py` |
| `export` | Генерация DOCX/MD/JSON/HTML | `features/export/generator.py` |
| `stt` | Распознавание голосовых | `core/stt/worker.py` |
| `database` | Всё, что связано с SQLite | `core/database.py` |
| `ui` | Интерфейс (PySide6) | `ui/main_window.py` |

### 🔄 Поток данных

```
Telegram API
    ↓
parser → сохраняет в SQLite (messages, media, sender_type)
    ↓
export → читает из SQLite → DOCX/MD/JSON/HTML
    ↓
STT (опционально) → читает голосовые, пишет в таблицу transcriptions
```

### 🧵 Thread mode (✅ реализовано)

При выборе участника с режимом «Все ветки»:
```
parser: collect_data(user_filter_mode="threads")
    ↓
database: get_thread_pairs(chat_id, user_id) → List[(context, reply)]
    ↓
generator: _dedup_thread_messages(pairs) → [(row, depth, reply_author), ...]
    ↓
render по форматам:
    HTML  → CSS depth-0..depth-5 + margin-left
    DOCX  → 24pt × depth + "↳" + "↩ в ответ на: автор"
    MD    → 4 spaces × depth + "↳" + "*(в ответ на: автор)*"
    JSON  → flat list + depth + reply_to_author + type (thread_root/thread_reply)
```

### 🏷️ Variant A-2: Канал как участник

**Принятое решение:** канал/чат включается в participant list как равноправный отправитель.

- **Нет** резолва channel-sender → admin (ненадёжно, не соответствует Telegram)
- Сообщения от канала отображаются под именем канала, как в Telegram
- `sender_type` поле (`"user"` / `"channel"` / `"deleted"`) в DB schema v2
- При фильтре по пользователю: `include_channel_senders = False`
- Для доступа к сообщениям от имени канала — выбрать канал как участника (I6)

**«По постам»** — только для broadcast-каналов, не для групп (megagroups).

### 📌 Что делать, если хочешь помочь?

1. Выбери Issue из таблицы выше.
2. В комментарии к Issue напиши, что берёшь.
3. Изучи `CLAUDE.md` (там подробные правила кодирования).
4. Вноси изменения, создавай Pull Request (можно прямо из main, но лучше отдельная ветка).
