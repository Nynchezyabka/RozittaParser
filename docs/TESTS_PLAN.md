# 🧪 ПЛАН ТЕСТИРОВАНИЯ — ROZITTA PARSER

---

## ⏱️ КОГДА ПЕРЕХОДИТЬ К ТЕСТАМ

> **Старт тест-фазы:** после завершения P2 (Performance & Filters).
> К этому моменту приложение должно стабильно проходить полный цикл:
> Auth → Chats → Parse → STT → Export (все три формата).
>
> **Порядок в фазе P3:**
> 1. P3-2: `test_database.py`
> 2. P3-3: `test_merger.py`
> 3. P3-4: `test_utils.py`
> 4. P3-4b: `test_export.py`
> 5. P3-4c: `test_parser.py` (с моками Telegram)
> 6. → только после прохождения всех тестов → P3-7 (EXE-сборка, **требует подтверждения**)
>
> **Файл тест-плана:** `TESTS_PLAN.md` (этот файл)
>
> **Установка зависимостей перед запуском:**
> ```bash
> pip install pytest pytest-asyncio pytest-mock pytest-cov pytest-timeout
> ```

---

## ⚠️ ВАЖНО: Актуальная структура модулей

> Тест-план был создан в период монолитной архитектуры (`backend.py`).
> После рефакторинга импорты изменились. Все тесты используют новые пути:

| Старый путь (устарел) | Актуальный путь |
|-----------------------|-----------------|
| `from backend import DBManager` | `from core.database import DBManager` |
| `from backend import finalize_telegram_id` | `from core.utils import finalize_telegram_id` |
| `from backend import TelegramArchiveManager` | Класс удалён. Логика разделена: |
| — `get_topics()` | `from features.chats.api import ChatsService` |
| — `collect_data()` | `from features.parser.api import ParserService, CollectParams` |
| — `generate_docx()` | `from features.export.generator import DocxGenerator` |
| `from backend import add_bookmark` | `from features.export.xml_magic import add_bookmark` |
| `from backend import write_text_with_links` | `from features.export.xml_magic import write_text_with_links` |

---

## 🔴 ВЫСОКИЙ ПРИОРИТЕТ

### 1. Database Operations — `tests/test_core/test_database.py`

