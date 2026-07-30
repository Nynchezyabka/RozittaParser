# 🐸 Rozitta Parser

[![Telegram](https://img.shields.io/badge/Telegram-Вступить_в_группу-2CA5E0?style=for-the-badge&logo=telegram)](https://t.me/rozittaparser)
[![Releases](https://img.shields.io/github/v/release/Nynchezyabka/RozittaParser?style=for-the-badge&color=f59f1e)](https://github.com/Nynchezyabka/RozittaParser/releases)

> Сохраняйте и изучайте свои Telegram-чаты — локально, приватно, офлайн.  
> А для расшифровки аудио и видео в текст используйте **Rozitta Transcriber** — [репозиторий](https://github.com/Nynchezyabka/RozittaTranscriber).

**Rozitta Parser** — десктопное приложение, которое скачивает ваши Telegram-чаты
(группы, каналы с комментариями, форумы, личные диалоги) в локальную базу
и собирает из них читаемые документы — или готовый корпус для нейросети.

🗺️ [Интерактивная карта проекта](https://nynchezyabka.github.io/RozittaParser/map.html) · 📖 [DeepWiki](https://deepwiki.com/Nynchezyabka/RozittaParser) · [🇬🇧 English below](#-rozitta-parser-english)

![Главное окно](https://github.com/user-attachments/assets/6f46f659-6d82-4dc3-829f-c0fb71549783)

---

## 🚀 Быстрый старт (2 минуты, без установки)

1. Скачайте **готовую сборку** из [Releases](https://github.com/Nynchezyabka/RozittaParser/releases) и распакуйте папку.
2. Запустите `RozittaParser.exe`.
3. Войдите в Telegram (см. [авторизацию](#-авторизация)).
4. Выберите чат → нажмите пресет **«⚡ Полный архив»** → «Начать».

Программа покажет окно **«Проверьте перед стартом»** — вы всегда видите,
что именно будет скачано, до запуска.

---

## ✨ Что умеет

- 📁 **Полный бэкап** — сообщения, фото, видео, файлы, голосовые из групп,
  каналов, форумов с топиками и личных диалогов
- 💬 **Комментарии под постами** — обсуждения каналов скачиваются вместе
  с постами и попадают в документ (в т.ч. отдельными файлами «пост + его обсуждение»)
- 🎙️ **Речь в текст** — расшифровка голосовых и кружочков локальным Whisper:
  без облака, без API-ключей, тексты попадают прямо в документ.  
  Для расшифровки видео и длинных аудио используйте [Rozitta Transcriber](https://github.com/Nynchezyabka/RozittaTranscriber).
- ⚡ **Пресеты одним кликом** — «Полный архив», «Только текст»
  и «🤖 Для нейросети» выставляют все настройки сами
- 🧠 **Готовый корпус для ИИ** — Markdown с разбивкой на чанки (по умолчанию
  300k слов) для NotebookLM, AnythingLLM, open-notebook и других RAG-инструментов
- 👥 **Фильтр по участникам** — выберите нескольких сразу: «только выбранные»
  или «кроме выбранных». В режиме исключения сообщения остаются в документе
  заглушкой «🚫 Сообщение скрыто» — переписка не рассыпается, видно, что на
  этом месте что-то было, и ответы не повисают в пустоте
- 🧵 **Ветки диалогов** — «только сообщения» или «сообщения + ответы»
  (контекст с деревом в HTML и отступами в DOCX/MD)
- 📝 **Четыре формата** — DOCX, Markdown, HTML, JSON; разбивка единым файлом,
  по дням, месяцам или постам
- 🔒 **Всё локально** — сессия, база SQLite и файлы не покидают ваш компьютер

---

## 💡 Зачем это нужно (живые сценарии)

**Учебный курс или группа.** Поток закончится — а архив с разборами
останется у вас: выпуски, комментарии, расшифрованные голосовые. Пресет
«🤖 Для нейросети» собирает из него корпус, которому можно задавать вопросы
через NotebookLM или локальный RAG: *«разбирался ли похожий случай и в каком
выпуске?»*

**Семейные чаты и память.** Годы переписки, голосовых и фото — в читаемом
документе, который не зависит ни от телефона, ни от серверов.

**Работа с клиентами.** Вся история договорённостей по проекту — в одном
файле с поиском: *«что мы согласовали по террасе в марте?»*

---

## 🔑 Авторизация

**Классический вход:** api_id + api_hash + номер телефона + код из Telegram.

<details>
<summary>Где взять api_id и api_hash (1 минута)</summary>

1. Зайдите на [my.telegram.org](https://my.telegram.org) и войдите под своим аккаунтом
2. **API development tools** → создайте приложение (название любое)
3. Скопируйте **api_id** и **api_hash**

Ключи идентифицируют *приложение*, а не аккаунт: подойдут ключи от любого
вашего аккаунта или другого проекта.
</details>

**Вход через tdata (без ключей):** укажите путь к папке Telegram Desktop
(например, `%APPDATA%\Telegram Desktop\tdata`), предварительно закрыв сам
Telegram Desktop. ⚠️ При включённом прокси импорт tdata может не сработать —
временно отключите прокси или используйте классический вход.

---

## 🛡️ Rozitta не банит аккаунты

- Запросы к Telegram — **не чаще 1 в секунду** (лимит Telegram — 30/сек, мы далеко от него)
- Автоматические паузы при FloodWait (встроено в Telethon)
- Приложение только **читает** данные: не рассылает, не спамит, не создаёт ботов
- Поддержка прокси (SOCKS5 / MTProto) для сложных сетей

---

## 🛠 Установка из исходников (для разработчиков)

```bash
git clone https://github.com/Nynchezyabka/RozittaParser.git
cd RozittaParser
python -m venv .venv
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # Linux/macOS
pip install -r requirements.txt
python main.py
```

Требуется Python 3.10–3.13 (3.14 — см. [issue #35](https://github.com/Nynchezyabka/RozittaParser/issues/35)).

**macOS:** после распаковки сборки выполните `xattr -cr RozittaParser-macOS-Intel-x64.app`
или разрешите запуск в настройках безопасности.

---

## 🔧 Частые вопросы

<details>
<summary><b>Можно без api-ключей?</b></summary>
Да — вход через tdata (см. «Авторизация»).
</details>

<details>
<summary><b>Что будет, если передам ключи другу?</b></summary>
Он войдёт под своим номером через ваше «приложение». За нарушения блокируется
его аккаунт, а не ваши ключи. Но передавать ключи посторонним не стоит.
</details>

<details>
<summary><b>Меня блокировали в другой программе — можно запускать Rozitta?</b></summary>
Да. Блокировка API обычно временная (3–7 дней) и не связана с Rozitta —
она не вызывает повторного бана благодаря щадящим лимитам.
</details>

<details>
<summary><b>Куда сохраняются данные?</b></summary>
В папку <code>output/&lt;название чата&gt;/</code> рядом с программой: база SQLite,
медиа по папкам и готовые документы. Всё портативно — можно перенести на флешке.
</details>

---

## 🐸 Семейство Rozitta

**Rozitta** — это семейство локальных инструментов для работы с текстами и знаниями. Каждый инструмент решает свою задачу, а вместе они превращают разрозненные данные (Telegram-чаты, аудио, видео) в структурированный корпус для поиска, анализа и работы с ИИ. Всё работает локально — данные остаются у вас.

| Инструмент | Статус | Назначение |
|------------|--------|------------|
| ✅ [**Rozitta Parser**](https://github.com/Nynchezyabka/RozittaParser) | готов | Парсинг Telegram-чатов, чанкинг, подготовка RAG-корпуса |
| ✅ [**Rozitta Transcriber**](https://github.com/Nynchezyabka/RozittaTrancriber) | готов | Аудио/видео → Markdown с таймкодами и диаризацией |
| 🔜 **Rozitta Библиотекарь** | в планах | Локальный поиск и вопросы по архиву |

**Поток данных:**


```
Видео/аудио ──▶ Rozitta Transcriber ──▶ .md ──▶ Rozitta Parser ──▶ RAG-корпус
                                                              │
                                                              ▼
                                                      Rozitta Библиотекарь (🔜)
```

---

## 📋 Планы

- 🖼️ **Распознавание изображений** (VLM/Florence-2) — описания картинок
  в документе и поиск по содержимому фото; доставка отдельным скачиваемым
  компонентом
- 📚 **«Розитта-Библиотекарь»** — локальный семантический поиск и вопросы
  по скачанному архиву
- 🧪 Тестирование на macOS и Linux
- 🌍 Английская версия интерфейса
- 🧰 Обслуживание базы из приложения (исправления без SQL)
- 🤖 Telegram-бот для удалённого управления архивированием

---

## ☕ Поддержать проект / Support

[![CloudTips](https://img.shields.io/badge/CloudTips-QR--код-blue?style=for-the-badge&logo=visa&logoColor=white)](https://pay.cloudtips.ru/p/c77c3d90)
[![Boosty](https://img.shields.io/badge/Boosty-Поддержать-orange?style=for-the-badge&logo=boosty&logoColor=white)](https://boosty.to/nynchezyabka/donate)

---

# 🐸 Rozitta Parser (English)

> Back up and explore your Telegram chats — locally, privately, offline.

**Rozitta Parser** is a desktop GUI app that downloads your Telegram chats
(groups, channels **with comments**, forums, private conversations) into
a local database and builds readable documents — or a ready-to-use corpus
for AI tools. For transcribing audio/video into text, check out
**[Rozitta Transcriber](https://github.com/Nynchezyabka/RozittaTranscriber)**.

### ✨ Features

- 📁 **Full backup** — messages, media and voice notes from any chat you're in
- 💬 **Channel comments** — post discussions are downloaded and exported,
  including one-file-per-post mode
- 🎙️ **Speech-to-Text** — local Whisper transcription of voice messages
  and "circles"; no cloud, no API key. For longer media, use Rozitta Transcriber.
- ⚡ **One-click presets** — "Full archive", "Text only", "For AI"
- 🧠 **AI-ready export** — chunked Markdown (300k words) for NotebookLM,
  AnythingLLM, open-notebook and other RAG tools
- 👥 **Per-participant export** — messages only, or full reply threads
  rendered as trees
- 📝 **Four formats** — DOCX, Markdown, HTML, JSON
- 🔒 **100% local** — your session and data never leave your computer

### 🚀 Quick start

Grab the portable build from
[Releases](https://github.com/Nynchezyabka/RozittaParser/releases), unpack,
run `RozittaParser.exe`, sign in, pick a chat, hit the **"Full archive"**
preset. A confirmation screen shows exactly what will be downloaded before
anything starts.

Source install: Python 3.10–3.13, `pip install -r requirements.txt`,
`python main.py`.

> ⚠️ For personal use only — chats you are a member of.
> Never share your `.session` file.
