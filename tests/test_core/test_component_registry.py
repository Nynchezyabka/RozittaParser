# -*- coding: utf-8 -*-
"""
tests/test_core/test_component_registry.py — сборщик реестра (CM-4).

Реестр это контракт между приложением и компонентом (COMPONENTS.md §3.1).
Ошибка в нём даёт неверный sha256, и установка отказывает у всех разом —
причём молча, «архив повреждён», без намёка на то, что виноват не архив.
Поэтому проверяется не «скрипт отработал», а что получившийся реестр
действительно принимается ComponentManager'ом.
"""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from core.components.manager import ComponentManager

SCRIPT = Path("tools/make_component_registry.py")


def run_tool(*args) -> subprocess.CompletedProcess:
    """
    Запускает инструмент отдельным процессом.

    PYTHONIOENCODING обязателен: без него дочерний Python пишет русский
    текст в кодировке консоли Windows (cp1251), а мы читаем как UTF-8 —
    и все сообщения об ошибках превращаются в «???». Тесты на текст
    сообщений при этом краснеют, а причина выглядит как что угодно, кроме
    настоящей.
    """
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    return subprocess.run(
        [sys.executable, str(SCRIPT), *[str(a) for a in args]],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=env,
    )


@pytest.fixture
def files(tmp_path):
    """Архив компонента и три файла весов, как их выложил бы workflow."""
    zip_path = tmp_path / "RozittaVLM-win64-1.0.0.zip"
    zip_path.write_bytes(b"pretend this is a zip" * 100)

    weights = tmp_path / "weights"
    weights.mkdir()
    for name, size in (
        ("Qwen3VL-4B-00001-of-00002.gguf", 5000),
        ("Qwen3VL-4B-00002-of-00002.gguf", 3000),
        ("mmproj-Qwen3VL-4B-Instruct-Q8_0.gguf", 1000),
    ):
        (weights / name).write_bytes(b"w" * size)
    return zip_path, weights


class TestFreshBuild:
    def test_registry_is_accepted_by_the_manager(self, files, tmp_path):
        """
        Главная проверка: реестр не просто собрался, а годен к употреблению.

        Тест ходит тем же путём, что приложение, — fetch_registry() плюс
        pick_version(). Проверять только форму JSON значило бы оставить
        нетронутым как раз тот стык, где ошибка стоит дороже всего.
        """
        zip_path, weights = files
        out = tmp_path / "components_registry.json"
        res = run_tool("--name", "vlm", "--version", "1.0.0",
                       "--zip", zip_path, "--zip-url", "https://ex/z.zip",
                       "--weights-dir", weights, "--weights-base", "https://ex/w",
                       "--out", out)
        assert res.returncode == 0, res.stderr

        cm = ComponentManager(tmp_path / "components", out.as_uri())
        version, info = cm.pick_version(cm.fetch_registry(), "vlm")
        assert version == "1.0.0"
        assert info["sha256"] == hashlib.sha256(zip_path.read_bytes()).hexdigest()
        assert len(info["models"]) == 3

    def test_checksums_match_the_real_files(self, files, tmp_path):
        """
        Неверный sha256 ломает установку у всех сразу, и сообщение при этом
        обвиняет архив, а не реестр. Проверяем побайтово.
        """
        zip_path, weights = files
        out = tmp_path / "r.json"
        run_tool("--name", "vlm", "--version", "1.0.0",
                 "--zip", zip_path, "--zip-url", "https://ex/z.zip",
                 "--weights-dir", weights, "--weights-base", "https://ex/w",
                 "--out", out)
        reg = json.loads(out.read_text(encoding="utf-8"))
        models = reg["components"]["vlm"]["versions"]["1.0.0"]["models"]
        for entry in models:
            real = weights / entry["file"]
            assert entry["sha256"] == hashlib.sha256(real.read_bytes()).hexdigest()
            assert entry["size_bytes"] == real.stat().st_size

    def test_urls_point_at_the_release(self, files, tmp_path):
        zip_path, weights = files
        out = tmp_path / "r.json"
        run_tool("--name", "vlm", "--version", "1.0.0",
                 "--zip", zip_path, "--zip-url", "https://ex/comp/z.zip",
                 "--weights-dir", weights,
                 "--weights-base", "https://ex/weights-1",
                 "--out", out)
        reg = json.loads(out.read_text(encoding="utf-8"))
        v = reg["components"]["vlm"]["versions"]["1.0.0"]
        assert v["urls"] == ["https://ex/comp/z.zip"]
        for entry in v["models"]:
            assert entry["urls"][0].startswith("https://ex/weights-1/")
            assert entry["urls"][0].endswith(entry["file"])

    def test_output_is_reproducible(self, files, tmp_path):
        """
        Два прогона на одних файлах дают побайтово одинаковый реестр — иначе
        diff при обновлении показывает шум вместо настоящих изменений.
        """
        zip_path, weights = files
        a, b = tmp_path / "a.json", tmp_path / "b.json"
        for out in (a, b):
            run_tool("--name", "vlm", "--version", "1.0.0",
                     "--zip", zip_path, "--zip-url", "https://ex/z.zip",
                     "--weights-dir", weights, "--weights-base", "https://ex/w",
                     "--out", out)
        assert a.read_bytes() == b.read_bytes()