```python
from core.database import DBManager

# --- Подключение ---

def test_connection_has_wal_mode():
    db = DBManager(":memory:")
    conn = db._get_connection()
    result = conn.execute("PRAGMA journal_mode").fetchone()
    assert result[0] == "wal"

def test_connection_has_timeout():
    db = DBManager(":memory:")
    conn = db._get_connection()
    assert conn.timeout == 60.0

def test_connection_isolation_level():
    db = DBManager(":memory:")
    conn = db._get_connection()
    assert conn.isolation_level is None  # Автокоммит

# --- insert_messages_batch ---

def test_insert_messages_batch_basic():
    db = DBManager(":memory:")
    messages = [
        {"chat_id": -100123, "message_id": 1, "date": "2025-02-12T10:00:00", "text": "Hello"},
        {"chat_id": -100123, "message_id": 2, "date": "2025-02-12T11:00:00", "text": "World"},
    ]
    db.insert_messages_batch(messages)
    result = db.get_messages(-100123)
    assert len(result) == 2

def test_insert_messages_batch_no_duplicate():
    """INSERT OR REPLACE — повтор не дублирует запись"""
    db = DBManager(":memory:")
    msg = {"chat_id": -100123, "message_id": 1, "date": "2025-02-12T10:00:00", "text": "Hello"}
    db.insert_messages_batch([msg])
    db.insert_messages_batch([msg])  # повтор
    result = db.get_messages(-100123)
    assert len(result) == 1

def test_insert_messages_batch_commit_every_200():
    """Проверяем что batch из 400 сообщений не падает и сохраняет всё"""
    db = DBManager(":memory:")
    messages = [
        {"chat_id": -100123, "message_id": i, "date": "2025-02-12T10:00:00", "text": f"msg{i}"}
        for i in range(400)
    ]
    db.insert_messages_batch(messages)
    result = db.get_messages(-100123)
    assert len(result) == 400

# --- get_messages ---

def test_get_messages_by_chat_id():
    db = DBManager(":memory:")
    db.insert_messages_batch([
        {"chat_id": -100123, "message_id": 1, "date": "2025-02-12T10:00:00"},
        {"chat_id": -100456, "message_id": 2, "date": "2025-02-12T10:00:00"},
    ])
    result = db.get_messages(-100123)
    assert len(result) == 1
    assert result[0]["message_id"] == 1

def test_get_messages_by_topic_id():
    db = DBManager(":memory:")
    db.insert_messages_batch([
        {"chat_id": -100123, "message_id": 1, "topic_id": 5, "date": "2025-02-12T10:00:00"},
        {"chat_id": -100123, "message_id": 2, "topic_id": 6, "date": "2025-02-12T10:00:00"},
    ])
    result = db.get_messages(-100123, topic_id=5)
    assert len(result) == 1

def test_get_messages_sorted_by_date():
    db = DBManager(":memory:")
    db.insert_messages_batch([
        {"chat_id": -100123, "message_id": 1, "date": "2025-02-12T10:00:00"},
        {"chat_id": -100123, "message_id": 2, "date": "2025-02-12T09:00:00"},
    ])
    result = db.get_messages(-100123)
    assert result[0]["message_id"] == 2  # более ранний первым

def test_get_messages_post_with_comments():
    db = DBManager(":memory:")
    db.insert_messages_batch([
        {"chat_id": -100123, "message_id": 100, "is_comment": 0, "date": "2025-02-12T10:00:00"},
        {"chat_id": -100123, "message_id": 101, "is_comment": 1, "post_id": 100, "date": "2025-02-12T10:01:00"},
        {"chat_id": -100123, "message_id": 102, "is_comment": 1, "post_id": 100, "date": "2025-02-12T10:02:00"},
    ])
    result = db.get_messages(-100123, post_id=100)
    assert len(result) == 3  # пост + 2 комментария

# --- transcriptions ---

def test_insert_and_get_transcription():
    db = DBManager(":memory:")
    db.insert_transcription(message_id=1, peer_id=-100123, text="Привет мир", model_type="base")
    result = db.get_transcription(message_id=1, peer_id=-100123)
    assert result == "Привет мир"

def test_transcription_no_duplicate():
    db = DBManager(":memory:")
    db.insert_transcription(1, -100123, "Первая версия", "base")
    db.insert_transcription(1, -100123, "Обновлённая версия", "base")  # повтор
    result = db.get_transcription(1, -100123)
    # INSERT OR REPLACE — должна остаться последняя версия
    assert result == "Обновлённая версия"

def test_get_stt_candidates():
    db = DBManager(":memory:")
    db.insert_messages_batch([
        {"chat_id": -100123, "message_id": 1, "file_type": "voice", "media_path": "/path/a.ogg", "date": "2025-02-12T10:00:00"},
        {"chat_id": -100123, "message_id": 2, "file_type": "video_note", "media_path": "/path/b.mp4", "date": "2025-02-12T10:01:00"},
        {"chat_id": -100123, "message_id": 3, "file_type": "photo", "media_path": "/path/c.jpg", "date": "2025-02-12T10:02:00"},
    ])
    candidates = db.get_stt_candidates(-100123, ["voice", "video_note"])
    assert len(candidates) == 2
```

---

### 2. ID Normalization — `tests/test_core/test_utils.py`

```python
from core.utils import finalize_telegram_id

def test_id_normalization():
    # Супергруппа/форум (target_type='channel')
    assert finalize_telegram_id(2882674903, target_type='channel') == -1002882674903

    # Личный чат (target_type='user') — остаётся положительным
    assert finalize_telegram_id(598765432, target_type='user') == 598765432

    # Личный чат с минусом (ошибка ввода) — становится положительным
    assert finalize_telegram_id(-598765432, target_type='user') == 598765432

    # Обычная группа (target_type='chat')
    assert finalize_telegram_id(456789, target_type='chat') == -456789

    # ID уже правильный — не дублировать префикс
    assert finalize_telegram_id(-1002882674903, target_type='channel') == -1002882674903

    # Обычная группа уже с минусом
    assert finalize_telegram_id(-456789, target_type='chat') == -456789
```

---

### 3. MergerService — `tests/test_core/test_merger.py`

