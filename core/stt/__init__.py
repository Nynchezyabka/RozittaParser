"""
core/stt/ — Модуль распознавания речи (Speech-to-Text)

Содержит:
    AudioConverter   — конвертация аудио/видео в 16kHz WAV через FFmpeg
    WhisperManager   — Singleton faster-whisper (Шаг 11)
    STTWorker        — QThread-обёртка для транскрибирования (Шаг 12)

Нет Qt-импортов в AudioConverter и WhisperManager.
STTWorker может импортировать только Signal/QThread из PySide6.
"""