class TestCarryingWeightsOver:
    """
    Веса весят три гигабайта и меняются редко, сборка — тридцать мегабайт и
    меняется часто. Обычный выпуск не пересобирает веса, а переносит их
    описание. Без этого правка бинарника означала бы перезалив 3 ГБ.
    """

    def test_weights_survive_a_new_build(self, files, tmp_path):
        zip_path, weights = files
        first = tmp_path / "first.json"
        run_tool("--name", "vlm", "--version", "1.0.0",
                 "--zip", zip_path, "--zip-url", "https://ex/z1.zip",
                 "--weights-dir", weights, "--weights-base", "https://ex/w",
                 "--out", first)

        second = tmp_path / "second.json"
        res = run_tool("--name", "vlm", "--version", "1.0.1",
                       "--zip", zip_path, "--zip-url", "https://ex/z2.zip",
                       "--previous", first, "--out", second)
        assert res.returncode == 0, res.stderr

        old = json.loads(first.read_text(encoding="utf-8"))
        new = json.loads(second.read_text(encoding="utf-8"))
        assert new["components"]["vlm"]["latest"] == "1.0.1"
        assert (new["components"]["vlm"]["versions"]["1.0.1"]["models"]
                == old["components"]["vlm"]["versions"]["1.0.0"]["models"])
        # А ссылка на сборку — уже новая.
        assert new["components"]["vlm"]["versions"]["1.0.1"]["urls"] \
            == ["https://ex/z2.zip"]

    def test_missing_previous_is_survivable(self, files, tmp_path):
        """Первая публикация: прежнего реестра нет, и это не сбой."""
        zip_path, _ = files
        out = tmp_path / "r.json"
        res = run_tool("--name", "vlm", "--version", "1.0.0",
                       "--zip", zip_path, "--zip-url", "https://ex/z.zip",
                       "--previous", tmp_path / "нет.json", "--out", out)
        assert res.returncode == 0
        assert "нет описания весов" in res.stderr

    def test_warns_loudly_when_weights_are_absent(self, files, tmp_path):
        """
        Реестр без весов установится, но компонент не заработает: воркер не
        найдёт модель и вернёт код 2. Скрипт обязан сказать об этом.
        """
        zip_path, _ = files
        out = tmp_path / "r.json"
        res = run_tool("--name", "vlm", "--version", "1.0.0",
                       "--zip", zip_path, "--zip-url", "https://ex/z.zip",
                       "--out", out)
        assert "внимание" in res.stderr.lower()


class TestRefusals:
    def test_missing_zip(self, tmp_path):
        res = run_tool("--name", "vlm", "--version", "1.0.0",
                       "--zip", tmp_path / "нет.zip", "--zip-url", "https://x",
                       "--out", tmp_path / "r.json")
        assert res.returncode != 0
        assert "нет архива" in res.stderr

    def test_weights_dir_without_base_url(self, files, tmp_path):
        """
        Без базового адреса ссылки получились бы битыми, а заметили бы это
        только у пользователя при скачивании.
        """
        zip_path, weights = files
        res = run_tool("--name", "vlm", "--version", "1.0.0",
                       "--zip", zip_path, "--zip-url", "https://x",
                       "--weights-dir", weights, "--out", tmp_path / "r.json")
        assert res.returncode != 0
        assert "weights-base" in res.stderr

    def test_empty_weights_dir(self, files, tmp_path):
        zip_path, _ = files
        empty = tmp_path / "пусто"
        empty.mkdir()
        res = run_tool("--name", "vlm", "--version", "1.0.0",
                       "--zip", zip_path, "--zip-url", "https://x",
                       "--weights-dir", empty, "--weights-base", "https://w",
                       "--out", tmp_path / "r.json")
        assert res.returncode != 0
        assert "нет .gguf" in res.stderr


class TestProtocolField:
    def test_protocol_is_written(self, files, tmp_path):
        """
        Протокол в реестре — то, по чему приложение отказывается запускать
        компонент новее себя. Забыть его значит снять эту защиту.
        """
        zip_path, weights = files
        out = tmp_path / "r.json"
        run_tool("--name", "vlm", "--version", "1.0.0", "--protocol", "1",
                 "--zip", zip_path, "--zip-url", "https://x",
                 "--weights-dir", weights, "--weights-base", "https://w",
                 "--out", out)
        reg = json.loads(out.read_text(encoding="utf-8"))
        assert reg["components"]["vlm"]["versions"]["1.0.0"]["protocol"] == 1

    def test_newer_protocol_is_refused_by_the_manager(self, files, tmp_path):
        """Сквозная проверка: реестр с чужим протоколом менеджер отвергает."""
        from core.exceptions import ComponentProtocolError

        zip_path, weights = files
        out = tmp_path / "r.json"
        run_tool("--name", "vlm", "--version", "1.0.0", "--protocol", "99",
                 "--zip", zip_path, "--zip-url", "https://x",
                 "--weights-dir", weights, "--weights-base", "https://w",
                 "--out", out)
        cm = ComponentManager(tmp_path / "c", out.as_uri())
        with pytest.raises(ComponentProtocolError, match="Обновите"):
            cm.pick_version(cm.fetch_registry(), "vlm")
