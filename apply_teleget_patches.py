"""
apply_teleget_patches.py  — интеграция TeleGet в features/parser/api.py
========================================================================
Запуск из корня проекта:
    python apply_teleget_patches.py

Установка зависимости (до запуска):
    pip install teleget9527[all]

Что меняется (4 патча)
──────────────────────
PATCH 1 — константы _TELEGET_THRESHOLD_BYTES=50МБ, _TELEGET_MAX_TIMEOUT=4ч
PATCH 2 — self._teleget_downloader=None в __init__
PATCH 3 — новые методы _init_teleget() и _teleget_download_file()
PATCH 4 — замена тела _download_media: TeleGet для ≥50МБ, fallback на Telethon

Нюансы
──────
• @async_retry остаётся на _download_media как внешний guard.
• Семафор _MEDIA_PARALLELISM сохраняется.
• Частичные файлы НЕ удаляются ни в каком сценарии.
• Если teleget9527 не установлен — всё работает как раньше + предупреждение в лог.
• TeleGet API ожидается: Downloader(client).download(message, save_path=path).
  Если ваша версия использует другой ключ — правьте одну строку в _teleget_download_file.
"""

import re
import sys
from pathlib import Path

TARGET = Path("features/parser/api.py")

if not TARGET.exists():
    print(f"ABORT: {TARGET} не найден. Запустите из корня проекта.")
    sys.exit(1)

src = TARGET.read_text(encoding="utf-8")
original = src
applied = 0

# ══════════════════════════════════════════════════════════════════════════════
# PATCH 1 — Константы TeleGet
# ══════════════════════════════════════════════════════════════════════════════

NEW_1_SUFFIX = (
    "\n"
    "# ── TeleGet — докачка больших файлов ─────────────────────────────────────────\n"
    "# Порог в байтах: файлы НИЖЕ этого лимита скачиваются стандартным\n"
    "# Telethon download_media (быстро, без лишних зависимостей).\n"
    "# Файлы ВЫШЕ лимита → TeleGet (поддерживает resume, FILE_REFERENCE_EXPIRED,\n"
    "# многопоточность внутри одного потока asyncio).\n"
    "_TELEGET_THRESHOLD_BYTES: int = 50 * 1_024 * 1_024   # 50 МБ\n"
    "# Максимальный таймаут для TeleGet-загрузок (секунды).\n"
    "# TeleGet сам восстанавливается после разрывов; этот guard нужен только\n"
    "# если процесс «завис» на уровне ОС (например, потерян сокет без TCP RST).\n"
    "_TELEGET_MAX_TIMEOUT: float = 4.0 * 3600.0             # 4 часа\n"
)

OLD_1_A = (
    '# Подпапки для каждого типа медиа внутри MEDIA_FOLDER_NAME\n'
    '_MEDIA_SUBFOLDERS: dict[str, str] = {\n'
    '    "photo":      "photos",\n'
    '    "video":      "videos",\n'
    '    "voice":      "voice",\n'
    '    "video_note": "video_notes",\n'
    '    "files":      "files",\n'
    '}\n'
)
OLD_1_B = OLD_1_A.replace('"files":      "files"', '"file":       "files"')

if OLD_1_A in src:
    src = src.replace(OLD_1_A, OLD_1_A + NEW_1_SUFFIX, 1)
    print("OK: PATCH 1 applied (key=files)"); applied += 1
elif OLD_1_B in src:
    src = src.replace(OLD_1_B, OLD_1_B + NEW_1_SUFFIX, 1)
    print("OK: PATCH 1 applied (key=file)"); applied += 1
else:
    m = re.search(r'(_MEDIA_SUBFOLDERS\s*:\s*dict\[.*?\]\s*=\s*\{[^}]+\}\n)', src, re.DOTALL)
    if m:
        src = src[: m.end()] + NEW_1_SUFFIX + src[m.end():]
        print("OK: PATCH 1 applied (regex fallback)"); applied += 1
    else:
        print("WARN: PATCH 1 — _MEDIA_SUBFOLDERS block not found, skipping")

