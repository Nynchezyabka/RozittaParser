# 🐸 Rozitta Parser
## 🗺️ [Интерактивная карта проекта](https://nynchezyabka.github.io/RozittaParser/map.html)
English | [Русский](#-rozitta-parser-v40)

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



# 🐸 Rozitta Parser (v1.5)

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

🆕 Что нового в версии 4.0
- ✅ Устранены проблемы со скоростью — загрузка чатов и тредов теперь работает быстро
- ✅ HTML экспорт — чистая веб-страница с сообщениями (требует доработки отображения полей)
- ✅ Настраиваемый AI-сплит — размер чанка для Markdown/JSON можно менять в настройках
- ✅ Корректные имена файлов — экспорт топиков форума больше не перезаписывает файлы
- ✅ STT починен — голосовые и кружочки распознаются локально
- ⚠️ В процессе — сборка exe с opentele (библиотека пока не подгружается)
- ⚠️ Требует тестирования на macOS — были сообщения о проблемах, ждём обратную связь

---

## 🔍 Ищу соавтора

Если вы опытный разработчик и вам интересен живой проект с душой —  
буду рада помощи с:

- **Сборкой exe** — библиотека opentele не подхватывается PyInstaller

- **Доработкой HTML экспорта** — корректное отображение всех полей сообщений

- **Аудитом безопасности сессий Telethon**

- **Тестированием на разных платформах** (macOS, Linux)

- **Лайт-версией** — упрощённый интерфейс для неопытных пользователей


👉 **[Открытые Issues](https://github.com/Nynchezyabka/RozittaParser/issues)** — 
там задокументированы конкретные проблемы.

Pull Requests и критика приветствуются.

---

## ✨ Что умеет

- 📁 **Полный бэкап** — сообщения из личных чатов, групп, каналов, 
  форумов с топиками
- 🧠 **AI-Ready Export** — Markdown + автоматический чанкинг для обхода лимитов NotebookLM
- 📝 **DOCX** — читаемые документы для печати или быстрого просмотра
- 🌐 HTML — веб-версия чата (в разработке)
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
>**Важно:** Python 3.10–3.13 рекомендуется. Для Python 3.14 нужны Microsoft C++ Build Tools.
---

## ⚠️ Безопасность

В программе есть два способа входа:

1. Через TData (Рекомендуется): Просто укажите путь к папке tdata вашего установленного Telegram Desktop. Вы войдете мгновенно.

2. Классический вход: Если нет Telegram Desktop, потребуется получить API ID и API Hash на my.telegram.org и войти по номеру телефона.
   
**Никогда не передавайте файлы `.session` и `config.json` третьим лицам** — 
они содержат полный доступ к вашему аккаунту.

---

## 📋 Планы на следующие версии

- Доработка HTML экспорта (все поля сообщений)

- Исправление opentele в сборке PyInstaller

- Тестирование на macOS и Linux

- Английская версия интерфейса

- Лайт-версия для начинающих пользователей

- Отображение списка активных участников

- Интерактивная карта проекта (обновление зависимостей)

## 📬 Контакты

Нашли баг или хотите помочь — создавайте 
[Issue](https://github.com/Nynchezyabka/RozittaParser/issues) 
или Pull Request.


## ⚠️ Важно: Для чего этот инструмент

Rozitta Parser создана для личного использования — 
чтобы сохранить и изучить данные из чатов, 
в которых вы сами состоите.


Не используйте для сбора данных без ведома участников, 
массового скрейпинга или любых целей, 
нарушающих правила Telegram и законодательство.

### ☕ Поддержать проект / Support

[![CloudTips](https://img.shields.io/badge/CloudTips-QR--код-blue?style=for-the-badge&logo=visa&logoColor=white)](https://pay.cloudtips.ru/p/c77c3d90)
[![Boosty](https://img.shields.io/badge/Boosty-Поддержать-orange?style=for-the-badge&logo=boosty&logoColor=white)](https://boosty.to/nynchezyabka/donate)