```python
from core.merger import MergerService

def _msg(id_, user_id, date_str, text="hello"):
    return {"message_id": id_, "user_id": user_id, "date": date_str, "text": text}

def test_merge_consecutive_same_author():
    """Два сообщения одного автора с разницей ≤60 сек → склеить"""
    msgs = [
        _msg(1, 42, "2025-01-01T10:00:00", "Привет"),
        _msg(2, 42, "2025-01-01T10:00:30", "мир"),
    ]
    result = MergerService().merge(msgs)
    assert len(result) == 1
    assert "Привет" in result[0]["text"]
    assert "мир" in result[0]["text"]

def test_no_merge_different_author():
    """Разные авторы — не склеивать"""
    msgs = [
        _msg(1, 42, "2025-01-01T10:00:00", "Привет"),
        _msg(2, 99, "2025-01-01T10:00:10", "ответ"),
    ]
    result = MergerService().merge(msgs)
    assert len(result) == 2

def test_no_merge_gap_over_60s():
    """Один автор, разница > 60 секунд — не склеивать"""
    msgs = [
        _msg(1, 42, "2025-01-01T10:00:00"),
        _msg(2, 42, "2025-01-01T10:02:00"),  # 120 сек
    ]
    result = MergerService().merge(msgs)
    assert len(result) == 2

def test_merge_assigns_group_id():
    """Склеенные сообщения получают одинаковый merge_group_id"""
    msgs = [
        _msg(1, 42, "2025-01-01T10:00:00"),
        _msg(2, 42, "2025-01-01T10:00:20"),
    ]
    result = MergerService().merge(msgs)
    assert result[0].get("merge_group_id") is not None

def test_merge_empty_list():
    result = MergerService().merge([])
    assert result == []

def test_merge_single_message():
    msgs = [_msg(1, 42, "2025-01-01T10:00:00")]
    result = MergerService().merge(msgs)
    assert len(result) == 1
```

---

### 4. DOCX / XML Magic — `tests/test_features/test_export.py`

```python
from docx import Document
from features.export.xml_magic import add_bookmark, add_internal_hyperlink, write_text_with_links

def test_add_bookmark():
    doc = Document()
    p = doc.add_paragraph("Test")
    add_bookmark(p, "test_bookmark")
    xml = p._p.xml
    assert "test_bookmark" in xml
    assert "w:bookmarkStart" in xml
    assert "w:bookmarkEnd" in xml

def test_add_internal_hyperlink():
    doc = Document()
    p = doc.add_paragraph()
    add_internal_hyperlink(p, 123, "Link to msg 123")
    xml = p._p.xml
    assert "msg_123" in xml
    assert "w:hyperlink" in xml

def test_write_text_with_links():
    doc = Document()
    p = doc.add_paragraph()
    write_text_with_links(p, "Check this https://example.com site")
    xml = p._p.xml
    assert "https://example.com" in xml
    assert "w:hyperlink" in xml

def test_write_text_no_links():
    """Обычный текст без ссылок — не падает"""
    doc = Document()
    p = doc.add_paragraph()
    write_text_with_links(p, "Просто текст без ссылок")
    # Не должно бросать исключений

# --- DocxGenerator ---

from features.export.generator import DocxGenerator
from features.export.ui import ExportParams

def test_generate_docx_empty_db(tmp_path):
    from core.database import DBManager
    db_path = str(tmp_path / "test.db")
    db = DBManager(db_path)
    params = ExportParams(
        chat_id=-100123, output_dir=str(tmp_path),
        export_formats=["docx"]
    )
    gen = DocxGenerator(db_path=db_path, params=params)
    files = gen.generate()
    assert files == []  # нет данных → нет файлов

def test_generate_docx_creates_file(tmp_path):
    from core.database import DBManager
    db_path = str(tmp_path / "test.db")
    db = DBManager(db_path)
    db.insert_messages_batch([
        {"chat_id": -100123, "message_id": 1, "date": "2025-02-12T10:00:00",
         "text": "Hello world", "user_id": 1, "username": "user1"}
    ])
    params = ExportParams(
        chat_id=-100123, output_dir=str(tmp_path),
        split_mode="none", export_formats=["docx"]
    )
    gen = DocxGenerator(db_path=db_path, params=params)
    files = gen.generate()
    assert len(files) == 1
    assert files[0].endswith(".docx")

def test_docx_missing_media_no_crash(tmp_path):
    """Медиафайл не существует → текст-заглушка, не падает"""
    from core.database import DBManager
    db_path = str(tmp_path / "test.db")
    db = DBManager(db_path)
    db.insert_messages_batch([
        {"chat_id": -100123, "message_id": 1, "date": "2025-02-12T10:00:00",
         "media_path": "/nonexistent/file.jpg", "file_type": "photo",
         "user_id": 1, "username": "user1"}
    ])
    params = ExportParams(
        chat_id=-100123, output_dir=str(tmp_path), export_formats=["docx"]
    )
    gen = DocxGenerator(db_path=db_path, params=params)
    files = gen.generate()  # не должно бросать исключение
    assert len(files) == 1
```

