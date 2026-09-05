"""
core/components/manager.py — ComponentManager (COMPONENTS.md §5).

Находит установленные компоненты, качает недостающие, запускает их как
subprocess и разбирает результат.

Нет Qt-импортов. Чистый Python. Синхронный и блокирующий — вызывается
только из QThread-воркера, по той же схеме, что ParseWorker/ExportWorker.

Компонент для менеджера — чёрный ящик с одним входом: «вот файл задания,
положи результат в этот файл». Менеджер не знает ни про модели, ни про
картинки; всё, что он умеет, — довезти задание и вернуть разобранный JSON.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import queue
import shutil
import subprocess
import threading
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

from core.exceptions import (
    ComponentCancelled,
    ComponentIntegrityError,
    ComponentProtocolError,
    ComponentRunError,
    RegistryError,
)

logger = logging.getLogger(__name__)

# Версия CLI-протокола, которую понимает это приложение (COMPONENTS.md §4).
# Компонент с протоколом новее запускать нельзя: мы не знаем его формата
# результата и разберём его неверно, что хуже честного отказа.
PROTOCOL_VERSION = 1

# Маркер успешной установки. Создаётся ПОСЛЕДНИМ — после проверки sha256 и
# полной распаковки. Пока его нет, папка считается мусором от прерванной
# установки и может быть снесена без вопросов.
INSTALLED_MARKER = ".installed"

MANIFEST_NAME = "component.json"

_CHUNK = 1 << 20          # 1 МБ — компромисс между отзывчивостью и накладными
_REGISTRY_TIMEOUT = 15.0
_DOWNLOAD_TIMEOUT = 120.0

ProgressCb = Callable[[int, int], None]
CancelFlag = Callable[[], bool]


def _noop_progress(done: int, total: int) -> None:
    """Прогресс никого не интересует — обычный случай в тестах."""


def _never_cancelled() -> bool:
    return False


@dataclass(frozen=True)
class InstalledComponent:
    """
    Установленный компонент, найденный на диске.

    Attributes:
        name:       Имя компонента ("vlm").
        version:    Версия строкой, как в имени папки ("1.0.0").
        protocol:   Версия CLI-протокола из component.json.
        entry_path: Абсолютный путь к исполняемому файлу.
        root:       Папка версии — то, что нужно удалить при переустановке.
    """

    name:       str
    version:    str
    protocol:   int
    entry_path: Path
    root:       Path

    @property
    def is_runnable(self) -> bool:
        """
        Файл запуска на месте.

        Ложь здесь — не редкость: антивирусы вырезают .exe из папки, оставляя
        всё остальное. Установка при этом выглядит целой (маркер на месте),
        а запуск падает. Отличать этот случай нужно, чтобы предложить
        переустановку, а не показывать невнятную ошибку запуска.
        """
        return self.entry_path.is_file()


def _parse_version(version: str) -> tuple:
    """
    Версия для сравнения: "1.10.0" должна быть новее "1.9.0".

    Сравнение строк здесь врёт, поэтому раскладываем по числам. Нечисловые
    куски («1.0.0-rc1») сортируются после числовых той же длины — точность
    тут не нужна, нужен предсказуемый порядок.
    """
    parts: List[tuple] = []
    for chunk in str(version).split("."):
        if chunk.isdigit():
            parts.append((0, int(chunk), ""))
        else:
            head = ""
            for ch in chunk:
                if ch.isdigit():
                    head += ch
                else:
                    break
            parts.append((1, int(head) if head else 0, chunk))
    return tuple(parts)


class ComponentManager:
    """
    Установка и запуск загружаемых компонентов.

    Usage:
        cm = ComponentManager(Path("components"), REGISTRY_URL)
        comp = cm.get_installed("vlm")
        if comp is None:
            info = cm.fetch_registry()["components"]["vlm"]["versions"]["1.0.0"]
            cm.download("vlm", "1.0.0", info, progress_cb, cancel_flag)
            comp = cm.get_installed("vlm")
        result = cm.run(comp, {"task": "describe_images", ...})
    """

    def __init__(self, components_dir: Path | str, registry_url: str) -> None:
        self._dir = Path(components_dir)
        self._registry_url = registry_url

    # ── Поиск установленного ─────────────────────────────────────────────

    def get_installed(self, name: str) -> Optional[InstalledComponent]:
        """
        Ищет установленный компонент, возвращает самую свежую версию.

        Папки без маркера `.installed` игнорируются — это следы прерванной
        установки, а не рабочие версии.

        Returns:
            InstalledComponent или None, если ничего пригодного не найдено.
            Повреждённая установка (маркер есть, файла запуска нет) всё
            равно возвращается: вызывающий отличит её по `is_runnable` и
            предложит переустановку.
        """
        base = self._dir / name
        if not base.is_dir():
            return None

        found: List[InstalledComponent] = []
        for version_dir in base.iterdir():
            if not version_dir.is_dir():
                continue
            if not (version_dir / INSTALLED_MARKER).is_file():
                continue
            comp = self._read_manifest(name, version_dir)
            if comp is not None:
                found.append(comp)

        if not found:
            return None
        return max(found, key=lambda c: _parse_version(c.version))

    def _read_manifest(
        self, name: str, version_dir: Path,
    ) -> Optional[InstalledComponent]:
        """
        Читает component.json внутри папки версии.

        Манифест лежит рядом с файлом запуска, но на одну папку глубже —
        распаковка zip создаёт свой каталог. Поэтому ищем и там, и там.
        """
        candidates = [version_dir / MANIFEST_NAME]
        candidates += sorted(version_dir.glob(f"*/{MANIFEST_NAME}"))
        for manifest in candidates:
            if not manifest.is_file():
                continue
            try:
                data = json.loads(manifest.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                logger.warning("component.json не читается (%s): %s",
                               manifest, exc)
                continue
            entry = data.get("entry")
            if not entry:
                logger.warning("component.json без entry: %s", manifest)
                continue
            return InstalledComponent(
                name       = data.get("name") or name,
                version    = str(data.get("version") or version_dir.name),
                protocol   = int(data.get("protocol") or 0),
                entry_path = manifest.parent / entry,
                root       = version_dir,
            )
        return None

    # ── Реестр ───────────────────────────────────────────────────────────

    def fetch_registry(self) -> dict:
        """
        Скачивает components_registry.json.

        Raises:
            RegistryError: сеть недоступна, ответ не JSON, структура не та.
                Исключение наружу осознанно: молча вернуть пустой реестр
                значило бы показать «компонентов нет» вместо «нет сети».
        """
        try:
            req = urllib.request.Request(
                self._registry_url,
                headers={"User-Agent": "RozittaParser"},
            )
            with urllib.request.urlopen(req, timeout=_REGISTRY_TIMEOUT) as resp:
                raw = resp.read()
        except (urllib.error.URLError, OSError) as exc:
            raise RegistryError(
                f"Не удалось получить список компонентов: {exc}") from exc

        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise RegistryError(
                f"Список компонентов повреждён: {exc}") from exc

        if not isinstance(data, dict) or "components" not in data:
            raise RegistryError("В списке компонентов нет раздела components")
        return data

    def pick_version(self, registry: dict, name: str) -> tuple:
        """
        Выбирает версию компонента из реестра: (версия, описание).

        Берётся `latest`, а не максимальная из списка: реестр может нарочно
        держать latest на предыдущей версии, пока новая обкатывается.

        Raises:
            RegistryError: компонента нет в реестре, или latest указывает
                на версию, которой в versions не оказалось.
            ComponentProtocolError: версия требует протокол новее нашего.
        """
        entry = (registry.get("components") or {}).get(name)
        if not entry:
            raise RegistryError(f"Компонента «{name}» нет в списке")

        version = entry.get("latest")
        versions = entry.get("versions") or {}
        info = versions.get(version)
        if not info:
            raise RegistryError(
                f"Компонент «{name}»: версия {version} не описана в списке")

        protocol = int(info.get("protocol") or 0)
        if protocol > PROTOCOL_VERSION:
            raise ComponentProtocolError(
                f"Компонент «{name}» {version} требует более новую версию "
                f"Rozitta Parser (протокол {protocol}, поддерживается "
                f"{PROTOCOL_VERSION}). Обновите приложение."
            )
        return version, info

    # ── Скачивание и установка ───────────────────────────────────────────

    def download(
        self,
        name:        str,
        version:     str,
        info:        dict,
        progress_cb: ProgressCb = _noop_progress,
        cancel_flag: CancelFlag = _never_cancelled,
    ) -> Path:
        """
        Качает архив компонента, проверяет sha256, распаковывает.

        Маркер `.installed` создаётся последним. Всё, что упало или было
        отменено раньше, убирается за собой — на диске не остаётся
        полуустановленной версии, которую `get_installed()` потом примет
        за рабочую.

        Args:
            info: Запись версии из реестра: urls, sha256, size_bytes.
            progress_cb: Вызывается как (скачано, всего) в байтах.
            cancel_flag: Опрашивается между кусками; True — прервать.

        Returns:
            Путь к папке установленной версии.

        Raises:
            ComponentCancelled:       прервано пользователем.
            ComponentIntegrityError:  sha256 не совпал.
            ComponentError:           не удалось скачать ни с одного зеркала.
        """
        urls = list(info.get("urls") or [])
        if not urls:
            raise RegistryError(f"Компонент «{name}» {version}: нет ссылок")

        expected = (info.get("sha256") or "").lower().strip()
        target = self._dir / name / version

        tmp_fd, tmp_name = tempfile.mkstemp(suffix=".zip", prefix=f"{name}-")
        os.close(tmp_fd)
        tmp_path = Path(tmp_name)

        # Распаковываем в сторону и подменяем готовым — не поверх рабочей
        # версии. Иначе переустановка сначала сносит то, что работало, и при
        # первой же неудаче (кончился диск, битый архив) пользователь
        # остаётся без компонента вообще.
        staging = target.parent / f".{version}.new"

        try:
            self._download_to(urls, tmp_path, info, progress_cb, cancel_flag)
            if expected:
                self._verify(tmp_path, expected)
            self._extract(tmp_path, staging, cancel_flag)
            # Маркер пишется в подготовленную папку до подмены: после
            # переезда версия должна быть сразу целой, без промежуточного
            # состояния «файлы есть, маркера ещё нет».
            (staging / INSTALLED_MARKER).write_text(
                f"{name} {version}\n", encoding="utf-8")
            shutil.rmtree(target, ignore_errors=True)
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staging, target)
        except BaseException:
            # Прибираем и падение, и отмену. Рабочая версия при этом цела:
            # мы её ещё не трогали.
            shutil.rmtree(staging, ignore_errors=True)
            raise
        finally:
            tmp_path.unlink(missing_ok=True)

        logger.info("компонент %s %s установлен в %s", name, version, target)
        return target

    def _download_to(
        self,
        urls:        List[str],
        dest:        Path,
        info:        dict,
        progress_cb: ProgressCb,
        cancel_flag: CancelFlag,
    ) -> None:
        """Качает по первой рабочей ссылке; остальные — зеркала."""
        errors: List[str] = []
        for url in urls:
            try:
                self._stream(url, dest, info, progress_cb, cancel_flag)
                return
            except ComponentCancelled:
                raise
            except Exception as exc:
                logger.warning("зеркало не ответило (%s): %s", url, exc)
                errors.append(f"{url}: {exc}")
        raise RegistryError(
            "Не удалось скачать компонент ни по одной ссылке:\n"
            + "\n".join(errors))

    def _stream(
        self,
        url:         str,
        dest:        Path,
        info:        dict,
        progress_cb: ProgressCb,
        cancel_flag: CancelFlag,
    ) -> None:
        req = urllib.request.Request(
            url, headers={"User-Agent": "RozittaParser"})
        with urllib.request.urlopen(req, timeout=_DOWNLOAD_TIMEOUT) as resp:
            total = int(resp.headers.get("Content-Length")
                        or info.get("size_bytes") or 0)
            done = 0
            progress_cb(0, total)
            with open(dest, "wb") as fh:
                while True:
                    if cancel_flag():
                        raise ComponentCancelled("Скачивание отменено")
                    chunk = resp.read(_CHUNK)
                    if not chunk:
                        break
                    fh.write(chunk)
                    done += len(chunk)
                    progress_cb(done, total)

    @staticmethod
    def _verify(path: Path, expected_sha256: str) -> None:
        digest = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(_CHUNK), b""):
                digest.update(chunk)
        actual = digest.hexdigest()
        if actual != expected_sha256:
            raise ComponentIntegrityError(
                "Скачанный архив повреждён (контрольная сумма не совпала). "
                "Обычно помогает повторить загрузку."
            )

    @staticmethod
    def _extract(archive: Path, target: Path, cancel_flag: CancelFlag) -> None:
        """
        Распаковывает архив в папку версии, снеся прежнее содержимое.

        Пути из архива проверяются: zip умеет хранить «../» и абсолютные
        пути, и наивная распаковка вынесет файлы за пределы папки. Архив
        свой, но проверка стоит четырёх строк, а доверие — нет.
        """
        shutil.rmtree(target, ignore_errors=True)
        target.mkdir(parents=True, exist_ok=True)
        root = target.resolve()
        with zipfile.ZipFile(archive) as z:
            for member in z.namelist():
                if cancel_flag():
                    raise ComponentCancelled("Установка отменена")
                out = (target / member).resolve()
                if not str(out).startswith(str(root)):
                    raise ComponentIntegrityError(
                        f"Архив пытается записать файл за пределы папки: "
                        f"{member}")
            z.extractall(target)

    # ── Запуск ───────────────────────────────────────────────────────────

    def run(
        self,
        comp:        InstalledComponent,
        task:        dict,
        progress_cb: ProgressCb = _noop_progress,
        cancel_flag: CancelFlag = _never_cancelled,
        timeout_sec: Optional[float] = None,
    ) -> dict:
        """
        Запускает компонент с заданием и возвращает разобранный результат.

        Задание и результат ездят файлами, а не через stdout: кириллические
        пути и кодировки консоли Windows — минное поле, файлы UTF-8 надёжнее
        (COMPONENTS.md §4). Через stdout идёт только прогресс.

        Args:
            timeout_sec: Потолок на всё задание. None — без потолка.

        Returns:
            Содержимое result-файла как dict.

        Raises:
            ComponentProtocolError: компонент новее приложения.
            ComponentCancelled:     прервано пользователем.
            ComponentRunError:      не запустился, завис, упал или не оставил
                                    пригодного результата.
        """
        if comp.protocol > PROTOCOL_VERSION:
            raise ComponentProtocolError(
                f"Компонент «{comp.name}» {comp.version} требует более новую "
                f"версию Rozitta Parser (протокол {comp.protocol}). "
                f"Обновите приложение."
            )
        if not comp.is_runnable:
            raise ComponentRunError(
                f"Файл запуска компонента не найден: {comp.entry_path}. "
                f"Возможно, его удалил антивирус — переустановите компонент."
            )

        work = Path(tempfile.mkdtemp(prefix=f"rozitta-{comp.name}-"))
        task_path = work / "task.json"
        result_path = work / "result.json"
        payload = dict(task)
        payload.setdefault("protocol", PROTOCOL_VERSION)
        task_path.write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8")

        try:
            code = self._spawn(
                comp, task_path, result_path, progress_cb, cancel_flag,
                timeout_sec)
            return self._collect(comp, result_path, code)
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def _spawn(
        self,
        comp:        InstalledComponent,
        task_path:   Path,
        result_path: Path,
        progress_cb: ProgressCb,
        cancel_flag: CancelFlag,
        timeout_sec: Optional[float],
    ) -> int:
        cmd = [str(comp.entry_path),
               "--task", str(task_path),
               "--result", str(result_path)]
        logger.info("запуск компонента: %s", " ".join(cmd))

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(comp.entry_path.parent),
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        deadline = time.monotonic() + timeout_sec if timeout_sec else None

        # Читаем stdout отдельным потоком, а не циклом `for line in stdout`.
        # Цикл блокируется до появления строки — а зависший компонент строк
        # не выдаёт вовсе, и до проверки таймаута выполнение не дошло бы
        # ровно в том случае, ради которого таймаут и нужен.
        lines: "queue.Queue[Optional[str]]" = queue.Queue()

        def _pump() -> None:
            try:
                for raw in proc.stdout:
                    lines.put(raw)
            except Exception:                     # труба закрылась — не беда
                pass
            finally:
                lines.put(None)                   # признак конца потока

        reader = threading.Thread(target=_pump, daemon=True,
                                  name=f"comp-{comp.name}-stdout")
        reader.start()

        try:
            finished = False
            while not finished:
                try:
                    raw = lines.get(timeout=0.5)
                except queue.Empty:
                    raw = ""                      # тишина — просто идём дальше
                else:
                    if raw is None:
                        finished = True
                    else:
                        line = raw.strip()
                        if line.startswith("PROGRESS "):
                            self._emit_progress(line, progress_cb)
                        elif line:
                            logger.debug("[%s] %s", comp.name, line)

                if cancel_flag():
                    self._kill(proc)
                    raise ComponentCancelled("Обработка отменена")
                if deadline and time.monotonic() > deadline:
                    self._kill(proc)
                    raise ComponentRunError(
                        f"Компонент «{comp.name}» не уложился в "
                        f"{timeout_sec:.0f} с и был остановлен."
                    )
            code = proc.wait(timeout=30)
        finally:
            reader.join(timeout=5)
            stderr = ""
            if proc.stderr:
                try:
                    stderr = proc.stderr.read() or ""
                except Exception:
                    stderr = ""
            if stderr.strip():
                logger.info("stderr компонента %s:\n%s", comp.name,
                            stderr.strip())
            for stream in (proc.stdout, proc.stderr):
                if stream:
                    try:
                        stream.close()
                    except Exception:
                        pass
        return code

    @staticmethod
    def _emit_progress(line: str, progress_cb: ProgressCb) -> None:
        """
        Разбирает `PROGRESS <done> <total>`.

        Кривую строку молча пропускаем: прогресс — украшение, ронять из-за
        него уже сделанную работу нельзя.
        """
        parts = line.split()
        if len(parts) != 3:
            return
        try:
            progress_cb(int(parts[1]), int(parts[2]))
        except (TypeError, ValueError):
            pass

    @staticmethod
    def _kill(proc: subprocess.Popen) -> None:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

    @staticmethod
    def _collect(
        comp: InstalledComponent, result_path: Path, code: int,
    ) -> dict:
        """
        Разбирает результат по коду возврата (COMPONENTS.md §4).

        Код 2 — фатальная ошибка окружения, result-файла может не быть
        вовсе. Код 1 — ошибка задания, подробности внутри файла. Код 0
        без файла — поломка самого компонента: он отчитался успехом, не
        оставив результата, и это хуже честного ненулевого кода.
        """
        data: Optional[dict] = None
        if result_path.is_file():
            try:
                data = json.loads(result_path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise ComponentRunError(
                    f"Компонент «{comp.name}» оставил нечитаемый результат: "
                    f"{exc}"
                ) from exc

        if code == 0:
            if data is None:
                raise ComponentRunError(
                    f"Компонент «{comp.name}» отчитался успехом, но результата "
                    f"не оставил."
                )
            return data

        detail = ""
        if isinstance(data, dict) and data.get("error"):
            detail = f": {data['error']}"
        raise ComponentRunError(
            f"Компонент «{comp.name}» завершился с кодом {code}{detail}")