# ══════════════════════════════════════════════════════════════════════════════
# PATCH 2 — __init__: self._teleget_downloader = None
# ══════════════════════════════════════════════════════════════════════════════

OLD_2 = (
    "        # Текущий контекст (для путей к медиа)\n"
    '        self._chat_title:  str = "chat"\n'
    '        self._output_dir:  str = "output"\n'
)
NEW_2 = (
    "        # Текущий контекст (для путей к медиа)\n"
    '        self._chat_title:  str = "chat"\n'
    '        self._output_dir:  str = "output"\n'
    "\n"
    "        # TeleGet загрузчик — инициализируется лениво при первом вызове\n"
    "        # _init_teleget().  None = ещё не инициализирован;\n"
    "        # False = попытка провалилась (библиотека отсутствует);\n"
    "        # объект Downloader = готов к работе.\n"
    "        self._teleget_downloader = None  # type: ignore[assignment]\n"
)

if OLD_2 in src:
    src = src.replace(OLD_2, NEW_2, 1)
    print("OK: PATCH 2 applied"); applied += 1
else:
    print("WARN: PATCH 2 — __init__ context block not found, skipping")

# ══════════════════════════════════════════════════════════════════════════════
# PATCH 3 — _init_teleget() + _teleget_download_file() перед _download_media
# ══════════════════════════════════════════════════════════════════════════════

NEW_METHODS = '''\
    # ------------------------------------------------------------------
    # 2b. Инициализация TeleGet (lazy, один раз на экземпляр)
    # ------------------------------------------------------------------

    async def _init_teleget(self) -> object:
        """
        Лениво инициализирует TeleGet Downloader и возвращает его.

        TeleGet API (teleget9527):
            from teleget import Downloader
            dl = Downloader(client)
            await dl.start()           # запускает внутренние воркеры (опционально)
            path = await dl.download(message, save_path=target_path)

        Returns:
            Объект Downloader если инициализация прошла успешно, иначе None.
        """
        if self._teleget_downloader is not None:
            # False означает «библиотека недоступна» — не пытаемся повторно
            return self._teleget_downloader if self._teleget_downloader is not False else None

        try:
            from teleget import Downloader  # type: ignore[import]
            dl = Downloader(self._client)
            # Некоторые версии TeleGet требуют явного start()
            if hasattr(dl, "start") and asyncio.iscoroutinefunction(dl.start):
                await dl.start()
            self._teleget_downloader = dl
            logger.info(
                "parser: TeleGet Downloader инициализирован (порог >= %d МБ)",
                _TELEGET_THRESHOLD_BYTES // (1024 * 1024),
            )
            return dl
        except ImportError:
            self._teleget_downloader = False  # type: ignore[assignment]
            logger.warning(
                "parser: teleget9527 не установлен — "
                "для больших файлов используется стандартный download_media. "
                "Установите: pip install teleget9527[all]"
            )
            return None
        except Exception as exc:
            self._teleget_downloader = False  # type: ignore[assignment]
            logger.warning(
                "parser: TeleGet init failed: %s — fallback to download_media", exc
            )
            return None

    async def _teleget_download_file(
        self,
        message:     "Message",
        target_path: str,
        file_size:   int,
    ) -> "Optional[str]":
        """
        Скачивает файл через TeleGet с поддержкой докачки.

        Не удаляет частичные файлы при ошибке — TeleGet возобновит
        с того же места при следующем вызове с тем же target_path.

        Args:
            message:     Telethon Message с медиа.
            target_path: Желаемый путь (TeleGet использует его как base name).
            file_size:   Размер файла в байтах (для логов).

        Returns:
            Реальный путь к скачанному файлу или None (вызывающий выполнит fallback).
        """
        dl = await self._init_teleget()
        if dl is None:
            return None

        mb = file_size // (1024 * 1024)
        self._log(
            f"⬇️  TeleGet: скачивание {mb} МБ "
            f"(msg_id={message.id}, таймаут {int(_TELEGET_MAX_TIMEOUT // 3600)} ч)"
        )
        logger.info(
            "parser: TeleGet download start: msg_id=%d size=%d bytes path=%s",
            message.id, file_size, target_path,
        )

        # TeleGet API: Downloader.download(message, save_path=…)
        # Если ваша версия библиотеки использует другой ключ аргумента —
        # замените save_path= на file= или path= в строке ниже:
        try:
            result = await asyncio.wait_for(
                dl.download(message, save_path=target_path),
                timeout=_TELEGET_MAX_TIMEOUT,
            )
            logger.info(
                "parser: TeleGet download done: msg_id=%d -> %s",
                message.id, result,
            )
            self._log(
                f"✅ TeleGet: сохранён -> {os.path.basename(str(result or target_path))}"
            )
            return result or target_path
        except asyncio.TimeoutError:
            logger.error(
                "parser: TeleGet timeout (%.0f ч) msg_id=%d — "
                "частичный файл НЕ удалён, докачка при следующем запуске",
                _TELEGET_MAX_TIMEOUT / 3600, message.id,
            )
            self._log(
                f"⚠️  TeleGet: таймаут {int(_TELEGET_MAX_TIMEOUT // 3600)} ч "
                f"(msg_id={message.id}) — частичный файл сохранён для докачки"
            )
            return None
        except Exception as exc:
            logger.warning(
                "parser: TeleGet error msg_id=%d: %s — "
                "частичный файл НЕ удалён, fallback на download_media",
                message.id, exc,
            )
            self._log(f"⚠️  TeleGet ошибка (msg_id={message.id}): {exc} — fallback")
            return None

'''

