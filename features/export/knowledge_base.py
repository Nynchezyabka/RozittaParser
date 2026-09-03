"""
features/export/knowledge_base.py — Пресет «🧠 База знаний для ИИ» (#96).

Генерирует обвязку базы знаний над существующей Markdown-выгрузкой:
  - 00_Оглавление.md         — главная точка входа в архив
  - ИНСТРУКЦИЯ_ДЛЯ_ИИ.md      — инструкция для нейросети
  - CLAUDE.md / AGENTS.md     — та же инструкция + добавка под агента
  - archive_passport.json     — машиночитаемый паспорт архива

Архитектурные принципы (из ТЗ docs/ТЗ_база_знаний_для_ИИ.md):
  - Существующая логика экспорта НЕ меняется, файлы НЕ переименовываются.
  - Все артефакты детерминированно генерируются из SQLite-базы.
  - Идемпотентность: повторный экспорт перезаписывает артефакты обвязки
    и не дублирует YAML-шапки в существующих MD.
  - Никаких сетевых запросов и LLM-вызовов.

Точка интеграции:
  ExportWorker.run() — после блоков форматов, если params.build_kb и
  "md" в params.formats, вызывает KnowledgeBaseBuilder.build(...).

Зависимости:
  - DBManager (read-only)
  - core.version.__version__ — для archive_passport.json
  - python-frontmatter — для идемпотентной работы с YAML front-matter

Нет Qt-зависимостей. Нет Telethon. Только stdlib + DBManager + frontmatter.
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from core.database import DBManager
from core.version import __version__ as PARSER_VERSION, KB_SCHEMA_VERSION

logger = logging.getLogger(__name__)

_LogCallback = Callable[[str], None]


# ============================================================================
# Константы
# ============================================================================

# Имена артефактов обвязки (создаются в корне output_dir)
INDEX_FILENAME = "00_Оглавление.md"
INSTRUCTION_RU = "ИНСТРУКЦИЯ_ДЛЯ_ИИ.md"
INSTRUCTION_CLAUDE = "CLAUDE.md"
INSTRUCTION_AGENTS = "AGENTS.md"


# ── KB preset stage 10c (agent addenda) ──
# Аддендум собирается динамически: пример файла берётся из реальной
# выгрузки, счётчики — из chat_meta. Раньше здесь был захардкожен пример
# из чужого архива, и инструкция учила ИИ ссылаться на несуществующий файл.

_ADDENDUM_HEADERS = {
    "claude": (
        "## Рекомендации для Claude\n\n"
        "Этот архив предназначен для работы в **Claude Code**.\n\n"
        "- Файл `CLAUDE.md` — ваш контекст. Claude Code автоматически "
        "прочитает его при запуске в папке архива.\n"
    ),
    "codex": (
        "## Рекомендации для OpenAI Agents\n\n"
        "Этот архив предназначен для работы с **Codex** и другими "
        "OpenAI-агентами.\n\n"
        "- Файл `AGENTS.md` — ваш контекст. OpenAI Agents прочитают его "
        "как системный промпт при работе в папке архива.\n"
    ),
}


def _first_post_example(exported_files: List[str]) -> Optional[Tuple[str, str]]:
    """Первый реальный файл поста из выгрузки -> (имя файла, номер поста).

    Нужен, чтобы пример цитирования в инструкции ссылался на файл,
    который в этом архиве действительно есть.
    """
    for path in exported_files:
        name = Path(path).name
        m = re.search(r"_post_(\d+)", name)
        if m:
            return name, m.group(1)
    return None


def _build_agent_addendum(
    agent:          str,
    chat_meta:      dict,
    exported_files: List[str],
) -> str:
    """Собирает добавку к инструкции для конкретного агента.

    Args:
        agent: "claude" | "codex".
        chat_meta: метаданные чата (счётчики постов и комментариев).
        exported_files: пути выгруженных файлов — для примера цитирования.

    Returns:
        Текст добавки, начинающийся с пустой строки. Пустая строка,
        если агент неизвестен.
    """
    header = _ADDENDUM_HEADERS.get(agent)
    if not header:
        return ""

    example = _first_post_example(exported_files)
    if example:
        cite = (f"- **Ссылайтесь на конкретные файлы и посты**: «согласно "
                f"`{example[0]}`, пост #{example[1]}…».\n")
    else:
        cite = ("- **Ссылайтесь на конкретные файлы и посты**, указывая имя "
                "файла и номер поста.\n")

    posts = chat_meta.get("posts_count", 0)
    comments = chat_meta.get("comments_count", 0)

    parts = [
        "\n\n", header,
        "- Секция «Режимы работы» выше — ваши инструкции по ответам. "
        "Начинайте с режима «Архивариус».\n\n",
        "### Дополнительные правила\n\n",
        "- **Ответы на русском языке**, даже если вопрос задан на "
        "английском.\n",
        "- **Архив read-only**: не предлагайте правок кода и не изменяйте "
        "файлы выгрузки.\n",
        cite,
        "- Если пользователь просит что-то вне архива — переключайтесь в "
        "режим «Свободный советник» и явно помечайте: «это не из архива».\n",
        "- Не додумывайте содержание: если файл не открыт — откройте его, "
        "а не предполагайте, что там написано.\n",
    ]

    # Раздел про источники нужен только там, где есть и посты, и комментарии
    if posts and comments:
        ratio = ("\n### Посты и комментарии — РАЗНЫЕ источники\n\n"
                 "- Файлы постов и расшифровки видео — **материал автора "
                 "канала**. Комментарии — сообщения участников: пересказы "
                 "своими словами, личные истории, вопросы.\n"
                 f"- В этом архиве {comments} комментариев против {posts} "
                 "постов. Поиск по словам почти всегда приводит в "
                 "комментарии — но это **не значит, что ответ там**.\n"
                 "- Сначала ищите ответ в тексте поста и расшифровке видео; "
                 "комментарии — дополнение, а не источник методики.\n"
                 "- **Всегда помечайте, чьи это слова**: «автор пишет…» "
                 "против «участница описывает свой опыт…». Не выдавайте "
                 "мнение участника за позицию автора.\n")
        parts.append(ratio)

    return "".join(parts)

PASSPORT_FILENAME = "archive_passport.json"

# N-KB: имена артефактов самой базы знаний — исключаются из дискового
# скана в _merge_with_existing_files(), это не выгруженный контент.
_KB_ARTIFACT_FILENAMES = frozenset({
    INDEX_FILENAME, INSTRUCTION_RU, INSTRUCTION_CLAUDE, INSTRUCTION_AGENTS,
    PASSPORT_FILENAME,
})

# Маппинг file_type → "[тип медиа]" для оглавления и эвристики «О чём пост».
# Источник значений file_type: features/parser/api.py::_detect_media_type().
MEDIA_TYPE_LABEL: Dict[str, str] = {
    "photo":         "[фото]",
    "video":         "[видео]",
    "videomessage":  "[кружочек]",
    "voice":         "[голосовое]",
    "file":          "[файл]",
}

# Метка для постов без текста и без известного медиа
_MEDIA_FALLBACK = "[медиа]"

# Приветственные префиксы, пропускаемые эвристикой «О чём пост» (правило 2).
# Из ТЗ: «не начинается с Уважаем/Дорог/Привет/Здравств/🌟».
_GREETING_PREFIXES = ("Уважаем", "Дорог", "Привет", "Здравств", "🌟")

# Минимальная длина строки для правила 2 (не-приветственная, > 15 символов).
_MIN_TOPIC_LINE_LEN = 15

# Максимальная длина «О чём» в оглавлении.
_MAX_TOPIC_LEN = 120

# Сколько первых непустых строк просматривать в поисках «Выпуск №N».
_HEAD_LINES_TO_SCAN = 6

# Regex для правила 1: «Выпуск №?N» или «Выпуск N» (case-insensitive).
_RE_ISSUE_LINE = re.compile(r"^Выпуск\s*№?\s*\d+", re.IGNORECASE)

# Порог паузы в днях для хронокарты (ТЗ: > 14 дней).
PAUSE_THRESHOLD_DAYS = 14

# Коэффициент IQR для определения «всплеска» (метод Тьюки, стандарт = 1.5).
_IQR_BURST_COEFF = 1.5


# ============================================================================
# Эвристика «О чём пост» — этап 2
# ============================================================================

def markdown_to_plain(text: str) -> str:
    """
    Снимает markdown-разметку для эвристики «О чём пост».

    Порядок преобразований (важен):
      1. Изображения `![alt](url)` → `alt` (до ссылок, иначе `!` останется).
      2. Ссылки `[text](url)` → `text`.
      3. Заголовки `#`/`##`/... в начале строки — убрать маркер.
      4. Bold/italic/code маркеры `*`, `_`, `` ` `` — убрать.
      5. Одиночные `[`, `]` — убрать (защита от остатков).

    Args:
        text: Исходная строка с markdown-разметкой.

    Returns:
        Строка без markdown-разметки, без лишних пробелов по краям.
        Пустая строка для None/пустого ввода.
    """
    if not text:
        return ""
    # 1. Изображения: ![alt](url) → alt
    out = re.sub(r"!\[([^\]]*)\]\([^\)]*\)", r"\1", text)
    # 2. Ссылки: [text](url) → text
    out = re.sub(r"\[([^\]]*)\]\([^\)]*\)", r"\1", out)
    # 3. Заголовки: # / ## / ... в начале строки
    out = re.sub(r"^#{1,6}\s*", "", out, flags=re.MULTILINE)
    # 4. Bold/italic/code маркеры
    out = re.sub(r"[*_`]+", "", out)
    # 5. Остаточные квадратные скобки
    out = re.sub(r"[\[\]]", "", out)
    return out.strip()


