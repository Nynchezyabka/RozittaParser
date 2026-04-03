# 🐸 Rozitta Parser 
## 🗺️ [Интерактивная карта проекта (с заделом на две будущих версии интерфейса)](https://nynchezyabka.github.io/RozittaParser/map.html)
[English](#rozitta-parser) | [🇷🇺 Русский](#rozitta-parser-v15)

> Back up and explore your Telegram chats — locally, privately, offline.
**Rozitta Parser** is a desktop GUI app that exports messages, media, 
and voice notes from any Telegram chat you're a member of — 
groups, channels, forums with topics, and private conversations.

![Screenshot_17](https://github.com/user-attachments/assets/09fd78d7-c6ee-4f31-affc-140aea1e3c8d)

### ✨ Features

- 📁 **Full backup** — messages from groups, channels, forums with topics
- 🧠 **AI-Ready export** — Markdown with adjustable chunk size (default 300k words) 
  for NotebookLM and other AI tools
- 📝 **DOCX** — readable documents, split by day / month / post
- 🌐 **HTML** — clean web‑ready export with message structure
- 🎙️ **Speech-to-Text** — transcribe voice messages and video notes 
  via local Whisper (no cloud, no API key)
- 🖼️ **Media archive** — photos, videos, files with folder structure
- 🔒 **100% local** — sessions and data never leave your computer

### 🚀 Use case: Telegram → NotebookLM

Thousands of messages in your chats = a knowledge base waiting to happen.
Export any chat to Markdown, upload to NotebookLM, ask questions.

### 🛠 Install
```bash
git clone https://github.com/Nynchezyabka/RozittaParser.git
cd RozittaParser
python -m venv .venv
.venv\Scripts\activate  # Windows
source .venv/bin/activate  # Linux/macOS
pip install -r requirements.txt
python main.py
```
Requires Python 3.10–3.13. Python 3.14 requires Microsoft C++ Build Tools (see issue #35).

> ⚠️ For personal use only — chats you are a member of.
> Never share your `.session` file with anyone.

---



# 🐸 Rozitta Parser v1.5
[🇬🇧 English](#rozitta-parser) | [Русский](#rozitta-parser-v15)

> Сохраняйте и изучайте свои Telegram‑чаты — локально, приватно, офлайн.

**Rozitta Parser** — десктопное приложение для архивирования сообщений, медиа и голосовых заметок из любых чатов, где вы участвуете: группы, каналы, форумы с топиками, личные диалоги.

---

## ✨ Возможности

- 📁 **Полный бэкап** — сообщения, фото, видео, файлы
- 🧠 **AI-Ready** — Markdown с настраиваемым размером чанка (по умолчанию 300k слов) для NotebookLM
- 📝 **DOCX** — читаемые документы с разбивкой по дням/месяцам/постам
- 🌐 **HTML** — чистая веб‑страница (в разработке, поля сообщений дорабатываются)
- 🎙️ **Speech-to-Text** — расшифровка голосовых и кружочков через локальный Whisper (без облака)
- 🔒 **Всё локально** — сессии и данные не покидают ваш компьютер

---

## 🚀 Быстрый старт (3 минуты)

### 1. Получите ключи API (если впервые)
1. Зайдите на [my.telegram.org](https://my.telegram.org)
2. Войдите под любым своим аккаунтом
3. Перейдите в **API development tools**
4. Создайте приложение (название любое)
5. Скопируйте **api_id** и **api_hash**

**Важно:** ключи **не привязаны к номеру телефона**. Вы можете использовать ключи от одного аккаунта, чтобы войти в другой.

### 2. Установите программу
```bash
git clone https://github.com/Nynchezyabka/RozittaParser.git
cd RozittaParser
python -m venv .venv
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # Linux/macOS
pip install -r requirements.txt
python main.py
```

**Требуется Python 3.10–3.13.** Python 3.14 требует установки Microsoft C++ Build Tools (см. [issue #35](https://github.com/Nynchezyabka/RozittaParser/issues/35)).

### 3. Авторизуйтесь
- **Классический вход:** введите api_id, api_hash и номер телефона, затем код из Telegram.
- **Вход через tdata (Telegram Desktop):** 1. Закройте открытый Telegram Desktop во избежание конфликтов сессий. 2. Укажите путь к папке `tdata` (например, `%APPDATA%\Telegram Desktop\tdata`).  
  ⚠️ *На данный момент импорт через tdata может не работать, если используется прокси. Рекомендуется временно отключать прокси при импорте tdata или использовать классический вход.*

---

## 🛡️ Rozitta **НЕ банит** (почему)

- ✅ Все запросы к Telegram делаются **не чаще 1 раза в секунду** (Telegram рекомендует 30 запросов/сек — мы далеко от лимита)
- ✅ Автоматические паузы при FloodWait (Telethon встроен)
- ✅ Поддержка прокси (SOCKS5 / MTProto) для сложных сетей
- ✅ Приложение только **читает** данные, не отправляет спам, не создаёт ботов


---

## 📱 Для начинающих (и тех, кто не хочет разбираться)

Если вы не программист — скачайте **готовую сборку** (портабельную версию) из [релизов](https://github.com/Nynchezyabka/RozittaParser/releases).  
Распакуйте папку, запустите `RozittaParser.exe` — и всё работает.

(В будущем появится **лайт‑режим** с одной кнопкой «Архивировать чат» — пока в разработке.)

---

## 🔧 Частые вопросы

### Где взять api_id и api_hash?
На [my.telegram.org](https://my.telegram.org) → API development tools → создать приложение.

### А можно без ключей?
Да, если у вас установлен Telegram Desktop. Укажите в программе путь к папке `tdata` (например, `C:\Users\Имя\AppData\Roaming\Telegram Desktop\tdata`).  
⚠️ *Примечание:* импорт через tdata может не работать, если включён прокси. Временно отключите прокси в настройках или используйте классический вход.

### У меня уже есть ключи от другого проекта. Подойдут?
Да. Ключи идентифицируют **приложение**, а не аккаунт. Используйте их с любым номером.

### Что будет, если я передам свои ключи другу?
Друг сможет войти в Telegram под своим номером, используя ваше приложение. Если он нарушит правила, блокировку получит **его аккаунт**, а не ваши ключи. Тем не менее, передавать ключи посторонним не рекомендуется.

### Меня заблокировали при использовании другой программы. Можно ли запустить Rozitta?
Да, блокировка аккаунта обычно временная (3–7 дней) и касается только доступа к API. Сам аккаунт остаётся рабочим. Подождите, пока ограничение снимется, и используйте Rozitta — она не вызовет повторного бана.

---

## 👩‍💻 Для разработчиков

Проект создан в формате **vibecoding** — я не программист, но мне очень нужны были именно такие функции.  
Спасибо, что нашёлся добрый человек, который помог с рефакторингом в  Claude Code! И ещё один, который помогает теперь тут на github.  
Телеграм сейчас работает нестабильно, не все функции протестированы.  
Выкладываю как есть — с открытым кодом и просьбой о помощи.

Если вы опытный разработчик и вам интересен живой проект с душой —  
буду рада помощи с любыми задачами из [Issues](https://github.com/Nynchezyabka/RozittaParser/issues).  
Pull Requests и критика приветствуются.

---

## ⚠️ Важно

Rozitta Parser предназначена для **личного использования** — сохранения чатов, в которых вы участвуете.  
Не используйте для сбора данных без ведома участников, массового скрейпинга или любых целей, нарушающих правила Telegram и законодательство.

---

## 📋 Планы на следующие версии

- Доработка списка активных участников с возможностью экспорта в отдельный файл
- Экспорт постов с комментариями отдельными файлами
- Тестирование на macOS и Linux
- Английская версия интерфейса
- Лайт-версия для начинающих пользователей
- Обновление интерактивной карты проекта

---

## ☕ Поддержать проект / Support

[![CloudTips](https://img.shields.io/badge/CloudTips-QR--код-blue?style=for-the-badge&logo=visa&logoColor=white)](https://pay.cloudtips.ru/p/c77c3d90)
[![Boosty](https://img.shields.io/badge/Boosty-Поддержать-orange?style=for-the-badge&logo=boosty&logoColor=white)](https://boosty.to/nynchezyabka/donate)
