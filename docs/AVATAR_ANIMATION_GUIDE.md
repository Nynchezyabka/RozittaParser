# 🎭 AVATAR_ANIMATION_GUIDE.md — Динамические реакции аватара Rozitta

> **Версия:** 1.0 (отдельная рекомендация, не входит в основную кодовую базу)
> **Статус:** Подготовка к будущей реализации. GIF-файлов пока нет.
> **Принцип:** Всё реализуется самостоятельно — без привлечения программиста.

---

## 📁 1. Структура папки `assets/`

Складывайте GIF-файлы сюда по мере готовности:

```
rozitta_parser/
└── assets/
    ├── rozitta_idle.png          ✅ Уже есть — аватар в спокойном состоянии
    │
    ├── rozitta_idle.gif          🔜 Лёгкая idle-анимация (моргание / дыхание)
    ├── rozitta_thinking.gif      🔜 Ожидание / загрузка (чесание головы?)
    ├── rozitta_working.gif       🔜 Парсинг идёт (активная работа)
    ├── rozitta_listening.gif     🔜 STT: распознавание голоса
    ├── rozitta_exporting.gif     🔜 Экспорт файла
    ├── rozitta_success.gif       🔜 Успешное завершение (радость)
    ├── rozitta_error.gif         🔜 Ошибка (огорчение)
    ├── rozitta_hello.gif         🔜 Первый запуск / авторизация пройдена
    └── rozitta_bye.gif           🔜 Закрытие приложения
```

---

## 🗺️ 2. Таблица реакций — что когда показывать

| Триггер | Файл | Когда происходит |
|---------|------|-----------------|
| Запуск приложения / ожидание | `rozitta_idle.png` или `rozitta_idle.gif` | Постоянно в фоне |
| Клик "Авторизация" / ожидание ответа Telegram | `rozitta_thinking.gif` | `AuthWorker` запущен |
| Авторизация успешна | `rozitta_hello.gif` | Сигнал `auth_complete` |
| Загрузка списка чатов | `rozitta_thinking.gif` | `ChatsWorker` запущен |
| Нажата кнопка "▶ НАЧАТЬ ПАРСИНГ" | `rozitta_working.gif` | `ParseWorker` запущен |
| Парсинг завершён, идёт STT | `rozitta_listening.gif` | `STTWorker` запущен |
| STT завершён, идёт экспорт | `rozitta_exporting.gif` | `ExportWorker` запущен |
| Экспорт завершён успешно | `rozitta_success.gif` | Сигнал `export_complete` |
| Любая ошибка (parse / stt / export) | `rozitta_error.gif` | Сигнал `error(str)` |
| Закрытие окна | `rozitta_bye.gif` | `closeEvent` MainWindow |

---

## 🔧 3. Как реализовать — пошаговая инструкция

> Всё делается правкой **одного файла**: `ui/main_window.py`
> Никаких новых зависимостей не нужно. PySide6 поддерживает GIF через `QMovie`.

### Шаг 1 — Заменить `QLabel` + `QPixmap` на `QMovie`-совместимый виджет

Найдите в `main_window.py` место создания аватара в `CharSection` (правая панель):

```python
# БЫЛО (статичный PNG — текущее состояние):
self.avatar_label = QLabel()
self.avatar_label.setFixedSize(80, 80)
pixmap = QPixmap("assets/rozitta_idle.png").scaled(80, 80, Qt.KeepAspectRatioByExpanding)
self.avatar_label.setPixmap(pixmap)
```

```python
# СТАНЕТ (с поддержкой GIF):
from PySide6.QtGui import QMovie  # добавить в импорты вверху файла

self.avatar_label = QLabel()
self.avatar_label.setFixedSize(80, 80)
self.avatar_label.setAlignment(Qt.AlignCenter)
self._current_movie: QMovie | None = None  # хранит текущую анимацию
self._set_avatar("assets/rozitta_idle.png")  # вызов нового метода
```

### Шаг 2 — Добавить метод `_set_avatar()`

Добавьте этот метод в класс `MainWindow` (или в отдельный виджет `RightPanel`):

```python
def _set_avatar(self, path: str) -> None:
    """
    Устанавливает аватар из PNG или GIF.
    Если файл не найден — показывает rozitta_idle.png (fallback).
    """
    import os

    # Fallback на idle если файл не найден
    if not os.path.exists(path):
        path = "assets/rozitta_idle.png"

    # Остановить предыдущую анимацию
    if self._current_movie is not None:
        self._current_movie.stop()
        self._current_movie = None

    if path.endswith(".gif"):
        movie = QMovie(path)
        movie.setScaledSize(self.avatar_label.size())
        self.avatar_label.setMovie(movie)
        movie.start()
        self._current_movie = movie
    else:
        # PNG / статичное изображение
        pixmap = QPixmap(path).scaled(
            80, 80,
            Qt.KeepAspectRatioByExpanding,
            Qt.SmoothTransformation
        )
        self.avatar_label.setPixmap(pixmap)
```

