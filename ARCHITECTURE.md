## 📐 Архитектура Rozitta Parser (контрибьюторская версия)

> 🗺️ [Интерактивная карта проекта](https://nynchezyabka.github.io/RozittaParser/map.html) — показывает модули и их связи с подсветкой issues.

### 🔥 Критические баги (срочно нужны правки)

| Проблема | Issue | Модуль | Файлы |
|----------|-------|--------|-------|


### 🟡 Известные проблемы (не критичные)

| Проблема | Модуль | Файлы | Примечание |
|----------|--------|-------|------------|
| **Пустые сообщения в экспорте канала** — из 3 постов 2 пустых, 1 корректный | `export` | `features/export/generator.py` | I1 |
| **Порядок grouped_media** — часть 2 идёт перед частью 1 | `parser`, `export` | `features/parser/api.py`, `features/export/generator.py` | I2 |
| **«Перекачать медиа»** — непонятное название кнопки | `ui`, `parser` | `features/parser/ui.py`, `ui/main_window.py` | I7 |
| **media=0 при обычном парсинге** — медиа скачивается только через отдельную кнопку | `parser` | `features/parser/api.py` | I8 |
| **Дубли ExportWorker** — предупреждения о дублировании воркеров | `ui` | `ui/main_window.py` | I10 |
| **Channel-author "Unknown"** — в конкретных группах (требует per-group анализа) | `parser` | `features/parser/api.py` | UNKNOWN-1 |
| **Ветка `fix/channel-sender-and-participants` не влита** — миграции схемы, `sender_type`, слияние channel-sender в `get_user_stats()` | `core` | `core/database.py`, `features/chats/api.py` | — |
| **DOCX: нет превью видео** | `export` | `features/export/generator.py` | BUG-19 |
| **«database is locked»** периодически при параллельной записи | `database` | `core/database.py` | DB-LOCK-2 |

### ✅ Исправлено в сессии 2026-05-27

| Баг | Описание | Файл |
|-----|----------|------|
| **C1** | `_iter_msg_count` не определена — парсинг падал | `features/parser/api.py` |
| **C2** | `_should_download()` — пропущен `self` в сигнатуре | `features/parser/api.py` |
| **C3** | Экспорт по пользователю возвращает все сообщения (include_channel_senders=True) | `features/export/generator.py` |
| **BUG-18** | OpenTele2: всегда предлагалось установить библиотеку | `features/auth/ui.py`, `features/auth/api.py` |

### ✅ Исправлено в сессии 2026-06 (Variant A-2 + B1/B3)

| Баг | Описание | Файл |
|-----|----------|------|
| **I6** | Канал как участник — сообщения Натальи в группе = 0 (sender_id=группы). Теперь канал включён в participant list как равноправный отправитель | `features/chats/api.py`, `features/parser/api.py`, `features/export/generator.py` |
| **I3** | «По постам» для групп — режим не имеет смысла для megagroups, кнопка неактивна | `features/export/ui.py`, `ui/main_window.py` |
| **I9** | Admin resolution в chats/api.py — логика резолва channel→admin не нужна (Variant A-2) | `features/chats/api.py` |
| **B1/B3** | Channel-sender в `get_user_stats` возвращал ДВЕ записи канала (bare ID + marked ID) — экспорт от имени канала падал. Теперь записи слиты в одну с marked-negative ID | `features/chats/api.py` |

### ✅ Исправлено в сессии 2026-07-03 (v1.7.3 bugfix-релиз)

| Баг | Описание | Файл |
|-----|----------|------|
| **C2-reg** | Регрессия C2: `ParserService._should_download() takes 2 positional arguments but 3 were given` — снова пропал `self`, не скачивалось видео | `features/parser/api.py` |
| **B6** | `HtmlGenerator._format_message() takes 3 positional arguments but 4 were given` — HTML-экспорт падал на сообщениях от имени канала | `features/export/generator.py` |

**Причина регрессий:** между сессиями патчи теряли `self` при копировании/переименовании методов. Баги прошли незамеченными больше месяца, потому что smoke-тест не покрывал сценарии видео-скачивания и HTML-экспорта. Введено правило #18 в CLAUDE.md — простой smoke-тест перед каждым релизом.

### ✅ Исправлено в сессии 2026-07-06 (BF-2 — посты + комментарии)

| Баг | Описание | Файл |
|-----|----------|------|
| **BF-2** | Посты + комментарии: iter_messages шёл по linked-группе с post_id из нумерации канала → собирался чужой тред. Фикс: итерация по каналу (GetRepliesRequest) + обработка MsgIdInvalidError | `features/parser/api.py` |
| **BF-2b** | Инкрементальный режим: регистрация постов в posts_with_comments шла после проверки трекера → новые комментарии под старыми постами не докачивались. Регистрация перенесена выше tracker.is_downloaded | `features/parser/api.py` |

### 🧱 Модули (куда смотреть)

| Модуль | Задача | Основной файл |
|--------|--------|---------------|
| `auth` | Вход, сессии, tdata, прокси | `features/auth/api.py` |
| `chats` | Загрузка списка чатов, топиков, participants | `features/chats/api.py` |
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

### 🆔 Sender ID нормализация (новое, B1/B3)

В `core/database.py` метод `_telegram_user_id_variants(uid)` возвращает варианты ID для SQL-фильтрации:
- Для положительного ID: `[uid, -(1_000_000_000_000 + uid)]` — bare + marked
- Для marked-negative: `[uid, -uid - 1_000_000_000_000]` — marked + bare

Используется в `get_messages()` и `get_thread_pairs()`, чтобы находить сообщения канала как по bare, так и по marked-negative ID одного и того же entity.

В `get_user_stats()` (features/chats/api.py) дубликат channel-sender entries сливается в одну запись с marked-negative ID, чтобы в dropdown участника канал отображался один раз с правильным ID.

### 📦 Компонентная доставка ML-функций (новое, 2026-07)

**Принятое решение:** тяжёлые ML-функции (Florence-2/VLM, в перспективе STT видео)
НЕ пакуются в основной exe. Они собираются отдельными onedir-компонентами,
скачиваются по требованию при первом включении функции и вызываются как
subprocess по CLI-протоколу (JSON-файлы задание/результат).

- Причина: torch + веса не влезают в onefile (~65MB), Florence-2 не работает
  во frozen-окружении
- Компоненты — чистые функции «файлы → JSON», в SQLite пишет только главное
  приложение (не плодим участников DB-LOCK-2)
- Полная спецификация: [COMPONENTS.md](COMPONENTS.md), этапы внедрения CM-1..CM-4

### 📌 Что делать, если хочешь помочь?

1. Выбери Issue из таблицы выше.
2. В комментарии к Issue напиши, что берёшь.
3. Изучи `CLAUDE.md` (там подробные правила кодирования, включая правило #18 — smoke-тест перед релизом).
4. Вноси изменения, создавай Pull Request (можно прямо из main, но лучше отдельная ветка).

---

## 🚀 Текущий релиз: v1.7.3 (2026-07-03)

Bugfix-релиз, исправляющий регрессии v1.7.2:
- Парсинг чатов снова работает (C1-фикс удержался)
- Скачивание видео снова работает (C2-regression fix)
- Экспорт в HTML снова работает (B6 fix)

Полный чейнджлог — в [Releases](https://github.com/Nynchezyabka/RozittaParser/releases).
