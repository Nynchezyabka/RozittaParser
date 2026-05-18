# TEST_COVERAGE.md — Rozitta Parser: отчёт по покрытию тестами

**Дата:** 2026-05-17
**Всего тестов:** 786
**Время прогона:** ~8s
**Общее покрытие строк:** 72%

---

## Сводка по спринтам

| Спринт | Фокус | Тестов | Статус |
|--------|-------|--------|--------|
| S1–S5 | Core + features базовые | 450 | ✅ |
| S6 | STT: audio_converter, whisper_manager, worker | 66 | ✅ |
| S7 | Export: participants, xml_magic | 41 | ✅ |
| S8 | Config edge cases + retry advanced | 62 | ✅ |
| S9 | UI: styles, widgets (properties) | 46 | ✅ |
| S10 | finish_takeout async | 10 | ✅ |
| S11 | TelegramApiMock + chats_mocks | 23 | ✅ |
| S12 | UI виджеты (test_ui/test_widgets/) | 61 | ✅ |
| S13 | UI экраны (AuthScreen, ChatsScreen, SettingsPanel) | 47 | ✅ |
| S14 | UI сценарии (AuthFlow, ChatSelection, ParseToExport) | 28 | ✅ |
| **Итого** | | **786** | |

---

## Покрытие по слоям

| Слой | Тестов | Файлов |
|------|--------|--------|
| `test_core/` | 276 | 11 |
| `test_features/` | 248 | 16 |
| `test_e2e/` | 34 | 3 |
| `test_ui/` | 136 | 9 |

---

## Покрытие по модулям

### Хорошо покрыто (>=80%)

| Модуль | Покрытие |
|--------|----------|
| `core/merger.py` | 98% |
| `config.py` | 96% |
| `core/stt/worker.py` | 95% |
| `finish_takeout.py` | 97% |
| `core/stt/whisper_manager.py` | 83% |
| `core/ui_shared/styles.py` | 82% |

### Среднее покрытие (50–79%)

| Модуль | Покрытие | Основные пробелы |
|--------|----------|------------------|
| `core/utils.py` | 78% | format_size, safe_filename |
| `features/chats/api.py` | 78% | media download, batch edge cases |
| `features/export/generator.py` | 77% | split export, media embed |
| `core/database.py` | 59% | export queries, reactions |
| `core/ui_shared/widgets.py` | 58% | paint events |
| `features/auth/api.py` | 57% | login flow, QR |
| `features/parser/api.py` | 56% | parsing logic, progress |
| `ui/main_window.py` | 35% | GUI wiring |

### Не покрыто (GUI / точки входа)

| Модуль | Причина |
|--------|---------|
| `features/auth/ui.py` | GUI |
| `features/chats/ui.py` | GUI |
| `features/parser/ui.py` | GUI |
| `core/ui_shared/calendar.py` | GUI |
| `main.py` | Точка входа |

---

## Покрытие баг-фиксов

| Issue | Баг | Покрытие |
|-------|-----|----------|
| #67 | Фильтрация по участнику | ❌ OPEN |
| #56 | Фильтр по датам | ✅ test_parser_mocks |
| #55 | Большие видео timeout | ✅ TestDownloadMediaTimeout |
| #41 | Парсинг HTML | ✅ test_export_html (17 тестов) |
| #27 | Список участников | ✅ test_participants (18 тестов) |
| #23 | MD + period_label | ✅ test_export_md (17 тестов) |
| #17 | Адаптивность окна | ✅ test_auth_screen |
| #11 | EXE + opentele | ✅ TestDetectTdataPath |
| #3 | Database locked | ✅ test_database + test_exceptions |

---

## Верификация

```bash
pytest tests/ -v --tb=short          # 786 passed
pytest tests/ --cov=. --cov-report=term-missing --tb=no -q
```

## Changelog

| Версия | Дата | Изменения |
|--------|------|-----------|
| 1.0 | 2026-05-06 | Начальный отчёт: 641 тест, 58% покрытия |
| 2.0 | 2026-05-17 | +145 тестов: UI виджеты/экраны/сценарии, TelegramApiMock, баг-фиксы #55/#11. 786 тестов, 72% покрытия |
