# 🐸 Rozitta Parser

English | [Русский](#-rozitta-parser-v40)

> Back up and explore your Telegram chats — locally, privately, offline.
**Rozitta Parser** is a desktop GUI app that exports messages, media, 
and voice notes from any Telegram chat you're a member of — 
groups, channels, forums with topics, and private conversations.

### ✨ Features

- 📁 **Full backup** — messages from groups, channels, forums with topics
- 🧠 **AI-Ready export** — Markdown with auto-chunking (300k words) 
  for NotebookLM and other AI tools
- 📝 **DOCX** — readable documents, split by day / month / post
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
pip install -r requirements.txt
python main.py
```

Requires Python 3.10+. Works on Windows, Linux, macOS.

> ⚠️ For personal use only — chats you are a member of.
> Never share your `.session` file with anyone.

---



# 🐸 Rozitta Parser (v4.0)

[English](#-rozitta-parser) | Русский

> Названа в честь жабочки Розитты из детской книжки «Лоскутик и Облако».  
> Маленькая, местами нескладная, но очень старается.

---

## 🤖 Проект создан в формате Vibecoding

Я не программист. Но мне очень нужны были именно такие функции программы и я не могла остановиться, пока не заработает.
Спасибо, что нашёлся добрый человек, который помог мне с Сlaude Сode!
Телеграм сейчас работает нестабильно, не все функции протестированы. 
Выкладываю как есть — с открытым кодом и просьбой о помощи.

---

## 🔍 Ищу соавтора

Если вы опытный разработчик и вам интересен живой проект с душой —  
буду рада помощи с:

- Оптимизацией работы с Telegram API (медленная загрузка чатов и тредов)
- Архитектурой asyncio + PySide6
- Аудитом безопасности сессий Telethon
- `database is locked` при конкурентном доступе

👉 **[Открытые Issues](https://github.com/Nynchezyabka/RozittaParser/issues)** — 
там задокументированы конкретные проблемы.

Pull Requests и критика приветствуются.

---

## ✨ Что умеет

- 📁 **Полный бэкап** — сообщения из личных чатов, групп, каналов, 
  форумов с топиками
- 🧠 **AI-Ready Export** — Markdown + автоматический чанкинг по 300 000 слов 
  для обхода лимитов NotebookLM
- 📝 **DOCX** — читаемые документы для печати или быстрого просмотра
- 🎙️ **Speech-to-Text** — расшифровка голосовых и кружочков через Whisper
- 🖼️ **Медиаархив** — фото, видео, файлы с сохранением структуры папок
- 🔒 **Локально** — сессии и данные только на вашем компьютере, 
  никуда не отправляются

---

## 🚀 Use Case: Telegram → NotebookLM

В Telegram-чатах зарыта огромная экспертиза.  
Rozitta Parser превращает тысячи сообщений в структурированную базу знаний:

1. Экспортируйте чат в Markdown с опцией «Адаптировать для ИИ»
2. Загрузите части `history_part_1.md`, `_part_2.md`... в NotebookLM
3. Задавайте вопросы: «Топ проблем за 2024?», «Какие вопросы задавались чаще всего?»

---

## 🛠 Установка
```
# Создать виртуальное окружение
python -m venv .venv

# Активировать (Windows)
.venv\Scripts\activate

# Активировать (Linux/macOS)
source .venv/bin/activate

# Установить зависимости
pip install -r requirements.txt

# Запустить
python main.py
```

---

## ⚠️ Безопасность

При первом запуске потребуется API ID и API Hash — получить на 
[my.telegram.org](https://my.telegram.org).

**Никогда не передавайте файлы `.session` и `config.json` третьим лицам** — 
они содержат полный доступ к вашему аккаунту.

---

## 📬 Контакты

Нашли баг или хотите помочь — создавайте 
[Issue](https://github.com/Nynchezyabka/RozittaParser/issues) 
или Pull Request.

Разработано с ❤️ для тех, кто ценит свои данные.

## ⚠️ Важно: Для чего этот инструмент

Rozitta Parser создана для личного использования — 
чтобы сохранить и изучить данные из чатов, 
в которых вы сами состоите.

Не используйте для сбора данных без ведома участников, 
массового скрейпинга или любых целей, 
нарушающих правила Telegram и законодательство.
