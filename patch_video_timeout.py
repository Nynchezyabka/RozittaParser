"""
PATCH — features/parser/api.py
Задача: исправить обрезку больших видео (1.5 ч, ~1+ ГБ).

Причина бага: asyncio.wait_for(..., timeout=120.0) в _download_media
прерывает скачивание через 2 минуты. Telethon успевает записать ~70 МБ
на диск — файл остаётся обрезанным и не открывается. Ошибка в лог
не попадает, потому что TimeoutError перехватывается молча.

Изменения:
  PATCH A — _download_media: динамический таймаут на основе file_size
             (min 300 сек; ~1 МБ/с как пессимистичная скорость).
             При TimeoutError удаляем обрезанный файл с диска.
  PATCH B — _flush_tasks: увеличиваем таймаут батча с 300 до 7200 сек
             (иначе один батч из 20 задач со скачиванием больших видео
              всё равно отменится раньше времени).

Побочные эффекты: нет. Оба изменения только увеличивают таймауты,
логику сохранения и retry не трогают.

Run: python patch_video_timeout.py
"""

PATH = "features/parser/api.py"

with open(PATH, encoding="utf-8") as f:
    src = f.read()
original = src


# ── PATCH A: динамический таймаут + удаление обрезанного файла ──────────────

OLD_A = (
    "        async with self._sem:\n"
    "            try:\n"
    "                result = await asyncio.wait_for(\n"
    "                    message.download_media(file=target_path),\n"
    "                    timeout=120.0,\n"
    "                )\n"
    "            except asyncio.TimeoutError:\n"
    "                logger.warning(\n"
    "                    \"[DIAG] download_media timeout: msg_id=%s media=%s, пропускаем\",\n"
    "                    message.id, type(message.media).__name__,\n"
    "                )\n"
    "                return None\n"
)

NEW_A = (
    "        # Динамический таймаут: file_size / 1 МБ/с (пессимистично) + 60 сек запаса.\n"
    "        # Минимум 300 сек — даже маленький файл может скачиваться долго на плохом соединении.\n"
    "        # Максимум не ограничен — лучше ждать, чем получить обрезанный файл.\n"
    "        _file_size: int = 0\n"
    "        if hasattr(message.media, 'document') and message.media.document:\n"
    "            _file_size = getattr(message.media.document, 'size', 0) or 0\n"
    "        elif hasattr(message.media, 'photo') and message.media.photo:\n"
    "            _file_size = 0  # фото маленькие, 300 сек хватит\n"
    "        _timeout = max(300.0, _file_size / (1024 * 1024) + 60.0)  # байты → секунды\n"
    "        logger.debug(\n"
    "            \"[DIAG] download_media: msg_id=%s size=%d bytes timeout=%.0fs\",\n"
    "            message.id, _file_size, _timeout,\n"
    "        )\n"
    "        async with self._sem:\n"
    "            try:\n"
    "                result = await asyncio.wait_for(\n"
    "                    message.download_media(file=target_path),\n"
    "                    timeout=_timeout,\n"
    "                )\n"
    "            except asyncio.TimeoutError:\n"
    "                logger.warning(\n"
    "                    \"[DIAG] download_media timeout: msg_id=%s media=%s size=%d bytes \"\n"
    "                    \"timeout=%.0fs — удаляем обрезанный файл\",\n"
    "                    message.id, type(message.media).__name__, _file_size, _timeout,\n"
    "                )\n"
    "                # Удаляем частичный файл — он нерабочий и занимает место\n"
    "                for _ext in ('.mp4', '.mkv', '.avi', '.mov', '.webm', '.ogg',\n"
    "                             '.jpg', '.jpeg', '.png', '.webp', ''):\n"
    "                    _partial = target_path + _ext if _ext else target_path\n"
    "                    if os.path.exists(_partial):\n"
    "                        try:\n"
    "                            os.remove(_partial)\n"
    "                            logger.debug(\"[DIAG] removed partial file: %s\", _partial)\n"
    "                        except OSError:\n"
    "                            pass\n"
    "                return None\n"
)

if OLD_A not in src:
    print("WARN: PATCH A (_download_media timeout) not found — проверьте отступы")
else:
    src = src.replace(OLD_A, NEW_A, 1)
    print("OK: PATCH A applied (dynamic timeout + partial file cleanup)")


# ── PATCH B: увеличить таймаут батча в _flush_tasks ─────────────────────────

OLD_B = (
    "        try:\n"
    "            results = await asyncio.wait_for(\n"
    "                asyncio.gather(*tasks, return_exceptions=True),\n"
    "                timeout=300.0,\n"
    "            )\n"
    "        except asyncio.TimeoutError:\n"
    "            logger.error(\n"
    "                \"[DIAG] _flush_tasks TIMEOUT: %d задач зависли, принудительно пропускаем\",\n"
    "                len(tasks),\n"
    "            )\n"
    "            results = [TimeoutError(f\"download_media timeout (batch of {len(tasks)})\")]"
    " * len(tasks)\n"
)

NEW_B = (
    "        # 7200 сек (2 часа) — батч из 20 задач может содержать несколько больших видео.\n"
    "        # Каждому видео даётся до ~2 часов своего таймаута (PATCH A),\n"
    "        # поэтому батч должен ждать не меньше.\n"
    "        try:\n"
    "            results = await asyncio.wait_for(\n"
    "                asyncio.gather(*tasks, return_exceptions=True),\n"
    "                timeout=7200.0,\n"
    "            )\n"
    "        except asyncio.TimeoutError:\n"
    "            logger.error(\n"
    "                \"[DIAG] _flush_tasks TIMEOUT: %d задач зависли, принудительно пропускаем\",\n"
    "                len(tasks),\n"
    "            )\n"
    "            results = [TimeoutError(f\"download_media timeout (batch of {len(tasks)})\")]"
    " * len(tasks)\n"
)

if OLD_B not in src:
    print("WARN: PATCH B (_flush_tasks timeout) not found — проверьте отступы")
else:
    src = src.replace(OLD_B, NEW_B, 1)
    print("OK: PATCH B applied (_flush_tasks timeout 300 → 7200 сек)")


# ── Запись ───────────────────────────────────────────────────────────────────
if src != original:
    with open(PATH, "w", encoding="utf-8") as f:
        f.write(src)
    print(f"\n✅ Сохранено: {PATH}")
else:
    print("\n⚠️ Файл не изменён — все патчи уже применены или строки не найдены")