---

### 5. Parser (с моками) — `tests/test_features/test_parser.py`

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from features.parser.api import ParserService, CollectParams
from core.database import DBManager

@pytest.mark.asyncio
async def test_collect_data_empty_chat(tmp_path):
    """Пустой чат — не падает, возвращает CollectResult с 0 сообщений"""
    db_path = str(tmp_path / "test.db")
    db = DBManager(db_path)

    async def empty_iter(*args, **kwargs):
        return
        yield  # пустой async generator

    mock_client = MagicMock()
    mock_entity = MagicMock()
    mock_entity.title = "Test Chat"
    mock_client.get_entity = AsyncMock(return_value=mock_entity)
    mock_client.iter_messages = empty_iter

    params = CollectParams(chat_id=-100123, output_dir=str(tmp_path))
    service = ParserService(client=mock_client, db=db, params=params)
    result = await service.collect_data()

    assert result.total_messages == 0

@pytest.mark.asyncio
async def test_collect_data_normalizes_id(tmp_path):
    """Ненормализованный ID → get_entity вызван с правильным ID"""
    db_path = str(tmp_path / "test.db")
    db = DBManager(db_path)

    async def empty_iter(*args, **kwargs):
        return
        yield

    mock_client = MagicMock()
    mock_entity = MagicMock()
    mock_entity.title = "Test"
    mock_client.get_entity = AsyncMock(return_value=mock_entity)
    mock_client.iter_messages = empty_iter

    params = CollectParams(chat_id=2882674903, output_dir=str(tmp_path))
    service = ParserService(client=mock_client, db=db, params=params)
    await service.collect_data()

    mock_client.get_entity.assert_called_with(-1002882674903)
```

---

## 🟡 СРЕДНИЙ ПРИОРИТЕТ

- `ChatsService.get_topics()` — с моками Telethon (forum / non-forum / error fallback)
- `ChatsService.get_linked_discussion_group()` — возврат `linked_chat_id`
- `DocxGenerator._generate_by_posts()` — один DOCX на пост + комментарии
- `DocxGenerator._generate_by_day()` — разделение по дням

## 🟢 НИЗКИЙ ПРИОРИТЕТ

- UI-виджеты (QWidget тесты сложны, низкий ROI)
- Вспомогательные функции форматирования дат

---

## 📊 Целевое покрытие

| Модуль | Цель | Приоритет |
|--------|------|-----------|
| `core/database.py` | 85% | 🔴 Обязательно |
| `core/utils.py` | 90% | 🔴 Обязательно |
| `core/merger.py` | 80% | 🔴 Обязательно |
| `features/export/xml_magic.py` | 75% | 🔴 Обязательно |
| `features/export/generator.py` | 60% | 🟡 |
| `features/parser/api.py` | 50% | 🟡 (с моками) |
| `features/chats/api.py` | 40% | 🟢 |
| UI-модули | — | ⚪ Пропустить |

**Суммарная цель:** 70% покрытие критического кода (исключая UI).

---

## 🛠️ Запуск тестов

```bash
# Установка:
pip install pytest pytest-asyncio pytest-mock pytest-cov pytest-timeout

# Все тесты:
pytest tests/ -v

# С покрытием:
pytest --cov=rozitta_parser --cov-report=html tests/

# Только быстрые (без slow-маркера):
pytest -m "not slow" tests/

# Конкретный файл:
pytest tests/test_core/test_database.py -v

# Только после тестов — EXE-сборка (требует подтверждения пользователя):
# pyinstaller --onefile --windowed --name RozittaParser --add-data "assets;assets" main.py
```

---

**Документ обновлён:** 2026-03-14
**Изменения:** исправлены пути модулей (backend.py → feature-based), добавлены тесты MergerService и STTWorker-кандидатов, добавлен раздел "Когда переходить к тестам", уточнён порядок P3-фазы.
**Автор:** Claude (Anthropic)