# ── N-17: частотный срез архива ───────────────────────────────────────────────
#
# Служебные слова: местоимения, предлоги, союзы, частицы, связки, усилители,
# наречия времени и места. Мусор в любом архиве независимо от темы.
#
# Содержательные существительные и глаголы («время», «дело», «человек»,
# «делать», «знать») сюда СОЗНАТЕЛЬНО не включены: для одного архива это
# шум, для другого — суть. Если на живом архиве мусорное слово попадёт в
# топ, допишите его сюда — это правка в одну строку.
_STOPWORDS: frozenset = frozenset({
    # местоимения
    "который", "которая", "которое", "которые", "этот", "этого", "этому",
    "этим", "этими", "этом", "того", "тому", "теми", "такой", "такая",
    "такое", "такие", "такого", "такому", "таким", "такими", "таком",
    "себя", "собой", "каждый", "каждая", "каждое", "любой", "любая",
    "любое", "любые", "всего", "всему", "всеми", "ничего",
    # связки и вспомогательные
    "быть", "была", "было", "были", "есть", "будет", "будут", "мочь",
    "могла", "могло", "могли", "может", "могут", "должен", "должна",
    "должно", "стать", "стала", "стало", "стали",
    # предлоги и союзы
    "чтобы", "или", "тоже", "также", "если", "хотя", "потому", "поэтому",
    "через", "между", "перед", "для", "при", "про",
    # наречия времени и места
    "здесь", "тогда", "сейчас", "потом", "сначала", "опять", "снова",
    "всегда", "никогда", "часто", "иногда", "обычно", "сегодня", "вчера",
    "завтра", "когда", "куда", "откуда", "почему", "зачем",
    # частицы и усилители
    "только", "просто", "больше", "вообще", "очень", "совсем", "даже",
    "конечно", "значит", "нужно", "нельзя", "достаточно", "наверное",
})

_TERM_MIN_LEN = 6
_TERM_MAX_LEN = 18
_TERM_MAX_CONSONANTS = 4
_TERM_DEFAULT_LIMIT = 15
_TERM_MIN_FREQ = 5

_VOWELS = frozenset("аеёиоуыэюяaeiouy")
_NEUTRAL = frozenset("ьъ")
_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)


def _looks_like_word(term: str) -> bool:
    """
    Эвристика против склеек: слово обязано иметь и гласную, и согласную,
    и не содержать 5+ согласных подряд.

    Отсекает «бабушкадействительно» и «восприятияпостоянные» — артефакты
    текстов, где потерян пробел. Тот же приём, что в Библиотекаре.
    """
    chars = [c for c in term.lower() if c.isalpha()]
    if not chars:
        return False
    if not any(c in _VOWELS for c in chars):
        return False
    if not any(c not in _VOWELS and c not in _NEUTRAL for c in chars):
        return False

    run = 0
    for c in chars:
        if c in _VOWELS or c in _NEUTRAL:
            run = 0
        else:
            run += 1
            if run > _TERM_MAX_CONSONANTS:
                return False
    return True


def extract_top_terms(
    texts:    List[str],
    limit:    int = _TERM_DEFAULT_LIMIT,
    min_freq: int = _TERM_MIN_FREQ,
) -> List[Tuple[str, int]]:
    """
    N-17: самые характерные слова архива — раздел «О чём этот архив».

    Детерминированно, без модели и без сети. Словоформы не склеиваются
    («терраса» и «террасы» считаются раздельно) — ровно так же ведёт себя
    токенизатор Библиотекаря, на который этот срез равняется.

    Фильтры: длина 6–18 символов, только буквы, не стоп-слово, похоже на
    слово (см. _looks_like_word), встречается не реже min_freq раз.

    Порядок: по убыванию частоты, при равной частоте по алфавиту — чтобы
    вывод не зависел от порядка чтения из БД.

    Если под min_freq не попал никто (маленький архив), порог снимается:
    лучше показать что-то, чем пустой раздел.

    Args:
        texts:    Тексты сообщений.
        limit:    Сколько слов вернуть.
        min_freq: Минимальная частота слова во всём архиве.

    Returns:
        Список пар (слово, частота); пустой, если считать не из чего.
    """
    limit = max(1, int(limit or _TERM_DEFAULT_LIMIT))
    counter: Counter = Counter()

    for text in texts:
        if not text:
            continue
        for raw in _WORD_RE.findall(text.lower()):
            if not (_TERM_MIN_LEN <= len(raw) <= _TERM_MAX_LEN):
                continue
            if raw in _STOPWORDS:
                continue
            if not _looks_like_word(raw):
                continue
            counter[raw] += 1

    if not counter:
        return []

    def _top(threshold: int) -> List[Tuple[str, int]]:
        picked = [(w, n) for w, n in counter.items() if n >= threshold]
        picked.sort(key=lambda pair: (-pair[1], pair[0]))
        return picked[:limit]

    return _top(min_freq) or _top(1)


# --- Тема поста из расшифровки голоса --------------------------------------
#
# Расшифровка приходит одним абзацем: whisper_manager склеивает сегменты
# пробелом, переводов строк там нет вообще. Поэтому построчные правила
# extract_post_topic к ней неприменимы — режем на предложения.
#
# Проверено на девяти живых расшифровках канала: семь дают понятную тему.
# Два случая, где автор называет тему только к середине записи, никакое
# правило «взять начало» не возьмёт — это принятое ограничение, а не
# недоделка. Даже вода из первых фраз информативнее голого «[кружочек]».

# Речь почти всегда открывается приветствием. Отдельным предложением оно
# короткое и отсеется по длине; список нужен для длинных вступлений
# вроде «Привет, мои хорошие, я сегодня пришла рассказать…».
_SPEECH_OPENERS = (
    "привет", "здравств", "добрый ", "доброе ", "всем привет",
    "мои хорошие", "моя хорошая", "дорог", "уважаем", "друзья",
    "ребят", "ну что", "итак", "на связи", "спасибо всем",
)

# Короткое предложение темы не несёт: «Так.», «Готовы там?», «Вы как?».
# Порог 25, а не 30: на живых записях 30 отсекал «Бургер с тамленой
# говядиной.» — ровно ту фразу, ради которой запись и снималась.
_TRANSCRIPT_MIN_SENT_LEN = 25