MARKER = "    @async_retry(\n        max_attempts = _MAX_RETRIES,"
if MARKER in src:
    src = src.replace(MARKER, NEW_METHODS + MARKER, 1)
    print("OK: PATCH 3 applied (_init_teleget + _teleget_download_file inserted)"); applied += 1
else:
    print("WARN: PATCH 3 — @async_retry marker before _download_media not found, skipping")

# ══════════════════════════════════════════════════════════════════════════════
# PATCH 4 — Замена тела _download_media
# ══════════════════════════════════════════════════════════════════════════════

NEW_DOWNLOAD_MEDIA = '''\
    @async_retry(
        max_attempts = _MAX_RETRIES,
        base_delay   = _RETRY_BASE_DELAY,
        backoff      = 2.0,
        exc_retry    = (OSError, RPCError),
        flood_cls    = TelethonFloodWaitError,
        flood_buffer = _FLOOD_BUFFER,
    )
    async def _download_media(
        self,
        message:     Message,
        target_path: str,
    ) -> Optional[str]:
        """
        Скачивает медиа сообщения на диск.

        Стратегия выбора пути загрузки
        ──────────────────────────────
        • Файл < _TELEGET_THRESHOLD_BYTES (50 МБ):
              Telethon download_media + потоковая запись на диск.
              Таймаут динамический: max(600 с, size / 512 КБ/с + 120 с).
        • Файл >= _TELEGET_THRESHOLD_BYTES:
              1) TeleGet (_teleget_download_file) — докачка, FILE_REFERENCE_EXPIRED,
                 многопоточность внутри одного asyncio-потока.
              2) Если TeleGet недоступен или вернул ошибку — fallback на Telethon.
        • Частичные файлы НЕ удаляются ни в каком сценарии:
              TeleGet продолжит докачку при следующем вызове с тем же путём;
              Telethon перезапишет файл поверх при следующей попытке.

        Retry-логика (декоратор @async_retry):
            FloodWait → sleep(seconds + _FLOOD_BUFFER), не считается попыткой.
            OSError / RPCError → экспоненциальный backoff, макс. _MAX_RETRIES раз.
            После исчерпания попыток → re-raise последнего исключения.

        Args:
            message:     Telethon Message с медиа.
            target_path: Путь без расширения (Telethon добавит .jpg/.mp4/...).

        Returns:
            Реальный путь к скачанному файлу (с расширением) или None.

        Raises:
            OSError | RPCError: после _MAX_RETRIES неудачных попыток.
        """
        # ── Определяем размер файла ──────────────────────────────────────────
        _file_size: int = 0
        if hasattr(message.media, "document") and message.media.document:
            _file_size = getattr(message.media.document, "size", 0) or 0
        # Фото — всегда маленькие, динамический таймаут покроет

        logger.debug(
            "[DIAG] download_media start: msg_id=%s media=%s path=%s size=%d",
            message.id, type(message.media).__name__, target_path, _file_size,
        )

        async with self._sem:
            # ── Путь 1: TeleGet для больших файлов ───────────────────────────
            if _file_size >= _TELEGET_THRESHOLD_BYTES:
                result = await self._teleget_download_file(
                    message, target_path, _file_size
                )
                if result is not None:
                    logger.debug(
                        "[DIAG] download_media via TeleGet OK: msg_id=%s -> %s",
                        message.id, result,
                    )
                    return result
                # TeleGet вернул None (недоступен или ошибка) → fallback ниже
                logger.debug(
                    "[DIAG] TeleGet fallback -> download_media: msg_id=%s", message.id
                )
                self._log(
                    f"⬇️  Telethon fallback: {_file_size // (1024*1024)} МБ "
                    f"(msg_id={message.id})"
                )

            # ── Путь 2: Telethon download_media (малые файлы + fallback) ─────
            # Динамический таймаут: 2 сек/МБ + 2 мин запаса, минимум 600 с
            _timeout: float = max(600.0, _file_size / (512 * 1024) + 120.0)
            logger.debug(
                "[DIAG] download_media (telethon): msg_id=%s size=%d timeout=%.0fs",
                message.id, _file_size, _timeout,
            )
            try:
                result = await asyncio.wait_for(
                    message.download_media(file=target_path),
                    timeout=_timeout,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "[DIAG] download_media timeout: msg_id=%s size=%d timeout=%.0fs "
                    "— частичный файл НЕ удалён",
                    message.id, _file_size, _timeout,
                )
                # Частичный файл НЕ удаляем — Telethon перезапишет при retry
                return None

        logger.debug(
            "[DIAG] download_media done (telethon): msg_id=%s -> %s",
            message.id, result,
        )
        return result

'''