### Шаг 3 — Подключить вызовы к существующим сигналам

Найдите в `main_window.py` места где запускаются воркеры.
В каждом из них добавьте **одну строку** `self._set_avatar(...)`:

```python
# При старте AuthWorker:
def _start_auth(self):
    self._set_avatar("assets/rozitta_thinking.gif")  # ← добавить
    worker = AuthWorker(...)
    worker.auth_complete.connect(self._on_auth_complete, Qt.UniqueConnection)
    ...

# При успешной авторизации:
def _on_auth_complete(self, user):
    self._set_avatar("assets/rozitta_hello.gif")  # ← добавить
    ...

# При старте ParseWorker:
def _start_parse(self):
    self._set_avatar("assets/rozitta_working.gif")  # ← добавить
    worker = ParseWorker(...)
    ...

# При старте STTWorker:
def _run_stt(self, result):
    self._set_avatar("assets/rozitta_listening.gif")  # ← добавить
    worker = STTWorker(...)
    ...

# При старте ExportWorker:
def _run_export(self, result):
    self._set_avatar("assets/rozitta_exporting.gif")  # ← добавить
    worker = ExportWorker(...)
    ...

# При успешном завершении экспорта:
def _on_export_complete(self, paths: list):
    self._set_avatar("assets/rozitta_success.gif")  # ← добавить
    # После 3 секунд — вернуть idle:
    QTimer.singleShot(3000, lambda: self._set_avatar("assets/rozitta_idle.gif"))
    ...

# При любой ошибке (общий слот):
def _on_worker_error(self, msg: str):
    self._set_avatar("assets/rozitta_error.gif")  # ← добавить
    # После 4 секунд — вернуть idle:
    QTimer.singleShot(4000, lambda: self._set_avatar("assets/rozitta_idle.png"))
    ...

# При закрытии окна:
def closeEvent(self, event):
    self._set_avatar("assets/rozitta_bye.gif")  # ← добавить
    super().closeEvent(event)
```

---

## 📋 4. Список GIF для художника / нейросети

Передайте этот список дизайнеру или используйте нейросеть для генерации:

| Файл | Размер | Описание сцены |
|------|--------|----------------|
| `rozitta_idle.gif` | 80×80px, ~2–3 сек loop | Лёгкое моргание или медленное дыхание. Нейтральное выражение. |
| `rozitta_thinking.gif` | 80×80px, ~1.5 сек loop | Взгляд вверх, пальцы у подбородка или вращение глаз. |
| `rozitta_working.gif` | 80×80px, ~0.8 сек loop | Быстрые движения, руки в работе, энергичная поза. |
| `rozitta_listening.gif` | 80×80px, ~1.2 сек loop | Рука у уха, прищуренный внимательный взгляд. |
| `rozitta_exporting.gif` | 80×80px, ~1 сек loop | Папка/документ вылетает из рук. |
| `rozitta_success.gif` | 80×80px, ~2 сек, без loop | Радость, поднятый кулак, улыбка. Проигрывается один раз. |
| `rozitta_error.gif` | 80×80px, ~2 сек, без loop | Расстроенное лицо, поникшая поза. Один раз. |
| `rozitta_hello.gif` | 80×80px, ~2 сек, без loop | Машет рукой, приветствует, улыбается. Один раз. |
| `rozitta_bye.gif` | 80×80px, ~2 сек, без loop | Машет рукой на прощание. Один раз. |

**Технические требования к GIF:**
- Размер холста: **80×80px** (или кратно — 160×160 для Retina, масштабируется кодом)
- Фон: **прозрачный** (alpha channel)
- Количество кадров: 8–20 (баланс плавности и размера файла)
- Макс. размер файла: **200 КБ** на анимацию
- Петли (`loop`): бесконечно для состояний-процессов, `0` повторений для одноразовых реакций

---

## 🚀 5. Порядок внедрения (поэтапно)

1. **Сейчас:** `rozitta_idle.png` уже работает. Приложение функционально.
2. **Когда появится первый GIF** (например `rozitta_working.gif`):
   - Положить в `assets/`
   - Добавить `_set_avatar()` + `_current_movie` (Шаг 1–2 выше)
   - Добавить вызов только для `_start_parse()` (Шаг 3 частично)
3. **По мере поступления GIF** — просто добавлять строки `_set_avatar()` в нужные места.
4. Каждое добавление — **±3 строки кода**, никакой архитектурной переделки.

---

## ⚠️ Что НЕ менять

- Не трогать `features/*/api.py` — они Qt-free
- Не хранить `QMovie` в воркерах — только в UI-потоке (MainWindow)
- Не делать `QMovie` глобальным — всегда через `self._current_movie`
- При закрытии приложения вызвать `self._current_movie.stop()` в `closeEvent`

---

**Документ создан:** 2026-03-14
**Версия:** 1.0
**Автор:** Claude (Anthropic)