# Пометка машинной расшифровки. Нужна не для красоты: распознавание врёт
# («три вооблюда», «ушелуша»), и читатель обязан видеть, что это не
# авторский текст.
_STT_MARK = "🎙"

_RE_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])\s+")


def _topic_from_transcript(transcript: Optional[str]) -> Optional[str]:
    """
    Первая содержательная фраза машинной расшифровки голоса.

    Отбрасывает короткие предложения и вступительные приветствия, берёт
    первое уцелевшее и обрезает по общему правилу колонки.

    Returns:
        Фразу без пометки, либо None — расшифровки нет или в ней не
        нашлось ни одного пригодного предложения.
    """
    if not transcript:
        return None

    flat = " ".join(transcript.split())
    for sentence in _RE_SENTENCE_SPLIT.split(flat):
        sentence = sentence.strip()
        if len(sentence) < _TRANSCRIPT_MIN_SENT_LEN:
            continue
        opening = sentence.lower().lstrip("—–-«\"' ")
        if opening.startswith(_SPEECH_OPENERS):
            continue
        return _truncate(sentence)

    return None


def extract_post_topic(
    text:       Optional[str],
    file_type:  Optional[str],
    transcript: Optional[str] = None,
) -> str:
    """
    Извлекает «О чём пост» — первую содержательную строку поста.

    Три правила (ТЗ п.1, проверены на реальном канале):
      1) Если в первых 6 непустых строках есть строка, начинающаяся с
         «Выпуск №?N» — взять её.
      2) Иначе первая строка, не являющаяся приветствием (не начинается с
         «Уважаем/Дорог/Привет/Здравств/🌟») и длиннее 15 символов.
      3) Иначе первая непустая строка как есть.

    Разметку markdown снять, обрезать до 120 символов (с «…» если длиннее).
    Если текста нет (только медиа) — тип медиа: «[видео]», «[фото]» и т.д.
    Если нет ни текста, ни медиа — возвращается «[медиа]» как фоллбэк.

    Args:
        text:      Полный текст поста (может быть None или пустым).
        file_type: Тип медиа, если пост без текста.
                   Один из: photo, video, videomessage, voice, file, None.
        transcript: Машинная расшифровка голоса, если она есть. Идёт в дело
                   только когда своего текста у поста нет: авторское слово
                   всегда главнее того, что услышала модель.

    Returns:
        Строка-описание темы поста для колонки «О чём». Никогда не пустая.
    """
    media_label = MEDIA_TYPE_LABEL.get(file_type or "", _MEDIA_FALLBACK)

    # Подменяем метку медиа фразой из расшифровки — так все три выхода
    # «текста нет» ниже отдают её без правки самих правил.
    spoken = _topic_from_transcript(transcript)
    if spoken:
        media_label = f"{_STT_MARK} {spoken}"

    # Нет текста — возвращаем метку медиа (или фоллбэк)
    if not text or not text.strip():
        return media_label

    # Разбиваем на непустые строки, сохраняя порядок
    raw_lines = [ln.strip() for ln in text.replace("\r\n", "\n").split("\n")]
    non_empty = [ln for ln in raw_lines if ln]
    if not non_empty:
        return media_label

    # Правило 1: «Выпуск №?N» в первых 6 непустых строках
    head = non_empty[:_HEAD_LINES_TO_SCAN]
    for ln in head:
        if _RE_ISSUE_LINE.match(ln):
            return _truncate(markdown_to_plain(ln))

    # Правило 2: первая не-приветственная строка длиннее 15 символов
    for ln in non_empty:
        plain = markdown_to_plain(ln)
        if not plain:
            continue
        if plain.startswith(_GREETING_PREFIXES):
            continue
        if len(plain) > _MIN_TOPIC_LINE_LEN:
            return _truncate(plain)

    # Правило 3: первая непустая строка как есть
    first_plain = markdown_to_plain(non_empty[0])
    if first_plain:
        return _truncate(first_plain)

    # Все строки оказались пустыми после снятия markdown — медиа-фоллбэк
    return media_label


def _truncate(text: str, max_len: int = _MAX_TOPIC_LEN) -> str:
    """Обрезает строку до max_len символов, добавляя «…» если длиннее."""
    if len(text) <= max_len:
        return text
    return text[:max_len] + "…"


# ============================================================================
# YAML front-matter — этап 3
# ============================================================================
#
# Пост-обработка MD-файлов после генерации MarkdownGenerator'ом.
# MarkdownGenerator НЕ меняется (правило ТЗ: «существующая логика НЕ меняется»).
#
# Логика:
#   1. Читаем MD-файл.
#   2. Если первая строка — заголовок `# {chat_title}...` — убираем его
#      (информация переезжает в YAML-поле `chat:`).
#   3. Добавляем YAML front-matter через python-frontmatter (идемпотентно:
#      если шапка уже есть, заменяем; ключи сортируются для детерминизма).
# ============================================================================

def add_yaml_frontmatter(
    path:        str | Path,
    metadata:    Dict[str, object],
    *,
    chat_title:  Optional[str] = None,
) -> bool:
    """
    Добавляет YAML front-matter в MD-файл (идемпотентно).

    Если у файла уже есть front-matter — он заменяется новым (с обновлёнными
    значениями из metadata). Ключи YAML сортируются для детерминизма
    (повторный запуск даёт идентичный файл).

    Если задан `chat_title` и первая строка файла — заголовок вида
    `# {chat_title}...` (как пишет MarkdownGenerator), заголовок убирается:
    название чата переезжает в YAML-поле `chat:`.

    Args:
        path:       Путь к MD-файлу.
        metadata:   Словарь с полями для YAML-шапки
                    (chat, post, date, author, type, comments_count, и т.д.).
        chat_title: Название чата — если задано, проверяется и убирается
                    первая строка-заголовок. None — не убирать.

    Returns:
        True если файл обработан, False если файл не существует.
    """
    import frontmatter

    p = Path(path)
    if not p.exists():
        return False

    content = p.read_text(encoding="utf-8")

    # Убираем первую строку-заголовок `# {chat_title}...`, если она есть.
    # MarkdownGenerator пишет: `# {chat_title}\n\n` (диалоги),
    # `# {chat_title} — пост #{pid} ({date})\n\n` (посты),
    # `# {chat_title} — ветки с {user}\n` (треды).
    # Безопасно убираем только если первая строка начинается с `# {chat_title}`.
    if chat_title and content.startswith(f"# {chat_title}"):
        newline_idx = content.find("\n")
        if newline_idx != -1:
            content = content[newline_idx + 1:]
            # Убираем пустые строки после заголовка
            content = content.lstrip("\n")
        else:
            content = ""

    # Если у файла уже есть front-matter, frontmatter.loads() его распарсит,
    # и мы заменим metadata на новое. Если нет — создаст пустой Post.
    try:
        post = frontmatter.loads(content) if content else frontmatter.Post("")
    except Exception:
        # Если YAML-парсинг упал — относимся к файлу как к чистому контенту
        post = frontmatter.Post(content)

    post.metadata = dict(metadata)  # полная замена, не merge

    # dumps с sort_keys=True для детерминизма (идемпотентность).
    # default_flow_style=False — блочный YAML (читаемость).
    # allow_unicode=True — не эскейпить кириллицу.
    output = frontmatter.dumps(
        post,
        sort_keys=True,
        default_flow_style=False,
        allow_unicode=True,
    )
    p.write_text(output, encoding="utf-8")
    return True


def parse_yaml_frontmatter(path: str | Path) -> Tuple[Optional[Dict], str]:
    """
    Читает MD-файл и возвращает (metadata, content).

    Если front-matter отсутствует — возвращает (None, исходный_контент).

    Args:
        path: Путь к MD-файлу.

    Returns:
        Кортеж (dict с метаданными или None, строка с контентом без шапки).
    """
    import frontmatter

    p = Path(path)
    if not p.exists():
        return None, ""

    text = p.read_text(encoding="utf-8")
    try:
        post = frontmatter.loads(text)
    except Exception:
        return None, text

    if not post.metadata:
        return None, text
    return dict(post.metadata), post.content


