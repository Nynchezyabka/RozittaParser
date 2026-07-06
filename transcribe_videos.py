#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
transcribe_videos.py — разовый скрипт транскрибации видео мастер-группы в Markdown.

НЕ является частью Rozitta Parser. Отдельный инструмент для этапа 0 (подготовка
корпуса для RAG / AnythingLLM).

Что делает:
  - Берёт все видео/аудио из входной папки
  - Распознаёт речь через faster-whisper (один говорящий, диаризация не нужна)
  - На каждый файл создаёт один .md:
      * имя MD = имя исходного файла
      * первая строка: "# <имя файла>"  (страховка для RAG-чанков)
      * опционально таймкоды **[MM:SS]** каждые 5 минут (--timecodes)
  - Уже готовые .md пропускает (можно безопасно перезапускать, гонять партиями по ночам)
  - Пишет во временный .part и переименовывает по завершении (защита от обрыва)

Установка (один раз):
    pip install faster-whisper

Примеры:
    python transcribe_videos.py "D:/МастерГруппа/видео"
    python transcribe_videos.py ./videos --output ./md --model medium --timecodes
    python transcribe_videos.py ./videos --prompt "Мастер-группа по психологии. Автор: Имя Фамилия."

Модель скачается автоматически при первом запуске (кэш HuggingFace).
Ориентир скорости на CPU: large-v3-turbo ~ реальное время; medium быстрее, но грубее.
"""

import argparse
import sys
import time
from pathlib import Path

MEDIA_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".mp3",
              ".m4a", ".wav", ".ogg", ".opus", ".flac", ".aac"}

TIMECODE_STEP = 300  # секунд между метками при --timecodes (5 минут)


def pick_device() -> tuple[str, str]:
    """Выбор устройства: CUDA, если доступна, иначе CPU."""
    try:
        from ctranslate2 import get_cuda_device_count
        if get_cuda_device_count() > 0:
            return "cuda", "float16"
    except Exception:
        pass
    return "cpu", "int8"


def fmt_ts(seconds: float) -> str:
    """1234.5 -> '20:34' (или '1:05:12' если больше часа)."""
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def transcribe_file(model, src: Path, dst: Path, *,
                    language: str, prompt: str | None, timecodes: bool) -> bool:
    """Транскрибирует один файл. Возвращает True при успехе."""
    tmp = dst.with_suffix(dst.suffix + ".part")
    t0 = time.monotonic()

    segments, info = model.transcribe(
        str(src),
        language=language,
        vad_filter=True,                    # режет тишину, лечит галлюцинации
        beam_size=5,
        condition_on_previous_text=False,   # защита от зацикливания на длинных записях
        initial_prompt=prompt,
    )
    duration = info.duration or 0.0
    print(f"  длительность: {fmt_ts(duration)}, язык: {info.language} "
          f"(p={info.language_probability:.2f})")

    next_mark = 0.0
    last_pct = -1
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(f"# {src.stem}\n\n")
        for seg in segments:
            if timecodes and seg.start >= next_mark:
                f.write(f"\n**[{fmt_ts(seg.start)}]**\n\n")
                next_mark = seg.start - (seg.start % TIMECODE_STEP) + TIMECODE_STEP
            f.write(seg.text.strip() + "\n")

            if duration > 0:
                pct = int(seg.end / duration * 100)
                if pct >= last_pct + 5:
                    last_pct = pct
                    elapsed = time.monotonic() - t0
                    print(f"  ... {pct:3d}%  ({fmt_ts(elapsed)} затрачено)", flush=True)

    tmp.replace(dst)
    print(f"  готово за {fmt_ts(time.monotonic() - t0)} → {dst.name}")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Транскрибация видео/аудио в Markdown (faster-whisper, один говорящий).")
    ap.add_argument("input_dir", help="Папка с видео/аудио файлами")
    ap.add_argument("--output", default=None,
                    help="Папка для .md (по умолчанию: <input_dir>/transcripts)")
    ap.add_argument("--model", default="large-v3-turbo",
                    help="Модель: tiny/base/small/medium/large-v3/large-v3-turbo "
                         "(по умолчанию large-v3-turbo)")
    ap.add_argument("--language", default="ru", help="Язык речи (по умолчанию ru)")
    ap.add_argument("--prompt", default=None,
                    help="initial_prompt: имена, термины методики — улучшает их написание")
    ap.add_argument("--timecodes", action="store_true",
                    help="Вставлять метки **[MM:SS]** каждые 5 минут")
    args = ap.parse_args()

    src_dir = Path(args.input_dir)
    if not src_dir.is_dir():
        print(f"Ошибка: папка не найдена: {src_dir}")
        return 1
    out_dir = Path(args.output) if args.output else src_dir / "transcripts"
    out_dir.mkdir(parents=True, exist_ok=True)

    files = sorted(p for p in src_dir.iterdir()
                   if p.is_file() and p.suffix.lower() in MEDIA_EXTS)
    if not files:
        print(f"В папке {src_dir} нет медиафайлов ({', '.join(sorted(MEDIA_EXTS))})")
        return 1

    todo = [p for p in files if not (out_dir / (p.stem + ".md")).exists()]
    print(f"Найдено файлов: {len(files)}, уже готово: {len(files) - len(todo)}, "
          f"в очереди: {len(todo)}")
    if not todo:
        print("Всё уже транскрибировано.")
        return 0

    device, compute_type = pick_device()
    print(f"Устройство: {device} ({compute_type}), модель: {args.model}")
    print("Загрузка модели (при первом запуске — скачивание)...")
    from faster_whisper import WhisperModel
    model = WhisperModel(args.model, device=device, compute_type=compute_type)

    ok, failed = 0, []
    for i, src in enumerate(todo, 1):
        print(f"\n[{i}/{len(todo)}] {src.name}")
        try:
            transcribe_file(model, src, out_dir / (src.stem + ".md"),
                            language=args.language, prompt=args.prompt,
                            timecodes=args.timecodes)
            ok += 1
        except KeyboardInterrupt:
            print("\nПрервано пользователем. Уже готовые файлы сохранены, "
                  "перезапуск продолжит с места остановки.")
            break
        except Exception as e:
            print(f"  ОШИБКА: {e}")
            print("  Подсказка: если файл не декодируется — проверьте кодек; "
                  "можно предварительно извлечь аудио: "
                  f'ffmpeg -i "{src.name}" -ac 1 -ar 16000 "{src.stem}.wav"')
            failed.append(src.name)

    print(f"\nИтог: успешно {ok}, ошибок {len(failed)}")
    if failed:
        print("Не обработаны: " + ", ".join(failed))
    return 0 if not failed else 2


if __name__ == "__main__":
    sys.exit(main())
