"""
component_vlm/worker.py — точка входа компонента (COMPONENTS.md §4).

    RozittaVLM.exe --task задание.json --result результат.json

Задание и результат — файлы UTF-8: пути с кириллицей и кодировки консоли
Windows делают stdout ненадёжным каналом для данных. Через stdout идёт
только прогресс, по строке на картинку.

Коды возврата:
    0 — успех, result-файл записан;
    1 — ошибка задания (подробности в result-файле, поле error);
    2 — фатальная ошибка окружения (result-файла может не быть).

Одна битая картинка не роняет пачку: она получает null в descriptions и
запись в errors. Ронять двести описаний из-за одного повреждённого файла
значило бы заставить пользователя гадать, какой именно.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

if __package__ in (None, ""):                  # запуск как скрипта из exe
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from component_vlm.engine import (  # noqa: E402
    EngineError,
    LlamaServer,
    clamp,
    find_binaries,
    prepare_image,
)

PROTOCOL_VERSION = 1

EXIT_OK = 0
EXIT_TASK_ERROR = 1
EXIT_FATAL = 2

# Имена весов, которые компонент ожидает найти в своей папке models/.
# Решение CM-0: Qwen3-VL 4B в Q4_K_M, проектор Q8_0 — тот же счёт, что у
# F16, на полсекунды быстрее и на 390 МБ легче.
# Модель публикуется разбитой: у GitHub предел 2 ГиБ на файл в релизе,
# а она весит 2497 МБ (§3.1.1). Серверу отдаётся первый кусок — остальные
# llama.cpp находит сам по имени.
MODEL_FILES = {
    "base": ("Qwen3VL-4B-00001-of-00002.gguf",
             "mmproj-Qwen3VL-4B-Instruct-Q8_0.gguf"),
}

logger = logging.getLogger("rozitta.vlm")


def _default_root() -> Path:
    """
    Папка компонента: рядом с ней лежат бинарники llama.cpp и веса.

    В собранном виде считать её от `__file__` нельзя: PyInstaller кладёт
    модули внутрь `_internal`, и путь уезжает на уровень глубже, чем нужно.
    У замороженной программы честный ориентир один — сам исполняемый файл.

    ROZITTA_VLM_ROOT перекрывает оба случая: без него воркер нельзя было бы
    прогнать из репозитория против настоящей модели, и обещание «работает»
    осталось бы непроверенным до самой сборки.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


_MODELS_SEARCH_DEPTH = 3


def _find_models_dir(root: Path, model_file: str) -> Path:
    """
    Ищет папку `models` с нужным файлом, поднимаясь от root вверх.

    Считать уровни было ошибкой: в бою раскладка
    `components/vlm/1.0.0/RozittaVLM/` кладёт веса на ДВА уровня выше
    воркера, а не на один, — и первая сборка честно упала, не найдя их.
    Подъём вверх переживает и эту раскладку, и отладочную, где веса лежат
    прямо рядом.

    Returns:
        Первую подходящую папку. Если ничего не нашлось — `root/models`:
        пусть ошибка назовёт ожидаемое место, а не самое дальнее.
    """
    for level in [root] + list(root.parents)[:_MODELS_SEARCH_DEPTH]:
        candidate = level / "models"
        if (candidate / model_file).is_file():
            return candidate
    return root / "models"


def _progress(done: int, total: int) -> None:
    """Строка прогресса в stdout — единственное, что туда пишется."""
    print(f"PROGRESS {done} {total}", flush=True)


def _write_result(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                    encoding="utf-8")


def _fail(result_path: Optional[Path], message: str, code: int) -> int:
    logger.error(message)
    if result_path is not None:
        try:
            _write_result(result_path, {"protocol": PROTOCOL_VERSION,
                                        "ok": False, "error": message})
        except OSError as exc:
            logger.error("не удалось записать result-файл: %s", exc)
    return code


def describe_images(
    images:   List[str],
    root:     Path,
    model:    str = "base",
) -> dict:
    """
    Описывает пачку картинок. Сервер поднимается один раз на всю пачку.

    Returns:
        Словарь результата по §4.2: descriptions, errors, model, elapsed_sec.

    Raises:
        EngineError: движок не поднялся — это фатально для всей пачки,
            в отличие от ошибки на отдельном файле.
    """
    names = MODEL_FILES.get(model)
    if names is None:
        raise EngineError(f"неизвестная модель: {model}")
    model_file, mmproj_file = names

    models_dir = _find_models_dir(root, model_file)
    server_exe = find_binaries(root)

    descriptions: Dict[str, Optional[str]] = {}
    errors: Dict[str, str] = {}
    started = time.time()
    total = len(images)
    _progress(0, total)

    with LlamaServer(server_exe,
                     models_dir / model_file,
                     models_dir / mmproj_file) as srv:
        for done, raw_path in enumerate(images, start=1):
            path = Path(raw_path)
            try:
                image_b64, mime = prepare_image(path)
                text = clamp(srv.describe(image_b64, mime))
                descriptions[raw_path] = text or None
                if not text:
                    errors[raw_path] = "модель вернула пустое описание"
            except EngineError:
                raise                      # движок умер — пачку не спасти
            except Exception as exc:       # битый файл, не картинка, нет прав
                logger.warning("пропускаю %s: %s", path, exc)
                descriptions[raw_path] = None
                errors[raw_path] = str(exc)
            _progress(done, total)

    return {
        "protocol":     PROTOCOL_VERSION,
        "ok":           True,
        "descriptions": descriptions,
        "errors":       errors,
        "model":        model,
        "elapsed_sec":  round(time.time() - started, 1),
    }


def main(argv: Optional[List[str]] = None) -> int:
    logging.basicConfig(
        level=logging.INFO, stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--task", required=True)
    parser.add_argument("--result", required=True)
    args = parser.parse_args(argv)

    result_path = Path(args.result)

    try:
        task = json.loads(Path(args.task).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return _fail(result_path, f"задание не читается: {exc}",
                     EXIT_TASK_ERROR)

    protocol = int(task.get("protocol") or 0)
    if protocol > PROTOCOL_VERSION:
        return _fail(result_path,
                     f"задание на протоколе {protocol}, компонент понимает "
                     f"{PROTOCOL_VERSION}", EXIT_TASK_ERROR)

    if task.get("task") != "describe_images":
        return _fail(result_path,
                     f"неизвестное задание: {task.get('task')!r}",
                     EXIT_TASK_ERROR)

    images = task.get("images") or []
    if not images:
        return _fail(result_path, "в задании нет картинок", EXIT_TASK_ERROR)

    root = Path(os.environ.get("ROZITTA_VLM_ROOT") or _default_root())
    try:
        payload = describe_images(images, root, task.get("model") or "base")
    except EngineError as exc:
        # Движок — часть окружения: нет весов, не хватило памяти, нет
        # бинарника. Задание тут ни при чём, поэтому код 2, а не 1.
        return _fail(result_path, f"движок недоступен: {exc}", EXIT_FATAL)
    except Exception as exc:                       # noqa: BLE001
        logger.exception("непредвиденный сбой")
        return _fail(result_path, f"непредвиденный сбой: {exc}", EXIT_FATAL)

    try:
        _write_result(result_path, payload)
    except OSError as exc:
        return _fail(None, f"не удалось записать результат: {exc}", EXIT_FATAL)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