pattern_dl = re.compile(
    r"    @async_retry\(\s*\n"
    r"        max_attempts = _MAX_RETRIES,.*?"
    r"(?=\n    # ----|\n    @|\n    async def |\n    def )",
    re.DOTALL,
)
m = pattern_dl.search(src)
if m:
    src = src[: m.start()] + NEW_DOWNLOAD_MEDIA + src[m.end():]
    print("OK: PATCH 4 applied (_download_media replaced)"); applied += 1
else:
    print("WARN: PATCH 4 — _download_media body not found via regex, skipping")

# ══════════════════════════════════════════════════════════════════════════════
# Сохранение и итог
# ══════════════════════════════════════════════════════════════════════════════

if src != original:
    TARGET.write_text(src, encoding="utf-8")
    print(f"\n✅ Сохранено: {TARGET}  ({applied}/4 патчей применено)")
else:
    print(f"\n⚠️  Файл не изменён (применено {applied}/4 патчей)")

if applied < 4:
    print(
        "\n⚠️  Не все патчи применены.\n"
        "   Проверьте отступы и версию файла или примените изменения вручную\n"
        "   по описанию в начале этого скрипта."
    )
else:
    print(
        "\nГотово! Следующий шаг:\n"
        "    pip install teleget9527[all]\n\n"
        "Если TeleGet использует другой ключ аргумента download(), найдите\n"
        "строку «dl.download(message, save_path=target_path)» в\n"
        "features/parser/api.py → метод _teleget_download_file() и поправьте ключ."
    )
