# TESTS_PLAN.md — Rozitta Parser

Дата: 2026-03-14
Версия: 3.5

---

## Регрессионные тесты (уже написаны)

| Файл | Покрытие |
|------|---------|
| `tests/test_core/test_database.py` | DBManager: WAL, batch upsert, transcriptions |
| `tests/test_core/test_merger.py` | MergerService: edge cases |
| `tests/test_core/test_utils.py` | finalize_telegram_id, DownloadTracker |
| `tests/test_features/test_export.py` | DocxGenerator, xml_magic |
| `tests/test_features/test_parser.py` | collect_data с моками |

---

## BUG-5+6 — TopicsWorker Signal(object)

**Файл:** `features/chats/ui.py`
**Проблема:** `Signal(dict)` → RuntimeError в PySide6 при emit.
**Fix:** `Signal(object)`.

### Тест-кейсы

```python
# tests/test_features/test_chats.py

def test_topics_worker_signal_type():
    """topics_loaded должен быть Signal(object), а не Signal(dict)."""
    from features.chats.ui import TopicsWorker
    sig = TopicsWorker.topics_loaded
    # PySide6: проверить через метаобъект что тип аргумента — object
    assert "object" in str(sig)

def test_inject_topics_populated(qtbot, monkeypatch):
    """ChatsScreen.inject_topics() заполняет комбобокс топиков."""
    from features.chats.ui import ChatsScreen
    from unittest.mock import MagicMock
    cfg = MagicMock()
    screen = ChatsScreen(cfg)
    qtbot.addWidget(screen)
    topics = {1001: "Общее", 1002: "Флудилка"}
    screen.inject_topics(topics)
    # комбобокс должен содержать 2 топика (+ возможный пустой элемент)
    assert screen._topic_combo.count() >= 2
```

---

## BUG-4 — user_ids фильтрация

**Файл:** `features/parser/api.py`
**Проблема:** `user_id: int` → один пользователь. Fix: `user_ids: List[int]`.

### Тест-кейсы

```python
# tests/test_features/test_parser.py (расширение)

@pytest.mark.asyncio
async def test_collect_filters_by_user_ids(mock_client):
    """collect_data пропускает сообщения не из списка user_ids."""
    from features.parser.api import ParserService, CollectParams

    # Создаём 3 сообщения от разных отправителей
    msg_a = make_message(sender_id=111, text="from A")
    msg_b = make_message(sender_id=222, text="from B")
    msg_c = make_message(sender_id=333, text="from C")
    mock_client.iter_messages.return_value = async_gen([msg_a, msg_b, msg_c])

    svc = ParserService(mock_client)
    params = CollectParams(chat_id=1, user_ids=[111, 333], output_dir="/tmp")
    result = await svc.collect_data(params)

    saved_ids = [m["user_id"] for m in result.messages]
    assert 111 in saved_ids
    assert 333 in saved_ids
    assert 222 not in saved_ids

@pytest.mark.asyncio
async def test_collect_no_filter_when_user_ids_none(mock_client):
    """collect_data без фильтра — все сообщения сохраняются."""
    from features.parser.api import ParserService, CollectParams

    msg_a = make_message(sender_id=111, text="from A")
    msg_b = make_message(sender_id=222, text="from B")
    mock_client.iter_messages.return_value = async_gen([msg_a, msg_b])

    svc = ParserService(mock_client)
    params = CollectParams(chat_id=1, user_ids=None, output_dir="/tmp")
    result = await svc.collect_data(params)

    assert len(result.messages) == 2
```

---

## BUG-2 — include_comments в ExportParams

**Файл:** `ui/main_window.py._run_export()`
**Проблема:** `include_comments` не передавался → комментарии не включались в DOCX.

### Тест-кейсы

```python
# tests/test_features/test_export.py (расширение)

def test_export_params_include_comments():
    """ExportParams.include_comments=True передаётся в DocxGenerator."""
    from features.export.ui import ExportParams
    from features.export.generator import DocxGenerator
    from unittest.mock import patch, MagicMock

    params = ExportParams(
        chat_id=1,
        chat_title="Test",
        split_mode="post",
        include_comments=True,
        output_dir="/tmp",
        db_path="/tmp/test.db",
    )
    assert params.include_comments is True

def test_docx_generator_includes_comments(tmp_path):
    """DocxGenerator._generate_by_posts() вызывает запрос комментариев при include_comments=True."""
    from features.export.generator import DocxGenerator
    from unittest.mock import patch, MagicMock

    gen = DocxGenerator.__new__(DocxGenerator)
    gen._db = MagicMock()
    gen._db.get_posts.return_value = [{"message_id": 42, "text": "Post"}]
    gen._db.get_comments_for_post.return_value = [{"text": "Comment", "username": "user"}]

    with patch.object(gen, "_write_message_block"):
        gen._generate_by_posts(include_comments=True, output_path=str(tmp_path / "out.docx"))

    gen._db.get_comments_for_post.assert_called_once_with(42)
```

---

## Выход (LogoutWorker)

**Файл:** `ui/main_window.py`

### Тест-кейсы (ручное тестирование)

1. Авторизоваться → кнопка "⏻ Выйти" появилась в сайдбаре.
2. Нажать "⏻ Выйти" → в логе появляются сообщения о выходе.
3. После выхода: кнопка скрывается, UI сбрасывается на шаг 0 (AuthScreen).
4. Session-файл (`*.session`) удалён с диска.
5. Повторный запуск приложения — снова запрашивает авторизацию.

---

## Запуск тестов

```bash
pytest tests/ -v
pytest tests/test_core/ -v
pytest tests/test_features/ -v --asyncio-mode=auto
```

---

**Автор:** Claude (Anthropic)
**Создан:** 2026-03-14