# ============================================================================
# Хронокарта — этап 8
# ============================================================================

def compute_iqr_bursts(monthly_counts: List[Tuple[str, int]]) -> dict:
    """
    Двухуровневая детекция всплесков по IQR (метод Тьюки).

    Args:
        monthly_counts: Список (year_month, count), отсортированный по дате.
                        year_month — строка вида "YYYY-MM".

    Returns:
        dict с ключами:
          - q1, q3, iqr:      квартили и межквартильный размах (для отладки).
          - threshold:        порог всплеска = Q3 + 1.5×IQR.
          - activity_periods: [ym] — месяцы с count > Q3 («повышенная активность»).
          - bursts:           [ym] — месяцы с count > threshold («всплеск»).
        Если в monthly_counts меньше 4 элементов — все массивы пустые
        (IQR на маленькой выборке нестабилен).
    """
    if len(monthly_counts) < 4:
        return {
            "q1": None, "q3": None, "iqr": None, "threshold": None,
            "activity_periods": [], "bursts": [],
        }

    counts = sorted(c for _, c in monthly_counts)
    n = len(counts)

    def _percentile(sorted_vals: List[int], p: float) -> float:
        """Линейная интерполяция (метод numpy default)."""
        if not sorted_vals:
            return 0.0
        if len(sorted_vals) == 1:
            return float(sorted_vals[0])
        rank = p * (n - 1)
        lo = int(rank)
        hi = min(lo + 1, n - 1)
        frac = rank - lo
        return sorted_vals[lo] + frac * (sorted_vals[hi] - sorted_vals[lo])

    q1 = _percentile(counts, 0.25)
    q3 = _percentile(counts, 0.75)
    iqr = q3 - q1
    threshold = q3 + _IQR_BURST_COEFF * iqr

    activity_periods = [
        ym for ym, c in monthly_counts if c > q3
    ]
    bursts = [
        ym for ym, c in monthly_counts if c > threshold
    ]

    return {
        "q1": round(q1, 2),
        "q3": round(q3, 2),
        "iqr": round(iqr, 2),
        "threshold": round(threshold, 2),
        "activity_periods": activity_periods,
        "bursts": bursts,
    }


def normalize_media_path(media_path: Optional[str], output_dir: Path) -> Optional[str]:
    """
    Нормализует путь медиа к относительному POSIX-формату для ссылок.

    Пример:
      media_path = 'output\\\\Chat\\\\media\\\\photos\\\\6_x.jpg'
      output_dir = Path('output/Chat')
      → 'media/photos/6_x.jpg'

    Args:
        media_path: Абсолютный или относительный путь из БД (Windows или POSIX).
        output_dir: Корень выгрузки чата.

    Returns:
        Относительный POSIX-путь или None, если media_path пустой
        или путь не находится внутри output_dir (возвращает абсолютный
        POSIX-путь как fallback).
    """
    if not media_path:
        return None

    # Нормализуем разделители (Windows → POSIX)
    normalized = media_path.replace("\\", "/")
    p = Path(normalized)

    # Пытаемся сделать путь относительно output_dir
    try:
        rel = p.relative_to(Path(str(output_dir).replace("\\", "/")))
        return rel.as_posix()
    except ValueError:
        # Путь не внутри output_dir — возвращаем как есть (нормализованный)
        return p.as_posix()


def _url_encode_path(rel_path: str) -> str:
    """Кодирует пробелы в пути как %20 для Markdown-ссылок.

    Не кодирует слеши и другие спецсимволы — только пробелы (по ТЗ).
    """
    return rel_path.replace(" ", "%20")


def _format_date(iso_str: Optional[str]) -> str:
    """Форматирует ISO-дату 'YYYY-MM-DD HH:MM:SS' → 'YYYY-MM-DD'.

    Возвращает '?' если дата пустая или невалидная.
    """
    if not iso_str:
        return "?"
    # Берём первые 10 символов 'YYYY-MM-DD'
    if len(iso_str) >= 10:
        return iso_str[:10]
    return iso_str


def _month_key(iso_str: Optional[str]) -> str:
    """
    Месяц сообщения для группировки таблицы постов: 'YYYY-MM'.

    Возвращает '?' для пустой или слишком короткой строки — такие посты
    собираются в отдельный блок, а не приписываются к соседнему месяцу.
    """
    if not iso_str or len(iso_str) < 7:
        return "?"
    return iso_str[:7]


def _tg_post_link(chat_id: Optional[int], message_id: Optional[int]) -> Optional[str]:
    """
    Приватная ссылка t.me/c/... на пост канала.

    Формат обязан совпадать с generator._tg_message_link (I15): оглавление
    и сами документы должны вести в одно и то же место. Здесь отдельная
    функция, а не импорт: тот вариант принимает строку БД целиком, а
    оглавление работает со словарями.

    Возвращает None, если данных недостаточно.
    """
    if not chat_id or not message_id:
        return None
    s = str(chat_id)
    internal = s[4:] if s.startswith("-100") else s.lstrip("-")
    return f"https://t.me/c/{internal}/{message_id}"


def _posts_table_legend(rows: List[str]) -> str:
    """
    Строка условных обозначений под заголовком таблицы постов.

    Печатается только для значков, которые в таблице действительно есть.
    Пустая строка — значит объяснять нечего.
    """
    joined = "\n".join(rows)
    parts: List[str] = []
    if _STT_MARK in joined:
        parts.append(
            f"{_STT_MARK} — фраза из машинной расшифровки голоса, "
            "а не авторский текст"
        )
    if "📝" in joined:
        parts.append("📝 — у поста есть расшифровка целиком")
    if not parts:
        return ""
    return "> " + ". ".join(parts) + "."


# ============================================================================
# Главный класс — собирает все артефакты базы знаний
# ============================================================================

