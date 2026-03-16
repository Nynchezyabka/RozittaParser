"""
core/stt/audio_converter.py — FFmpeg pipeline для конвертации аудио/видео в WAV

Назначение:
    Конвертирует голосовые сообщения (.ogg), видео (.mp4) и кружки в
    16kHz моно WAV — формат, который требует faster-whisper.

Нет Qt-импортов. Чистый Python + subprocess.

Использование:
    wav_path = AudioConverter.convert_to_wav(input_path)
    try:
        text = whisper_manager.transcribe(wav_path)
    finally:
        AudioConverter.cleanup(wav_path)
"""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from typing import Optional

from core.exceptions import STTError

logger = logging.getLogger(__name__)


class AudioConverter:
    """
    Конвертирует аудио/видео файлы в 16kHz моно WAV через FFmpeg.

    Все методы статические — объект создавать не нужно.

    Требования:
        FFmpeg установлен и доступен в PATH.
    """

    @staticmethod
    def convert_to_wav(input_path: str, output_path: Optional[str] = None) -> str:
        """
        Конвертирует файл в 16kHz моно WAV.

        Параметры FFmpeg:
            -ar 16000   — частота дискретизации 16kHz (требование Whisper)
            -ac 1       — моно (один канал)
            -acodec pcm_s16le — несжатый PCM 16-bit LE
            -y          — перезаписать выходной файл без вопросов

        Args:
            input_path:  Путь к входному файлу (.ogg, .mp4, .mp3 и т.д.).
            output_path: Путь к выходному WAV. Если None — создаётся tempfile.

        Returns:
            Абсолютный путь к созданному WAV-файлу.

        Raises:
            STTError: FFmpeg не найден, завершился с ошибкой или истёк timeout.
        """
        if not os.path.exists(input_path):
            raise STTError(
                f"Входной файл не найден: {input_path}",
                media_path=input_path,
            )

        if output_path is None:
            fd, output_path = tempfile.mkstemp(suffix=".wav")
            os.close(fd)

        cmd = [
            "ffmpeg",
            "-i", input_path,
            "-ar", "16000",
            "-ac", "1",
            "-acodec", "pcm_s16le",
            "-y",
            output_path,
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
            )
        except FileNotFoundError:
            raise STTError(
                "FFmpeg не найден. Установите FFmpeg и добавьте в PATH.",
                media_path=input_path,
            )
        except subprocess.TimeoutExpired:
            raise STTError(
                "FFmpeg завис (>120 сек). Файл может быть повреждён.",
                media_path=input_path,
            )

        if result.returncode != 0:
            raise STTError(
                f"FFmpeg завершился с ошибкой (код {result.returncode}): "
                f"{result.stderr[:300]}",
                media_path=input_path,
            )

        if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
            raise STTError(
                "FFmpeg создал пустой файл — возможно, нет аудиодорожки.",
                media_path=input_path,
            )

        logger.debug("AudioConverter: %s → %s", input_path, output_path)
        return output_path

    @staticmethod
    def cleanup(wav_path: str) -> None:
        """
        Удаляет временный WAV-файл после транскрибирования.

        Не бросает исключений — ошибка удаления только логируется.

        Args:
            wav_path: Путь к WAV-файлу для удаления.
        """
        if not wav_path:
            return
        try:
            if os.path.exists(wav_path):
                os.remove(wav_path)
                logger.debug("AudioConverter: удалён временный файл %s", wav_path)
        except OSError as exc:
            logger.warning("AudioConverter: не удалось удалить %s: %s", wav_path, exc)
