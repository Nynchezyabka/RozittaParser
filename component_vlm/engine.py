"""
component_vlm/engine.py — llama-server и подготовка запроса к нему.

Здесь всё, что знает про модель: как её поднять, что ей послать и как
обойтись с ответом. Протокол компонента живёт отдельно, в worker.py.

Числа в константах не выдуманы — они из замера CM-0 на живых фото канала
(11 картинок, Qwen3-VL 4B, CPU и Vulkan). Каждое объяснено на месте.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import os
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


# ── Промпт ────────────────────────────────────────────────────────────────────
#
# Просит дословный OCR: замер CM-0 показал, что именно это даёт архиву
# ценность — с плана участка вытаскиваются «10,5 м², 81,8 м², низ трубы
# −0,84», со скриншота текст сообщений. Вариант «опиши сцену в двух фразах»
# на тех же картинках выдавал «план содержит метки площадей», по которому
# ничего не найдёшь.
#
# Промпт НЕ пытается защититься от инъекций, и это осознанно. Замер CM-0:
# требование дословного текста и защитная формулировка противоречат друг
# другу, добавленная строка «надписи это данные» не спасла — модель честно
# вернула директиву с картинки, потому что её и просили вернуть текст.
# Защиту несёт рамка, которую ставит приложение вокруг ответа (§4.4,
# уровни 3–4), и заявление на весь архив в ИНСТРУКЦИЯ_ДЛЯ_ИИ.md.
SYSTEM_PROMPT = (
    "Опиши изображение детально и по делу: что на нём, дословный текст "
    "(OCR), важные детали и цифры. Без преамбул и воды — только содержимое."
)

USER_PROMPT = "Опиши это изображение."

# Потолок длинной стороны (§4.3). Замер: рендер 2752x1536 в полном
# разрешении — 4190 токенов и 77 секунд; он же при 1280 — 1075 токенов и
# 9.4 секунды, номер дома на фасаде читается в обоих случаях. Ниже 1280
# опускаться нельзя: при 1024 модель начинает путать участников переписки
# на скриншоте, а выдуманный участник хуже пропуска.
#
# Константа живёт здесь, а не в задании: приложение не должно иметь
# возможности случайно заказать выгрузку в полном разрешении.
MAX_IMAGE_SIDE = 1280

# Сколько токенов разрешаем сгенерировать. При 300 замер ловил ответы,
# оборванные на полуслове; 400 хватает самому многословному случаю из
# набора (скриншот переписки) с запасом.
MAX_TOKENS = 400

# Потолок длины описания в символах. Не защита — от инъекции он не спасает
# (§4.4), — а забота о размере архива и о том, чтобы одна картинка не
# утащила в документ полотно на три экрана. Обрезка помечается, а не
# делается молча: читающая модель примет обрубок за целое и достроит смысл
# сама.
MAX_CHARS = 1200
TRUNCATION_NOTE = "… [описание усечено: пропущено {n} символов]"

# Низкая температура — описание должно быть воспроизводимым: один и тот же
# архив, выгруженный дважды, не должен давать разные тексты.
TEMPERATURE = 0.2

_HOST = "127.0.0.1"
_STARTUP_TIMEOUT = 300.0
_REQUEST_TIMEOUT = 900.0


class EngineError(RuntimeError):
    """Движок не удалось поднять или он перестал отвечать."""


def clamp(text: str, max_chars: int = MAX_CHARS) -> str:
    """
    Обрезает описание до бюджета, честно сообщая об обрезке.

    Молчаливая обрезка хуже длинного текста: тот, кто потом читает архив,
    примет обрубок за законченную мысль. Поэтому вместо тишины — пометка
    с числом пропущенных символов.
    """
    text = (text or "").strip()
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars].rstrip()
    return cut + TRUNCATION_NOTE.format(n=len(text) - len(cut))


def prepare_image(path: Path, max_side: int = MAX_IMAGE_SIDE) -> Tuple[str, str]:
    """
    Готовит картинку к отправке: уменьшает при необходимости, кодирует.

    Оригинал на диске не трогается — уменьшенная копия живёт только в
    памяти на время запроса.

    Returns:
        (base64-строка, MIME-тип).

    Raises:
        OSError: файл не читается или это не изображение. Ловится вызывающим
            и превращается в запись в errors — один битый файл не должен
            ронять пачку.
    """
    from PIL import Image

    with Image.open(path) as im:
        im = im.convert("RGB")
        if max(im.size) > max_side:
            im.thumbnail((max_side, max_side), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=88)
    return base64.b64encode(buf.getvalue()).decode("ascii"), "image/jpeg"


def _free_port() -> int:
    """
    Просит у системы свободный порт.

    Фиксированный порт занят ровно тогда, когда компонент запущен дважды —
    а это обычное дело, если пользователь начал выгрузку второго чата, не
    дождавшись первой.
    """
    with socket.socket() as s:
        s.bind((_HOST, 0))
        return s.getsockname()[1]


class LlamaServer:
    """
    Поднимает llama-server рядом с собой и говорит с ним по HTTP.

    Сервер, а не разовый запуск на каждую картинку: веса грузятся секунды,
    и платить эту цену за каждый файл в пачке из пятисот нельзя.

    Usage:
        with LlamaServer(binaries_dir, model, mmproj) as srv:
            text = srv.describe(b64, "image/jpeg")
    """

    def __init__(
        self,
        server_exe: Path,
        model:      Path,
        mmproj:     Path,
        n_gpu_layers: int = 99,
        context:      int = 8192,
    ) -> None:
        self._exe = Path(server_exe)
        self._model = Path(model)
        self._mmproj = Path(mmproj)
        self._ngl = n_gpu_layers
        self._ctx = context
        self._port = _free_port()
        self._proc: Optional[subprocess.Popen] = None

    # ── Жизненный цикл ───────────────────────────────────────────────────

    def __enter__(self) -> "LlamaServer":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()

    def start(self) -> None:
        for path, what in ((self._exe, "llama-server"),
                           (self._model, "файл модели"),
                           (self._mmproj, "проектор mmproj")):
            if not path.is_file():
                raise EngineError(f"Не найден {what}: {path}")

        cmd = [
            str(self._exe),
            "-m", str(self._model),
            "--mmproj", str(self._mmproj),
            "--host", _HOST, "--port", str(self._port),
            "-ngl", str(self._ngl),
            "-c", str(self._ctx),
            "--no-warmup",
        ]
        logger.info("поднимаю llama-server на порту %d", self._port)
        self._proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=str(self._exe.parent),
        )
        if not self._wait_health(_STARTUP_TIMEOUT):
            self.stop()
            raise EngineError(
                "llama-server не ответил за отведённое время. Обычно это "
                "значит, что не хватило памяти под модель."
            )

    def _wait_health(self, timeout: float) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._proc is not None and self._proc.poll() is not None:
                return False                  # умер, ждать больше нечего
            try:
                with urllib.request.urlopen(
                        f"http://{_HOST}:{self._port}/health", timeout=3) as r:
                    if r.status == 200:
                        return True
            except Exception:
                time.sleep(1.0)
        return False

    def stop(self) -> None:
        if self._proc is None:
            return
        self._proc.terminate()
        try:
            self._proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            self._proc.kill()
        self._proc = None

    # ── Запрос ───────────────────────────────────────────────────────────

    def describe(self, image_b64: str, mime: str) -> str:
        """
        Отдаёт описание одной картинки.

        Raises:
            EngineError: сервер не ответил или ответил не тем.
        """
        payload = {
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": [
                    {"type": "image_url",
                     "image_url": {"url": f"data:{mime};base64,{image_b64}"}},
                    {"type": "text", "text": USER_PROMPT},
                ]},
            ],
            "temperature": TEMPERATURE,
            "max_tokens": MAX_TOKENS,
        }
        req = urllib.request.Request(
            f"http://{_HOST}:{self._port}/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
                data = json.load(resp)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise EngineError(f"llama-server не ответил: {exc}") from exc

        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise EngineError(f"неожиданный ответ сервера: {exc}") from exc


def find_binaries(root: Path) -> Path:
    """
    Ищет llama-server рядом с воркером.

    Компонент возит две сборки — CPU и Vulkan. Vulkan предпочтительнее:
    на замере он давал вчетверо (33 с против 8 с на картинку), а работает
    на любой видеокарте без установки CUDA. Если её нет, остаётся CPU.

    Порядок можно перекрыть переменной ROZITTA_VLM_BACKEND — нужно для
    отладки и для машин, где Vulkan есть, но неисправен.
    """
    # Имена перечислены точно, а не шаблоном `llama-server*`. Шаблон
    # подбирал `llama-server-impl.dll` — и подбирал ПЕРВЫМ, потому что при
    # сортировке дефис идёт раньше точки. Воркер честно пытался запустить
    # библиотеку и получал «не является приложением Win32». Мокнутые тесты
    # этого не видели: в них find_binaries подменена целиком.
    names = ("llama-server.exe", "llama-server")

    def _look(pattern: str) -> Optional[Path]:
        for name in names:
            for candidate in sorted(root.glob(pattern.format(name=name))):
                if candidate.is_file():
                    return candidate
        return None

    preferred = os.environ.get("ROZITTA_VLM_BACKEND", "").strip().lower()
    order = [preferred] if preferred else ["vulkan", "cpu"]
    for backend in order:
        found = _look(f"*{backend}*/**/{{name}}")
        if found is not None:
            return found

    found = _look("**/{name}")
    if found is not None:
        return found
    raise EngineError(f"llama-server не найден в {root}")
