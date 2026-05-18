## 📐 Архитектура Rozitta Parser (контрибьюторская версия)

> 🗺️ [Интерактивная карта проекта](https://nynchezyabka.github.io/RozittaParser/map.html) — показывает модули и их связи с подсветкой issues.

### 🔥 Критические баги (срочно нужны правки)

| Проблема | Issue | Модуль | Файлы |
|----------|-------|--------|-------|
| **Экспорт игнорирует выбранные даты** | [#56](https://github.com/Nynchezyabka/RozittaParser/issues/56) | `export`, `database` | `ui/main_window.py`, `features/export/ui.py`, `core/database.py` |
| **STT не работает в .exe‑сборке** | — (создать) | `stt`, `build` | `core/stt/worker.py`, `rozitta_parser.spec` |
| **Фильтрация сообщений по участнику не работает** | [#67](https://github.com/Nynchezyabka/RozittaParser/issues/67) | `parser` | `features/parser/api.py` |
| **Список участников и комментарии к постам** — не собираются корректно из‑за спама в linked‑группе; требуется связывание пересланных постов с комментариями | [#27-2](https://github.com/Nynchezyabka/RozittaParser/issues/27-2), [#BF-2](https://github.com/Nynchezyabka/RozittaParser/issues/... ) | `parser` | `features/parser/api.py` |

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
parser → сохраняет в SQLite (messages, media)
    ↓
export → читает из SQLite → DOCX/MD/JSON/HTML
    ↓
STT (опционально) → читает голосовые, пишет в таблицу transcriptions
```

### 📌 Что делать, если хочешь помочь?

1. Выбери Issue из таблицы выше.
2. В комментарии к Issue напиши, что берёшь.
3. Изучи `CLAUDE.md` (там подробные правила кодирования).
4. Вноси изменения, создавай Pull Request (можно прямо из main, но лучше отдельная ветка).