class KnowledgeBaseBuilder:
    """
    Собирает артефакты базы знаний для одной выгрузки чата.

    Не зависит от Qt/Telethon — чисто stdlib + DBManager + frontmatter.
    Вызывается из ExportWorker.run() (см. features/export/ui.py).

    Usage::

        with DBManager(db_path) as db:
            builder = KnowledgeBaseBuilder(db, output_dir)
            artifacts = builder.build(
                chat_id        = p.chat_id,
                chat_title     = p.chat_title,
                period_label   = p.period_label,
                exported_files = all_files,
                log            = self._log,
            )
            all_files.extend(artifacts)

    Args:
        db:         Открытый DBManager (read-only достаточно).
        output_dir: Папка выгрузки чата (куда уже сложены MD и медиа).
    """

    def __init__(self, db: DBManager, output_dir: str | Path) -> None:
        self._db = db
        self._output_dir = Path(output_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Главный entry point
    # ------------------------------------------------------------------

    def build(
        self,
        chat_id:        int,
        chat_title:     str,
        period_label:   str,
        *,
        exported_files: List[str],
        log:            _LogCallback = lambda _: None,
    ) -> List[str]:
        """
        Генерирует все артефакты базы знаний и возвращает пути к ним.

        Args:
            chat_id:        ID чата.
            chat_title:     Название чата (для шапок артефактов).
            period_label:   Метка периода выгрузки (для имени файла/паспорта).
            exported_files: Список путей к уже созданным MD/медиа —
                            нужен для построения оглавления и паспорта.
            log:            Колбэк для логирования прогресса.

        Returns:
            Список абсолютных путей к созданным артефактам:
            [00_Оглавление.md, ИНСТРУКЦИЯ_ДЛЯ_ИИ.md, CLAUDE.md,
             AGENTS.md, archive_passport.json]
        """
        log("База знаний: старт сборки артефактов")
        chat_meta = self._get_chat_metadata(chat_id)

        # N-KB: exported_files — только файлы этого прогона. chat_meta и
        # список постов и так берутся из БД целиком (весь архив) — без
        # этого дополнения ссылки на файлы отставали бы от остального
        # оглавления и терялись на любой довыгрузке, где не пересобирается
        # вообще всё разом.
        known_files = self._merge_with_existing_files(exported_files)

        # 1. Оглавление
        index_path = self._build_index(
            chat_id, chat_title, chat_meta, known_files, log
        )

        # 2. Инструкция (3 файла)
        instruction_paths = self._build_instruction(
            chat_id, chat_title, chat_meta, known_files, log  # ── KB preset stage 10b (dynamic instruction) ──
        )

        # Список сгенерированных артефактов (без паспорта — он в конце)
        artifacts: List[str] = [index_path] + instruction_paths

        # 3. Паспорт (включает список всех артефактов, включая сам себя)
        passport_path = self._build_passport(
            chat_id, chat_title, chat_meta, known_files, artifacts, log
        )
        artifacts.append(passport_path)

        log(f"База знаний: готово, {len(artifacts)} артефактов")
        return artifacts

    def _merge_with_existing_files(self, exported_files: List[str]) -> List[str]:
        """
        Дополняет exported_files тем, что уже лежит в output_dir на диске.

        exported_files — только файлы текущего прогона. Артефакты самой
        базы знаний (оглавление/инструкция/паспорт) в список не попадают —
        это не выгруженный контент, а обвязка над ним, и мы вот-вот
        перезапишем их заново.
        """
        seen = set(exported_files)
        merged = list(exported_files)
        try:
            existing = sorted(self._output_dir.glob("*.md"))
        except OSError as exc:
            logger.warning(
                "_merge_with_existing_files: не удалось прочитать %s: %s",
                self._output_dir, exc,
            )
            return merged
        for path in existing:
            if path.name in _KB_ARTIFACT_FILENAMES:
                continue
            s = str(path)
            if s not in seen:
                seen.add(s)
                merged.append(s)
        return merged

    # ------------------------------------------------------------------
    # Внутренние методы — этапы 1, 5, 8
    # ------------------------------------------------------------------

    def enrich_md_files(
        self,
        md_files:     List[str],
        chat_id:      int,
        chat_title:   str,
        *,
        log:          _LogCallback = lambda _: None,
    ) -> int:
        """
        Этап 3+9: добавляет YAML front-matter в каждый MD-файл выгрузки.

        Вызывается из ExportWorker.run() **до** build(), чтобы оглавление
        и паспорт видели уже обогащённые файлы. Идемпотентно: повторный
        вызов перезаписывает шапку, не дублирует её.

        Метаданные для каждого MD определяются по имени файла
        (MarkdownGenerator формирует имена детерминированно):
          - ``{title}_post_{pid}...md``  → type=post_with_comments, post=pid,
            +date/author/comments_count из БД.
          - ``{title}..._part_{N}.md``   → type=chunk, part=N.
          - ``{title}_threads_..._...md``→ type=threads.
          - ``{title}..._{period}.md``   → type=chat_archive.

        Сбои на отдельных файлах НЕ роняют общий процесс — пишется warning
        в лог, обработка продолжается.

        Args:
            md_files:   Список путей к MD-файлам (абсолютных или относительно
                        output_dir).
            chat_id:    ID чата — для подгрузки метаданных постов из БД.
            chat_title: Название чата — поле ``chat:`` в YAML + критерий
                        удаления первой строки-заголовка ``# {chat_title}...``.
            log:        Колбэк логирования.

        Returns:
            Количество успешно обработанных файлов (может быть меньше
            len(md_files) при ошибках на отдельных файлах).
        """
        log(f"  YAML-обогащение {len(md_files)} MD-файлов…")

        # Один запрос к БД: карта post_id → метаданные.
        post_meta: Dict[int, dict] = {}
        try:
            for row in self._db.get_post_metadata(chat_id):
                d = dict(row)
                post_meta[d["message_id"]] = d
        except Exception as exc:
            log(f"  ⚠️ get_post_metadata для YAML не удался: {exc}")

        processed = 0
        for md_path in md_files:
            try:
                meta = self._build_md_metadata(md_path, chat_title, post_meta)
                ok = add_yaml_frontmatter(md_path, meta, chat_title=chat_title)
                if ok:
                    processed += 1
            except Exception as exc:
                log(f"  ⚠️ YAML для {Path(md_path).name}: {exc}")

        log(f"  YAML-обогащение: {processed}/{len(md_files)} готово")
        return processed

    @staticmethod
    def _build_md_metadata(
        md_path:    str,
        chat_title: str,
        post_meta:  Dict[int, dict],
    ) -> Dict[str, object]:
        """Строит YAML-метаданные для MD-файла по его имени.

        Шаблоны MarkdownGenerator (features/export/generator.py):
          - ``{title}_post_{pid}{mode_part}_{period}.md`` — пост + комменты
          - ``{title}{topic_part}{user_part}{mode_part}_{period}_part_{N}.md``
          - ``{title}{topic_part}{user_part}{mode_part}_{period}.md`` — диалог
          - ``{title}_threads_{user_label}_{period}.md`` — треды пользователя

        Возвращает словарь с минимумом полей: ``chat``, ``type`` и,
        для постов, ``post``/``date``/``author``/``comments_count``.
        """
        name = Path(md_path).name
        meta: Dict[str, object] = {"chat": chat_title}

        # 1. Пост: ищем ``_post_{N}_`` или ``_post_{N}.md`` (после N — _ или конец).
        m = re.search(r"_post_(\d+)(?:_|\.md$)", name)
        if m:
            pid = int(m.group(1))
            meta["type"] = "post_with_comments"
            meta["post"] = pid
            pm = post_meta.get(pid, {})
            if pm.get("date"):
                meta["date"] = pm["date"][:10]
            if pm.get("username"):
                meta["author"] = pm["username"]
            if pm.get("comments_count") is not None:
                meta["comments_count"] = pm["comments_count"]
            return meta

        # 2. Чанк: ``_part_{N}.md`` (без ``_post_`` — иначе сработало бы выше).
        m = re.search(r"_part_(\d+)\.md$", name)
        if m:
            meta["type"] = "chunk"
            meta["part"] = int(m.group(1))
            return meta

        # 3. Треды: ``_threads_`` в имени.
        if "_threads_" in name:
            meta["type"] = "threads"
            return meta

        # 4. Обычный файл чата/диалога.
        meta["type"] = "chat_archive"
        return meta

    def _get_chat_metadata(self, chat_id: int) -> dict:
        """Этап 1: метаданные чата из БД (делегирует в DBManager.get_chat_info)."""
        return self._db.get_chat_info(chat_id)

    def _get_top_terms(self, chat_id: int) -> List[Tuple[str, int]]:
        """N-17: частотный срез архива по текстам без комментариев."""
        return extract_top_terms(self._db.get_post_texts(chat_id))

    def _get_posts_for_index(self, chat_id: int) -> List[dict]:
        """Этап 1: список постов канала для оглавления (is_comment=0)."""
        rows = self._db.get_post_metadata(chat_id)
        return [dict(r) for r in rows]

    def _get_transcripts_map(self, chat_id: int) -> Dict[int, str]:
        """Этап 4: {message_id: text} расшифровок STT для чата.

        Внутренние STT-расшифровки уже включены в MD-контент постов через
        MarkdownGenerator._format_message(stt_text=...). Здесь мы только
        узнаём, у каких сообщений есть расшифровки, чтобы пометить посты
        в оглавлении (колонка «Файлы»: иконка 📝).
        """
        return self._db.get_transcriptions_for_chat(chat_id)

    def _collect_post_files(
        self,
        chat_id:         int,
        post:            dict,
        exported_files:  List[str],
        transcripts_map: Dict[int, str],
    ) -> str:
        """Этап 5: собирает колонку «Файлы» для поста в оглавлении."""
        post_id = post["message_id"]
        links: List[str] = []

        md_link = self._find_post_md_link(post_id, exported_files)
        if md_link:
            links.append(f"[📄]({md_link})")

        media_rows = self._db.get_media_for_post(chat_id, post_id)
        for m in media_rows:
            rel = normalize_media_path(m["media_path"], self._output_dir)
            if rel:
                icon = self._media_icon(m["file_type"])
                links.append(f"[{icon}]({_url_encode_path(rel)})")

        has_transcript = post_id in transcripts_map
        if not has_transcript:
            for m in media_rows:
                if m["message_id"] in transcripts_map:
                    has_transcript = True
                    break
        if has_transcript:
            links.append("📝")

        return " ".join(links) if links else "—"

    def _find_post_md_link(
        self, post_id: int, exported_files: List[str]
    ) -> Optional[str]:
        """Ищет MD-файл поста в exported_files по шаблону `post_{N}`."""
        marker = f"post_{post_id}_"
        for f in exported_files:
            f_norm = f.replace("\\", "/")
            if marker in f_norm:
                try:
                    rel = Path(f_norm).relative_to(
                        Path(str(self._output_dir).replace("\\", "/"))
                    )
                    return _url_encode_path(rel.as_posix())
                except ValueError:
                    return _url_encode_path(f_norm)
        return None

    @staticmethod
    def _media_icon(file_type: Optional[str]) -> str:
        """Иконка для типа медиа в оглавлении (эмодзи)."""
        return {
            "photo":         "🖼️",
            "video":         "🎬",
            "videomessage":  "🎥",
            "voice":         "🎤",
            "file":          "📎",
        }.get(file_type or "", "📎")

    def _build_index(
        self,
        chat_id:        int,
        chat_title:     str,
        chat_meta:      dict,
        exported_files: List[str],
        log:            _LogCallback,
    ) -> str:
        """Этап 5: строит 00_Оглавление.md."""
        log("  Построение оглавления…")
        parts: List[str] = []

        parts.append(f"# Оглавление архива: {chat_title}")
        parts.append("")
        parts.append("> Этот файл — главная точка входа в архив. "
                     "Начинай поиск с него.")
        parts.append("")
        parts.append(f"- **Тип чата:** {chat_meta.get('type') or 'неизвестен'}")
        parts.append(f"- **Период:** {_format_date(chat_meta.get('period_min'))} "
                     f"— {_format_date(chat_meta.get('period_max'))}")
        parts.append(f"- **Сообщений:** {chat_meta.get('messages_count', 0)}")
        if chat_meta.get("posts_count", 0) > 0:
            parts.append(f"- **Постов:** {chat_meta['posts_count']}, "
                         f"**комментариев:** {chat_meta.get('comments_count', 0)}")
        parts.append(f"- **Участников:** {chat_meta.get('participants_count', 0)}")
        parts.append(f"- **Дата генерации:** {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        parts.append("")

        # N-17: до всякой хронологии — о чём тут вообще речь.
        parts.extend(self._render_top_terms_section(chat_id, log))

        if chat_meta.get("type") == "channel" and chat_meta.get("posts_count", 0) > 0:
            parts.extend(self._render_posts_table(chat_id, chat_title, exported_files, log))
        else:
            parts.extend(self._render_months_table(chat_id, exported_files, log))

        index_path = self._output_dir / INDEX_FILENAME
        index_path.write_text("\n".join(parts) + "\n", encoding="utf-8")
        log(f"  Оглавление: {index_path.name}")
        return str(index_path)

    def _render_top_terms_section(
        self,
        chat_id: int,
        log:     _LogCallback,
    ) -> List[str]:
        """
        N-17: раздел «О чём этот архив» — частотный срез.

        Пустой архив или сплошное медиа без текста → раздел не выводится
        вовсе: пустой заголовок хуже его отсутствия.
        """
        terms = self._get_top_terms(chat_id)
        if not terms:
            log("  Частотный срез: текстов нет, раздел пропущен")
            return []

        log(f"  Частотный срез: {len(terms)} слов")
        return [
            "## О чём этот архив",
            "",
            "Самые частые слова архива — с чего начать поиск. "
            "В скобках число упоминаний.",
            "",
            ", ".join(f"**{word}** ({count})" for word, count in terms),
            "",
        ]

    def _render_posts_table(
        self,
        chat_id:        int,
        chat_title:     str,
        exported_files: List[str],
        log:            _LogCallback,
    ) -> List[str]:
        """
        N-17 (B): таблица постов канала, разрезанная по месяцам.

        Колонка «Автор» убрана: по Variant A-2 канал сам себе отправитель,
        и на 596 постов там одно значение — колонка занимала место, не
        неся информации.

        Шапка повторяется в каждом месячном блоке: markdown не соберёт в
        одну таблицу куски, разделённые заголовком.

        Нумерация сквозная через все месяцы — номер поста используют как
        адрес в разговоре, он не должен зависеть от того, где проходит
        граница месяца.

        Колонка «стрелка» — прямая ссылка на пост в Telegram. Для канала
        работает всегда, независимо от режима выгрузки, в отличие от
        колонки «Файлы», где ссылка на MD есть только при дроблении
        «по постам».
        """
        posts = self._get_posts_for_index(chat_id)
        transcripts_map = self._get_transcripts_map(chat_id)
        log(f"  Постов для индексации: {len(posts)}")

        header = "| № | Дата | О чём | Файлы | ↗ |"
        ruler = "|:---:|:---:|:---|:---|:---:|"

        body: List[str] = []
        current_month: Optional[str] = None

        for idx, post in enumerate(posts, start=1):
            month = _month_key(post.get("date"))
            if month != current_month:
                current_month = month
                # Пустая строка перед заголовком обязательна: без неё часть
                # markdown-читалок склеивает заголовок с предыдущей таблицей.
                body.extend(["", f"### {month}", "", header, ruler])

            topic = extract_post_topic(
                post.get("text"),
                post.get("file_type"),
                transcript=transcripts_map.get(post.get("message_id")),
            )
            date = _format_date(post.get("date"))
            files = self._collect_post_files(
                chat_id, post, exported_files, transcripts_map
            )
            link = _tg_post_link(chat_id, post.get("message_id"))
            link_cell = f"[↗]({link})" if link else "—"
            topic_safe = topic.replace("|", "\\|")
            body.append(
                f"| {idx} | {date} | {topic_safe} | {files} | {link_cell} |"
            )

        lines: List[str] = ["## Посты канала"]
        legend = _posts_table_legend(body)
        if legend:
            lines.extend(["", legend])
        lines.extend(body)
        lines.append("")
        return lines

    def _render_months_table(
        self,
        chat_id:        int,
        exported_files: List[str],
        log:            _LogCallback,
    ) -> List[str]:
        """Таблица по месяцам для диалогов + хронокарта."""
        chmap = self._db.get_chronological_map(chat_id)
        log(f"  Месяцев в хронокарте: {len(chmap['messages_by_month'])}")

        lines: List[str] = [
            "## Сообщения по месяцам",
            "",
            "| Месяц | Сообщений | Файлы |",
            "|:---:|:---:|:---|",
        ]

        for month in chmap["messages_by_month"]:
            ym = month["ym"]
            count = month["count"]
            md_links = self._find_chunk_links_for_month(ym, exported_files)
            files = " ".join(f"[📄]({l})" for l in md_links) if md_links else "—"
            lines.append(f"| {ym} | {count} | {files} |")

        lines.append("")
        lines.extend(self._render_chronomap_section(chmap))
        return lines

    def _find_chunk_links_for_month(
        self, ym: str, exported_files: List[str]
    ) -> List[str]:
        """Ищет MD-чанки, относящиеся к месяцу ym, в exported_files."""
        links: List[str] = []
        for f in exported_files:
            f_norm = f.replace("\\", "/")
            if ym in f_norm and f_norm.endswith(".md"):
                try:
                    rel = Path(f_norm).relative_to(
                        Path(str(self._output_dir).replace("\\", "/"))
                    )
                    links.append(_url_encode_path(rel.as_posix()))
                except ValueError:
                    links.append(_url_encode_path(f_norm))
        return links

    def _render_chronomap_section(self, chmap: dict) -> List[str]:
        """Раздел хронокарты для диалогов (этап 8)."""
        lines: List[str] = [
            "## Хронологическая карта",
            "",
            f"Всего сообщений: **{chmap['messages_count']}**",
            "",
        ]

        monthly = [(m["ym"], m["count"]) for m in chmap["messages_by_month"]]
        bursts_info = compute_iqr_bursts(monthly)

        if bursts_info["activity_periods"]:
            lines.append("**Повышенная активность** (выше Q3): "
                         + ", ".join(bursts_info["activity_periods"]))
            lines.append("")
        if bursts_info["bursts"]:
            lines.append("**Всплески** (выше Q3 + 1.5×IQR): "
                         + ", ".join(bursts_info["bursts"]))
            lines.append("")

        if chmap["pauses"]:
            lines.extend([
                "**Паузы > 14 дней:**",
                "",
                "| С | По | Дней |",
                "|:---|:---|:---:|",
            ])
            for p in chmap["pauses"]:
                lines.append(
                    f"| {_format_date(p['from_date'])} | "
                    f"{_format_date(p['to_date'])} | {p['days']} |"
                )
            lines.append("")

        if chmap["user_shares"]:
            lines.extend([
                "**Доли участников:**",
                "",
                "| Участник | Сообщений | % |",
                "|:---|:---:|:---:|",
            ])
            for u in chmap["user_shares"][:20]:
                name = u["username"] or f"id:{u['user_id']}"
                lines.append(f"| {name} | {u['count']} | {u['pct']}% |")
            lines.append("")

        return lines

    def _build_instruction(
        self,
        chat_id:        int,
        chat_title:     str,
        chat_meta:      dict,
        exported_files: List[str],
        log:            _LogCallback,
    ) -> List[str]:
        """Этап 6: строит ИНСТРУКЦИЯ_ДЛЯ_ИИ.md + CLAUDE.md + AGENTS.md.

        ИНСТРУКЦИЯ_ДЛЯ_ИИ.md — полная базовая инструкция.
        CLAUDE.md — базовая + добавка для Claude Code.
        AGENTS.md — базовая + добавка для OpenAI Agents.
        """
        log("  Построение инструкции для ИИ…")
        text = self._render_instruction_text(chat_title, chat_meta, exported_files)  # ── KB preset stage 10b (dynamic instruction) ──
        # _build_agent_addendum() уже собирает добавку динамически (stage 10c).
        # _CLAUDE_ADDENDUM/_AGENTS_ADDENDUM этим же переходом убрали, а здесь
        # осталась ссылка на них — NameError при каждом build_kb=True, тихо
        # проглатываемый except в ExportWorker.run().
        _AGENT_ADDENDA: Dict[str, str] = {
            INSTRUCTION_CLAUDE: _build_agent_addendum("claude", chat_meta, exported_files),
            INSTRUCTION_AGENTS: _build_agent_addendum("codex", chat_meta, exported_files),
        }
        paths: List[str] = []
        for filename in (INSTRUCTION_RU, INSTRUCTION_CLAUDE, INSTRUCTION_AGENTS):
            p = self._output_dir / filename
            p.write_text(text + _AGENT_ADDENDA.get(filename, ""), encoding="utf-8")
            paths.append(str(p))
        log(f"  Инструкция: {len(paths)} файла")
        return paths

    def _render_instruction_text(  # ── KB preset stage 10b (dynamic instruction) ──
        self,
        chat_title:     str,
        chat_meta:      dict,
        exported_files: List[str],
    ) -> str:
        """Шаблон инструкции для ИИ (этап 6).

        Секция «Структура архива» строится динамически на основе
        анализа exported_files — имена файлов определяют их роль.
        """
        chat_type = chat_meta.get("type") or "неизвестен"
        period = (f"{_format_date(chat_meta.get('period_min'))} — "
                  f"{_format_date(chat_meta.get('period_max'))}")
        msgs = chat_meta.get("messages_count", 0)
        posts = chat_meta.get("posts_count", 0)
        participants = chat_meta.get("participants_count", 0)

        lines: List[str] = [
            f"# Архив: {chat_title}",
            "",
            "Это архив Telegram-чата, выгруженный через Rozitta Parser "
            "с пресетом «🧠 База знаний для ИИ».",
            "",
            "## Общие сведения",
            "",
            f"- **Название:** {chat_title}",
            f"- **Тип чата:** {chat_type}",
            f"- **Период:** {period}",
            f"- **Сообщений:** {msgs}",
        ]
        if posts > 0:
            lines.append(f"- **Постов канала:** {posts}")
        lines.extend([
            f"- **Участников:** {participants}",
            "",
        ])

        # ── Динамическая секция «Структура архива» ──────────────────
        lines.extend(self._render_archive_structure(
            chat_title, chat_meta, exported_files))

        lines.extend([
            "## Режимы работы",
            "",
            "По умолчанию — **Архивариус**. Переключение по явной формулировке.",
            "",
            "### Архивариус (по умолчанию)",
            "- Отвечай **только** по материалам архива.",
            "- Каждый тезис подтверждай ссылкой на файл и номер поста/дату.",
            "- Если информации нет — прямо скажи «в архиве этого нет».",
            "- Не смешивай текст автора поста с мнениями комментаторов.",
            "",
            "### Консультант по материалам",
            "Формулировка: «посоветуй на основе…»",
            "- Рекомендации только из справочных материалов с указанием источника.",
            "- Факты о ситуации — из архива и/или со слов пользователя,",
            "  всегда с пометкой, что откуда.",
            "- Связка теории с ситуацией явно помечается как применение,",
            "  а не как факт.",
            "",
            "### Свободный советник",
            "Формулировка: «дай общий совет…»",
            "- Общие знания модели разрешены.",
            "- Факты об архиве — по-прежнему только из архива.",
            "- Общие рекомендации явно помечаются как не основанные на материалах.",
            "",
            "## Типы задач",
            "(работают в любом режиме, наследуя его правила достоверности)",
            "",
            "- **Вопрос-ответ** — прямой ответ на вопрос по архиву.",
            "- **Подборка** — извлечь всё по критерию.",
            "- **Аналитика** — вычисления над архивом (динамика, доли, паузы).",
            "  Приводить числа, не впечатления.",
            "- **Составление** — дайджест, отчёт, чек-лист. Каждый факт в",
            "  итоговом тексте прослеживается до источника.",
            "",
            "## Деликатные темы",
            "",
            "Если переписка касается личных отношений, дневников, психологических",
            "материалов:",
            "- Разделяй уровни «факт → контекст → гипотеза».",
            "- Помечай гипотезы как гипотезы.",
            "- Не выноси суждений о мотивах и состояниях реальных людей.",
            "- Передавай материал автора, не выступая терапевтом.",
            "",
            "## Как искать",
            "",
            "1. Сначала открой `00_Оглавление.md`, найди подходящие посты/месяцы.",
            "2. Затем grep по MD-файлам. Учитывай морфологию русского: ищи по",
            "   основе слова («презрени», «обесценива»), а не по полной форме.",
            "3. Один и тот же пост может встречаться в нескольких срезах-полках —",
            "   считать повторы одним источником.",
            "",
            "## Запреты",
            "",
            "- Не переименовывать и не изменять файлы архива.",
            "- Не дополнять и не домысливать то, чего нет в архиве.",
            "",
        ])
        return "\n".join(lines)

    # ── KB preset stage 10b (dynamic instruction) ──
    def _render_archive_structure(
        self,
        chat_title:     str,
        chat_meta:      dict,
        exported_files: List[str],
    ) -> List[str]:
        """Строит динамическую секцию «Структура архива» для инструкции ИИ.

        Анализирует имена MD-файлов из exported_files и описывает
        конкретные шаблоны имён вместо абстрактного «MD-файлы».
        """
        md_files = [f for f in exported_files if f.endswith(".md")]
        has_posts = any(re.search(r"_post_\d+", Path(f).name) for f in md_files)
        has_chunks = any(re.search(r"_part_\d+\.md$", Path(f).name) for f in md_files)
        has_threads = any("_threads_" in Path(f).name for f in md_files)
        has_media = any("media" in f for f in exported_files)

        # Примеры имён файлов для описания (до 2 каждого типа)
        post_examples = []
        chat_examples = []
        chunk_examples = []
        thread_examples = []
        for f in md_files:
            name = Path(f).name
            if re.search(r"_post_\d+", name) and len(post_examples) < 2:
                post_examples.append(f"`{name}`")
            if re.search(r"_part_\d+\.md$", name) and len(chunk_examples) < 2:
                chunk_examples.append(f"`{name}`")
            if "_threads_" in name and len(thread_examples) < 2:
                thread_examples.append(f"`{name}`")
            if (not re.search(r"_post_\d+", name)
                    and not re.search(r"_part_\d+", name)
                    and "_threads_" not in name
                    and len(chat_examples) < 2):
                chat_examples.append(f"`{name}`")

        posts_count = chat_meta.get("posts_count", 0)
        is_channel = chat_meta.get("type") == "channel"
        lines: List[str] = ["## Структура архива", ""]

        # ── Оглавление ───────────────────────────────────────────────
        if is_channel and posts_count > 0:
            lines.extend([
                "- `00_Оглавление.md` — таблица всех постов: номер, дата, "
                "заголовок, ссылка на файл. Это **файловый индекс** для "
                "быстрого перехода к нужному посту.",
                "",
                "  **Важно:** столбец «О чём» содержит **авторские заголовки** "
                "постов. Они часто метафоричны, ироничны или не раскрывают "
                "содержание (например: «ОДНА ФРАЗА, КОТОРАЯ ЗАСТАВИЛА "
                "ЗАВИСНУТЬ» — пост про вычислимость сознания). Для понимания "
                "темы поста — читай полные тексты файлов, не ориентируйся "
                "только по заголовкам.",
                "",
            ])
        else:
            lines.extend([
                "- `00_Оглавление.md` — помесячная таблица сообщений со "
                "ссылками на файлы. Для диалогов также содержит хронокарту "
                "(всплески и паузы активности).",
                "",
            ])

        # ── Файлы постов ─────────────────────────────────────────────
        if has_posts:
            lines.extend([
                "- Файлы постов — каждый пост канала в отдельном MD-файле "
                "вместе с его комментариями:",
            ])
            if post_examples:
                lines.append(f"  пример: {post_examples[0]}")
            lines.extend([
                "  ID в имени файла — номер сообщения-поста в Telegram. "
                "Каждый файл имеет YAML-шапку с метаданными "
                "(chat, post, date, author, type, comments_count).",
                "",
            ])

        # ── Файлы чанков ─────────────────────────────────────────────
        if has_chunks:
            lines.extend([
                "- Чанки — части большого архива, разбитые по объёму:",
            ])
            if chunk_examples:
                lines.append(f"  пример: {chunk_examples[0]}")
            lines.extend([
                "  Номер части нарастает. Каждый чанк — самодостаточный "
                "фрагмент переписки.",
                "",
            ])

        # ── Треды ────────────────────────────────────────────────────
        if has_threads:
            lines.extend([
                "- Ветки (треды) — сообщения пользователя и ответы на них:",
            ])
            if thread_examples:
                lines.append(f"  пример: {thread_examples[0]}")
            lines.extend([
                "  Глубина ответа показана отступами и маркером «↳».",
                "",
            ])

        # ── Обычный файл чата ────────────────────────────────────────
        if not has_posts and not has_chunks and chat_examples:
            lines.extend([
                "- Полный архив переписки в одном файле:",
            ])
            lines.append(f"  {chat_examples[0]}")
            lines.extend([
                "  Содержит все сообщения в хронологическом порядке. "
                "Каждое сообщение имеет YAML-шапку с метаданными.",
                "",
            ])
        elif chat_examples and not has_posts:
            lines.extend([
                "- Архив переписки:",
            ])
            lines.append(f"  пример: {chat_examples[0]}")
            lines.extend([""])

        # ── Паспорт ──────────────────────────────────────────────────
        lines.extend([
            "- `archive_passport.json` — машиночитаемый паспорт архива "
            "(версия, даты, счётчики, список всех файлов).",
        ])

        # ── Медиа ────────────────────────────────────────────────────
        if has_media:
            lines.extend([
                "- Папка `media/` — медиафайлы (фото, видео, голосовые, "
                "файлы). Голосовые и кружочки, расшифрованные через STT, "
                "имеют текстовую расшифровку прямо в MD-файле поста.",
            ])

        lines.append("")
        return lines

    def _build_passport(
        self,
        chat_id:        int,
        chat_title:     str,
        chat_meta:      dict,
        exported_files: List[str],
        artifacts:      List[str],
        log:            _LogCallback,
    ) -> str:
        """Этап 7: строит archive_passport.json."""
        log("  Построение паспорта архива…")
        passport_path = self._output_dir / PASSPORT_FILENAME

        # Включаем сам паспорт в список артефактов
        all_artifacts = list(artifacts) + [str(passport_path)]

        passport = {
            "schema_version": KB_SCHEMA_VERSION,
            "parser_version": PARSER_VERSION,
            "generated_at":   datetime.now().isoformat(timespec="seconds"),
            "chat": {
                "title":       chat_title,
                "type":        chat_meta.get("type"),
                "chat_id":     chat_id,
                "period_min":  chat_meta.get("period_min"),
                "period_max":  chat_meta.get("period_max"),
                "linked_chat_id": chat_meta.get("linked_chat_id"),
            },
            "counts": {
                "posts_count":        chat_meta.get("posts_count", 0),
                "messages_count":     chat_meta.get("messages_count", 0),
                "comments_count":     chat_meta.get("comments_count", 0),
                "participants_count": chat_meta.get("participants_count", 0),
            },
            # N-17: машиночитаемый частотный срез — внешний инструмент
            # понимает тему архива, не открывая ни одного файла выгрузки.
            "top_terms": [
                {"term": word, "count": count}
                for word, count in self._get_top_terms(chat_id)
            ],
            "shelves": [
                {
                    "name": "chat_archive",
                    "type": "chat_archive",
                    "description": "Первичная выгрузка чата через Rozitta Parser",
                }
            ],
            "artifacts": [
                {"path": self._rel_artifact_path(a),
                 "type": self._artifact_type(a)}
                for a in all_artifacts
            ],
            "exported_files_count": len(exported_files),
        }

        # Для диалогов — добавляем хронокарту
        chmap = self._build_chronological_map(chat_id)
        if chmap is not None:
            passport["chronological_map"] = chmap

        passport_path.write_text(
            json.dumps(passport, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        log(f"  Паспорт: {passport_path.name}")
        return str(passport_path)

    def _rel_artifact_path(self, artifact_path: str) -> str:
        """Возвращает путь артефакта относительно output_dir (POSIX)."""
        try:
            return Path(artifact_path).relative_to(self._output_dir).as_posix()
        except ValueError:
            return Path(artifact_path).as_posix()

    @staticmethod
    def _artifact_type(path: str) -> str:
        """Определяет тип артефакта по имени файла."""
        name = Path(path).name
        if name == INDEX_FILENAME:
            return "index"
        if name in (INSTRUCTION_RU, INSTRUCTION_CLAUDE, INSTRUCTION_AGENTS):
            return "instruction"
        if name == PASSPORT_FILENAME:
            return "passport"
        if name.endswith(".md"):
            return "markdown"
        if name.endswith(".json"):
            return "json"
        return "other"

    def _build_chronological_map(self, chat_id: int) -> Optional[dict]:
        """Этап 8: хронокарта для чатов БЕЗ постов канала."""
        chat_meta = self._db.get_chat_info(chat_id)
        if chat_meta.get("type") == "channel" and chat_meta.get("posts_count", 0) > 0:
            return None
        chmap = self._db.get_chronological_map(chat_id)
        monthly = [(m["ym"], m["count"]) for m in chmap["messages_by_month"]]
        chmap["bursts_info"] = compute_iqr_bursts(monthly)
        return chmap
