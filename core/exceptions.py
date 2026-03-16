"""
core/exceptions.py — Иерархия исключений Rozitta Parser

Все кастомные исключения проекта организованы в дерево:

    RozittaError                     ← базовый класс всех ошибок проекта
    ├── ConfigError                  ← ошибки конфигурации (API ID, Hash)
    ├── AuthError                    ← ошибки авторизации Telegram
    │   ├── SessionExpiredError      ← сессия устарела, нужен повторный вход
    │   └── PhoneCodeInvalidError    ← неверный код подтверждения
    ├── DatabaseError                ← ошибки SQLite
    │   └── DatabaseLockedError      ← "database is locked" после retry
    ├── TelegramError                ← ошибки Telegram API
    │   ├── ChatNotFoundError        ← чат не найден или нет доступа
    │   ├── ForumTopicsError         ← не удалось получить топики форума
    │   ├── FloodWaitError           ← Telegram просит подождать
    │   ├── LinkedGroupNotFoundError ← нет linked discussion группы
    │   └── MediaDownloadError       ← ошибка скачивания медиафайла
    └── ExportError                  ← ошибки генерации документов
        ├── DocxGenerationError      ← ошибка python-docx
        └── EmptyDataError           ← нет данных для экспорта

Рекомендации по использованию:

    # В features/chats/api.py:
    from core.exceptions import ChatNotFoundError

    entity = await client.get_entity(chat_id)
    if entity is None:
        raise ChatNotFoundError(chat_id)

    # В UI (features/chats/ui.py):
    try:
        topics = await manager.get_topics(chat_id)
    except FloodWaitError as e:
        self.log_signal.emit(f"⏳ Подождите {e.seconds} сек...")
        await asyncio.sleep(e.seconds)
    except ChatNotFoundError as e:
        self.error_signal.emit(str(e))

    # В тестах:
    with pytest.raises(ChatNotFoundError, match="1234567"):
        await manager.get_topics(1234567)
"""

from __future__ import annotations

from typing import Optional


# ==============================================================================
# Базовый класс
# ==============================================================================

class RozittaError(Exception):
    """
    Базовый класс всех ошибок Rozitta Parser.

    Все кастомные исключения наследуются отсюда — это позволяет ловить
    любую «бизнес-ошибку» проекта одним except:

        try:
            await manager.collect_data(...)
        except RozittaError as e:
            logger.error("Ошибка парсера: %s", e)
    """

    def __init__(self, message: str = "", *args) -> None:
        super().__init__(message, *args)
        self.message = message

    def __str__(self) -> str:
        return self.message or self.__class__.__name__


# ==============================================================================
# Конфигурация
# ==============================================================================

class ConfigError(RozittaError):
    """
    Ошибка конфигурации приложения.

    Возникает при старте, если отсутствуют или некорректны обязательные
    настройки: API ID, API Hash, или путь к файлу конфига.

    Example:
        raise ConfigError("API ID не указан. Проверьте config_modern.json")
    """


# ==============================================================================
# Авторизация
# ==============================================================================

class AuthError(RozittaError):
    """
    Базовый класс ошибок авторизации в Telegram.

    Наследуй от него для конкретных случаев (неверный код,
    истёкшая сессия и т.д.).
    """


class SessionExpiredError(AuthError):
    """
    Telegram-сессия устарела или была отозвана.

    Пользователь должен заново пройти авторизацию (ввести номер и код).

    Example:
        raise SessionExpiredError(
            "Сессия устарела. Войдите заново."
        )
    """


class PhoneCodeInvalidError(AuthError):
    """
    Введённый код подтверждения не совпал.

    Example:
        raise PhoneCodeInvalidError("Неверный код. Попробуйте ещё раз.")
    """


# ==============================================================================
# База данных
# ==============================================================================

class DatabaseError(RozittaError):
    """
    Базовый класс ошибок работы с SQLite.

    Оборачивает sqlite3.Error для единообразной обработки в слое UI.
    """

    def __init__(self, message: str = "", original: Optional[Exception] = None) -> None:
        super().__init__(message)
        self.original = original  # оригинальное sqlite3.Error для диагностики

    def __str__(self) -> str:
        if self.original:
            return f"{self.message} (причина: {self.original})"
        return self.message


class DatabaseLockedError(DatabaseError):
    """
    База данных заблокирована после исчерпания retry-попыток.

    Возникает в DBManager._cursor() когда все 3 попытки с backoff
    провалились. Как правило — признак конкурентного доступа без WAL.

    Example:
        raise DatabaseLockedError(
            "БД заблокирована после 3 попыток",
            original=sqlite3_error
        )
    """


# ==============================================================================
# Telegram API
# ==============================================================================

class TelegramError(RozittaError):
    """
    Базовый класс ошибок Telegram API.

    Используй подклассы для конкретных ситуаций. Это позволяет UI
    показывать точные сообщения вместо «что-то пошло не так».
    """


class ChatNotFoundError(TelegramError):
    """
    Чат не найден или у аккаунта нет прав на доступ.

    Возникает при get_entity() / iter_messages() когда Telegram вернул
    ChannelInvalid, ChannelPrivate или аналогичную ошибку.

    Attributes:
        chat_id: ID чата, который не удалось найти.

    Example:
        raise ChatNotFoundError(chat_id=-1002882674903)
    """

    def __init__(self, chat_id: int, message: str = "") -> None:
        self.chat_id = chat_id
        msg = message or f"Чат {chat_id} не найден или нет доступа"
        super().__init__(msg)


class ForumTopicsError(TelegramError):
    """
    Не удалось получить список топиков форума.

    Возникает когда оба метода провалились:
    1) GetForumTopicsRequest вернул ошибку
    2) Fallback через iter_messages не нашёл топиков

    Attributes:
        chat_id: ID форума.

    Example:
        raise ForumTopicsError(chat_id=-1002882674903)
    """

    def __init__(self, chat_id: int, message: str = "") -> None:
        self.chat_id = chat_id
        msg = message or f"Не удалось получить топики форума {chat_id}"
        super().__init__(msg)


class FloodWaitError(TelegramError):
    """
    Telegram требует паузу (anti-flood protection).

    В отличие от telethon.errors.FloodWaitError, этот класс —
    часть нашей бизнес-логики и используется в features/parser/api.py
    для передачи времени ожидания в UI через Qt Signal.

    Attributes:
        seconds: Сколько секунд нужно подождать (из e.seconds Telethon).

    Example:
        except telethon.errors.FloodWaitError as e:
            raise FloodWaitError(e.seconds)
    """

    def __init__(self, seconds: int, message: str = "") -> None:
        self.seconds = seconds
        msg = message or f"Telegram требует паузу: {seconds} сек."
        super().__init__(msg)


class LinkedGroupNotFoundError(TelegramError):
    """
    У канала нет привязанной группы для комментариев.

    Возникает когда get_linked_discussion_group() возвращает None,
    но пользователь включил опцию «скачивать комментарии».

    Attributes:
        channel_id: ID канала без linked группы.

    Example:
        raise LinkedGroupNotFoundError(channel_id=-1002882674903)
    """

    def __init__(self, channel_id: int, message: str = "") -> None:
        self.channel_id = channel_id
        msg = message or f"У канала {channel_id} нет группы комментариев"
        super().__init__(msg)


class MediaDownloadError(TelegramError):
    """
    Ошибка скачивания медиафайла.

    Возникает при client.download_media(), если файл недоступен,
    слишком большой, или произошла сетевая ошибка.

    Attributes:
        message_id:  ID сообщения, чьё медиа не скачалось.
        original:    Оригинальное исключение для диагностики.

    Example:
        raise MediaDownloadError(
            message_id=12345,
            message="Видео слишком большое (>2 ГБ)",
        )
    """

    def __init__(
        self,
        message_id: int,
        message:    str                = "",
        original:   Optional[Exception] = None,
    ) -> None:
        self.message_id = message_id
        self.original   = original
        msg = message or f"Ошибка скачивания медиа сообщения #{message_id}"
        super().__init__(msg)

    def __str__(self) -> str:
        base = self.message
        if self.original:
            return f"{base} (причина: {self.original})"
        return base


# ==============================================================================
# STT — распознавание речи
# ==============================================================================

class STTError(RozittaError):
    """
    Ошибка обработки STT (Speech-to-Text).

    Возникает при конвертации аудио через FFmpeg или при транскрибировании
    через faster-whisper.

    Attributes:
        media_path: Путь к медиафайлу, вызвавшему ошибку.
        message_id: ID Telegram-сообщения (если известен).

    Example:
        raise STTError(
            "FFmpeg не найден. Установите FFmpeg и добавьте в PATH.",
            media_path="/output/voice_12345.ogg",
        )
    """

    def __init__(
        self,
        message:    str           = "STT error",
        *,
        media_path: Optional[str] = None,
        message_id: Optional[int] = None,
    ) -> None:
        self.media_path = media_path
        self.message_id = message_id
        super().__init__(message)


# ==============================================================================
# Экспорт / генерация документов
# ==============================================================================

class ExportError(RozittaError):
    """
    Базовый класс ошибок генерации документов (DOCX, PDF и т.д.).
    """


class DocxGenerationError(ExportError):
    """
    Ошибка при создании DOCX-файла через python-docx.

    Возникает при сбое Document.save(), add_picture() или
    работе с XML-магией (закладки, ссылки).

    Attributes:
        file_path: Путь к файлу, который пытались создать.
        original:  Оригинальное исключение.

    Example:
        raise DocxGenerationError(
            file_path="output/archive.docx",
            message="Не удалось вставить изображение",
            original=exc,
        )
    """

    def __init__(
        self,
        file_path: str,
        message:   str                = "",
        original:  Optional[Exception] = None,
    ) -> None:
        self.file_path = file_path
        self.original  = original
        msg = message or f"Ошибка генерации DOCX: {file_path}"
        super().__init__(msg)

    def __str__(self) -> str:
        base = self.message
        if self.original:
            return f"{base} (причина: {self.original})"
        return base


class EmptyDataError(ExportError):
    """
    В базе данных нет сообщений для экспорта.

    Возникает в generate_docx() когда get_messages() вернул пустой список.
    Позволяет UI показать конкретное сообщение вместо создания пустого файла.

    Attributes:
        chat_id:  ID чата.
        topic_id: ID топика (если был фильтр по топику).

    Example:
        raise EmptyDataError(chat_id=-1002882674903, topic_id=5)
    """

    def __init__(
        self,
        chat_id:  int,
        topic_id: Optional[int] = None,
        message:  str           = "",
    ) -> None:
        self.chat_id  = chat_id
        self.topic_id = topic_id

        if message:
            msg = message
        elif topic_id is not None:
            msg = f"Нет сообщений в чате {chat_id}, топик {topic_id}"
        else:
            msg = f"Нет сообщений в чате {chat_id} для экспорта"

        super().__init__(msg)
