# -*- coding: utf-8 -*-
"""
tests/test_core/test_components.py — ComponentManager (CM-1, COMPONENTS.md §5).

Сети здесь нет. Реестр подаётся через `file://`, архивы собираются на месте,
а «компонент» — крошечный python-скрипт, запускаемый тем же интерпретатором,
что и тесты. Этого хватает, чтобы проверить весь протокол §4 по-настоящему:
задание уезжает файлом, прогресс приходит строками, результат читается из
файла, коды возврата разбираются.

Отдельная забота — краевые случаи из §6. Они и есть причина, по которой
менеджер вообще нужен: без них хватило бы трёх строк с subprocess.run.
"""
import hashlib
import json
import os
import sys
import textwrap
import zipfile
from pathlib import Path

import pytest

from core.components.manager import (
    INSTALLED_MARKER,
    PROTOCOL_VERSION,
    ComponentManager,
)
from core.exceptions import (
    ComponentCancelled,
    ComponentIntegrityError,
    ComponentProtocolError,
    ComponentRunError,
    RegistryError,
)


# ──────────────────────────────────────────────────────────────────────────────
# Помощники: собираем настоящий компонент, а не мок
# ──────────────────────────────────────────────────────────────────────────────

def _worker_source(body: str) -> str:
    """
    Тело воркера, говорящего на протоколе §4.

    `body` получает переменные task (dict), result_path (Path) и обязан
    завершиться sys.exit(<код>).
    """
    return textwrap.dedent(f"""
        import json, sys, time
        from pathlib import Path

        args = sys.argv[1:]
        task_path = Path(args[args.index("--task") + 1])
        result_path = Path(args[args.index("--result") + 1])
        task = json.loads(task_path.read_text(encoding="utf-8"))

{textwrap.indent(textwrap.dedent(body), " " * 8)}
    """)


def make_component(
    root: Path,
    name: str = "vlm",
    version: str = "1.0.0",
    protocol: int = PROTOCOL_VERSION,
    body: str = 'result_path.write_text(json.dumps({"ok": True}), encoding="utf-8")\nsys.exit(0)',
    installed: bool = True,
    with_entry: bool = True,
) -> Path:
    """Раскладывает установленный компонент на диске так, как это делает download()."""
    version_dir = root / name / version
    inner = version_dir / f"Rozitta{name.upper()}"
    inner.mkdir(parents=True, exist_ok=True)

    entry = f"run_{name}.py"
    if with_entry:
        (inner / entry).write_text(_worker_source(body), encoding="utf-8")
    (inner / "component.json").write_text(
        json.dumps({"name": name, "version": version,
                    "protocol": protocol, "entry": entry}),
        encoding="utf-8")
    if installed:
        (version_dir / INSTALLED_MARKER).write_text("ok", encoding="utf-8")
    return version_dir


@pytest.fixture
def python_entry(monkeypatch):
    """
    Запускает .py-воркер текущим интерпретатором.

    В бою entry — это .exe, и менеджер вызывает его напрямую. В тестах
    подставлять .exe негде, поэтому подменяем сборку команды. Всё
    остальное — трубы, прогресс, коды возврата — работает как в бою.
    """
    from core.components import manager as mod

    original = mod.ComponentManager._spawn

    def patched(self, comp, task_path, result_path, progress_cb,
                cancel_flag, timeout_sec):
        real = mod.subprocess.Popen

        def popen(cmd, *a, **kw):
            return real([sys.executable] + list(cmd), *a, **kw)

        monkeypatch.setattr(mod.subprocess, "Popen", popen)
        try:
            return original(self, comp, task_path, result_path, progress_cb,
                            cancel_flag, timeout_sec)
        finally:
            monkeypatch.setattr(mod.subprocess, "Popen", real)

    monkeypatch.setattr(mod.ComponentManager, "_spawn", patched)


def make_registry(tmp_path: Path, zip_path: Path, *, protocol: int = 1,
                  sha256: str | None = None, name: str = "vlm",
                  version: str = "1.0.0") -> str:
    """Кладёт реестр файлом и возвращает file://-ссылку на него."""
    if sha256 is None:
        sha256 = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    registry = {
        "registry_version": 1,
        "components": {
            name: {
                "latest": version,
                "versions": {
                    version: {
                        "protocol": protocol,
                        "min_app_version": "1.7.3",
                        "size_bytes": zip_path.stat().st_size,
                        "sha256": sha256,
                        "urls": [zip_path.as_uri()],
                    }
                },
            }
        },
    }
    path = tmp_path / "components_registry.json"
    path.write_text(json.dumps(registry, ensure_ascii=False), encoding="utf-8")
    return path.as_uri()


def make_zip(tmp_path: Path, name: str = "vlm", version: str = "1.0.0",
             protocol: int = PROTOCOL_VERSION, body: str | None = None,
             extra: dict | None = None) -> Path:
    """Собирает архив компонента — то, что лежало бы в GitHub Releases."""
    staging = tmp_path / "staging"
    staging.mkdir(exist_ok=True)
    inner = staging / f"Rozitta{name.upper()}"
    inner.mkdir(exist_ok=True)
    entry = f"run_{name}.py"
    (inner / entry).write_text(
        _worker_source(body or 'result_path.write_text(json.dumps({"ok": True}),'
                               ' encoding="utf-8")\nsys.exit(0)'),
        encoding="utf-8")
    (inner / "component.json").write_text(
        json.dumps({"name": name, "version": version,
                    "protocol": protocol, "entry": entry}),
        encoding="utf-8")

    zip_path = tmp_path / f"{name}-{version}.zip"
    with zipfile.ZipFile(zip_path, "w") as z:
        for path in staging.rglob("*"):
            if path.is_file():
                z.write(path, path.relative_to(staging))
        for member, data in (extra or {}).items():
            z.writestr(member, data)
    return zip_path


# ──────────────────────────────────────────────────────────────────────────────
# Поиск установленного
# ──────────────────────────────────────────────────────────────────────────────

class TestGetInstalled:
    def test_nothing_installed(self, tmp_path):
        cm = ComponentManager(tmp_path, "file:///nowhere")
        assert cm.get_installed("vlm") is None

    def test_finds_installed(self, tmp_path):
        make_component(tmp_path)
        comp = ComponentManager(tmp_path, "x").get_installed("vlm")
        assert comp is not None
        assert comp.name == "vlm" and comp.version == "1.0.0"
        assert comp.protocol == PROTOCOL_VERSION
        assert comp.is_runnable

    def test_ignores_folder_without_marker(self, tmp_path):
        """
        Папка без `.installed` — след прерванной установки, а не версия.

        Принять её за рабочую значит запустить наполовину распакованный
        компонент; отказ понятнее любой ошибки, которую он выдаст.
        """
        make_component(tmp_path, installed=False)
        assert ComponentManager(tmp_path, "x").get_installed("vlm") is None

    def test_picks_newest_version_numerically(self, tmp_path):
        """1.10.0 новее 1.9.0 — сравнение строк здесь врёт."""
        make_component(tmp_path, version="1.9.0")
        make_component(tmp_path, version="1.10.0")
        comp = ComponentManager(tmp_path, "x").get_installed("vlm")
        assert comp.version == "1.10.0"

    def test_damaged_install_is_reported_not_hidden(self, tmp_path):
        """
        Антивирус вырезал .exe: маркер на месте, запускать нечего.

        Вернуть None было бы удобнее, но неверно: пользователь увидел бы
        «компонент не установлен» и скачал бы его заново поверх того же
        антивируса. Пусть вызывающий увидит повреждение и скажет об этом.
        """
        make_component(tmp_path, with_entry=False)
        comp = ComponentManager(tmp_path, "x").get_installed("vlm")
        assert comp is not None
        assert comp.is_runnable is False

    def test_broken_manifest_skipped(self, tmp_path):
        version_dir = make_component(tmp_path)
        manifest = next(version_dir.rglob("component.json"))
        manifest.write_text("{не json", encoding="utf-8")
        assert ComponentManager(tmp_path, "x").get_installed("vlm") is None


# ──────────────────────────────────────────────────────────────────────────────
# Реестр
# ──────────────────────────────────────────────────────────────────────────────

class TestRegistry:
    def test_fetch_and_pick(self, tmp_path):
        zip_path = make_zip(tmp_path)
        url = make_registry(tmp_path, zip_path)
        cm = ComponentManager(tmp_path / "components", url)
        version, info = cm.pick_version(cm.fetch_registry(), "vlm")
        assert version == "1.0.0"
        assert info["urls"]

    def test_missing_registry_is_an_error_not_emptiness(self, tmp_path):
        """
        Нет сети — это «не удалось получить список», а не «компонентов нет».

        Молчаливый пустой реестр показал бы пользователю, что функции
        не существует, вместо того чтобы предложить проверить соединение.
        """
        cm = ComponentManager(tmp_path, (tmp_path / "нет.json").as_uri())
        with pytest.raises(RegistryError):
            cm.fetch_registry()

    def test_garbage_registry(self, tmp_path):
        path = tmp_path / "r.json"
        path.write_text("не json вовсе", encoding="utf-8")
        cm = ComponentManager(tmp_path, path.as_uri())
        with pytest.raises(RegistryError):
            cm.fetch_registry()

    def test_registry_without_components_section(self, tmp_path):
        path = tmp_path / "r.json"
        path.write_text(json.dumps({"registry_version": 1}), encoding="utf-8")
        cm = ComponentManager(tmp_path, path.as_uri())
        with pytest.raises(RegistryError):
            cm.fetch_registry()

    def test_unknown_component(self, tmp_path):
        zip_path = make_zip(tmp_path)
        cm = ComponentManager(tmp_path, make_registry(tmp_path, zip_path))
        with pytest.raises(RegistryError):
            cm.pick_version(cm.fetch_registry(), "нет-такого")

    def test_newer_protocol_refused_with_update_hint(self, tmp_path):
        """
        Протокол новее нашего — единственный честный ответ «обновите приложение».

        Запустить такой компонент значит разобрать его результат по чужим
        правилам и получить тихо неверные данные.
        """
        zip_path = make_zip(tmp_path, protocol=PROTOCOL_VERSION + 1)
        url = make_registry(tmp_path, zip_path, protocol=PROTOCOL_VERSION + 1)
        cm = ComponentManager(tmp_path / "components", url)
        with pytest.raises(ComponentProtocolError, match="Обновите"):
            cm.pick_version(cm.fetch_registry(), "vlm")


# ──────────────────────────────────────────────────────────────────────────────
# Скачивание и установка
# ──────────────────────────────────────────────────────────────────────────────

class TestDownload:
    def test_installs_and_becomes_findable(self, tmp_path):
        zip_path = make_zip(tmp_path)
        url = make_registry(tmp_path, zip_path)
        root = tmp_path / "components"
        cm = ComponentManager(root, url)
        version, info = cm.pick_version(cm.fetch_registry(), "vlm")

        cm.download("vlm", version, info)
        comp = cm.get_installed("vlm")
        assert comp is not None and comp.is_runnable

    def test_progress_reaches_the_end(self, tmp_path):
        zip_path = make_zip(tmp_path)
        url = make_registry(tmp_path, zip_path)
        cm = ComponentManager(tmp_path / "components", url)
        version, info = cm.pick_version(cm.fetch_registry(), "vlm")

        seen = []
        cm.download("vlm", version, info, progress_cb=lambda d, t: seen.append((d, t)))
        assert seen and seen[-1][0] == zip_path.stat().st_size

    def test_bad_checksum_leaves_nothing_behind(self, tmp_path):
        """
        Главный тест раздела: после провала на диске не должно остаться
        полуустановленной версии — `get_installed()` принял бы её за рабочую.
        """
        zip_path = make_zip(tmp_path)
        url = make_registry(tmp_path, zip_path, sha256="0" * 64)
        root = tmp_path / "components"
        cm = ComponentManager(root, url)
        version, info = cm.pick_version(cm.fetch_registry(), "vlm")

        with pytest.raises(ComponentIntegrityError):
            cm.download("vlm", version, info)
        assert cm.get_installed("vlm") is None
        assert not (root / "vlm" / version).exists()

    def test_cancel_leaves_nothing_behind(self, tmp_path):
        zip_path = make_zip(tmp_path)
        url = make_registry(tmp_path, zip_path)
        root = tmp_path / "components"
        cm = ComponentManager(root, url)
        version, info = cm.pick_version(cm.fetch_registry(), "vlm")

        with pytest.raises(ComponentCancelled):
            cm.download("vlm", version, info, cancel_flag=lambda: True)
        assert cm.get_installed("vlm") is None
        assert not (root / "vlm" / version).exists()

    def test_zip_slip_refused(self, tmp_path):
        """
        Архив с путём «наружу» не должен разложиться поверх чужих файлов.

        Архив свой, но проверка стоит четырёх строк, а доверие — нет.
        """
        zip_path = make_zip(tmp_path, extra={"../сбежал.txt": "нет"})
        url = make_registry(tmp_path, zip_path)
        root = tmp_path / "components"
        cm = ComponentManager(root, url)
        version, info = cm.pick_version(cm.fetch_registry(), "vlm")

        with pytest.raises(ComponentIntegrityError):
            cm.download("vlm", version, info)
        assert not (root / "vlm" / "сбежал.txt").exists()

    def test_failed_reinstall_keeps_the_working_version(self, tmp_path):
        """
        Неудачная переустановка не должна оставить пользователя ни с чем.

        Первая версия менеджера сносила рабочую папку и только потом
        распаковывала новую: любой сбой на распаковке — и компонента нет
        вовсе, хотя минуту назад он работал. Теперь распаковка идёт в
        сторону, а подмена происходит готовым.
        """
        zip_path = make_zip(tmp_path)
        url = make_registry(tmp_path, zip_path)
        root = tmp_path / "components"
        cm = ComponentManager(root, url)
        version, info = cm.pick_version(cm.fetch_registry(), "vlm")

        cm.download("vlm", version, info)
        assert cm.get_installed("vlm").is_runnable

        # Та же версия, но архив с путём наружу — распаковка обязана упасть.
        bad_zip = make_zip(tmp_path, extra={"../сбежал.txt": "нет"})
        bad_info = dict(info)
        bad_info["urls"] = [bad_zip.as_uri()]
        bad_info["sha256"] = hashlib.sha256(bad_zip.read_bytes()).hexdigest()

        with pytest.raises(ComponentIntegrityError):
            cm.download("vlm", version, bad_info)

        still = cm.get_installed("vlm")
        assert still is not None and still.is_runnable, \
            "переустановка снесла рабочую версию и ничего не поставила взамен"

    def test_successful_reinstall_replaces_cleanly(self, tmp_path):
        """Успешная переустановка не оставляет следов подготовительной папки."""
        zip_path = make_zip(tmp_path)
        url = make_registry(tmp_path, zip_path)
        root = tmp_path / "components"
        cm = ComponentManager(root, url)
        version, info = cm.pick_version(cm.fetch_registry(), "vlm")

        cm.download("vlm", version, info)
        cm.download("vlm", version, info)

        assert cm.get_installed("vlm").is_runnable
        leftovers = [p.name for p in (root / "vlm").iterdir()
                     if p.name.startswith(".")]
        assert leftovers == [], f"остались временные папки: {leftovers}"

    def test_falls_back_to_mirror(self, tmp_path):
        """Первая ссылка мертва — берём вторую, а не сдаёмся."""
        zip_path = make_zip(tmp_path)
        url = make_registry(tmp_path, zip_path)
        cm = ComponentManager(tmp_path / "components", url)
        registry = cm.fetch_registry()
        version, info = cm.pick_version(registry, "vlm")
        info["urls"] = [(tmp_path / "мертво.zip").as_uri(), zip_path.as_uri()]

        cm.download("vlm", version, info)
        assert cm.get_installed("vlm") is not None

    def test_all_mirrors_dead(self, tmp_path):
        zip_path = make_zip(tmp_path)
        cm = ComponentManager(tmp_path / "components",
                              make_registry(tmp_path, zip_path))
        version, info = cm.pick_version(cm.fetch_registry(), "vlm")
        info["urls"] = [(tmp_path / "нет1.zip").as_uri(),
                        (tmp_path / "нет2.zip").as_uri()]
        with pytest.raises(RegistryError):
            cm.download("vlm", version, info)


# ──────────────────────────────────────────────────────────────────────────────
# Запуск: протокол §4 целиком
# ──────────────────────────────────────────────────────────────────────────────

class TestRun:
    def test_task_travels_as_a_file_and_result_comes_back(
            self, tmp_path, python_entry):
        """Задание доезжает целиком, включая кириллицу в путях и значениях."""
        body = '''
            result_path.write_text(json.dumps({
                "ok": True,
                "echo": task.get("images"),
                "protocol_seen": task.get("protocol"),
            }, ensure_ascii=False), encoding="utf-8")
            sys.exit(0)
        '''
        make_component(tmp_path, body=body)
        cm = ComponentManager(tmp_path, "x")
        comp = cm.get_installed("vlm")

        images = ["D:/Чат «Ландшафт»/photo/1.jpg"]
        out = cm.run(comp, {"task": "describe_images", "images": images})
        assert out["ok"] is True
        assert out["echo"] == images
        assert out["protocol_seen"] == PROTOCOL_VERSION

    def test_progress_lines_are_parsed(self, tmp_path, python_entry):
        body = '''
            for i in range(1, 4):
                print("PROGRESS %d 3" % i, flush=True)
            result_path.write_text(json.dumps({"ok": True}), encoding="utf-8")
            sys.exit(0)
        '''
        make_component(tmp_path, body=body)
        cm = ComponentManager(tmp_path, "x")
        seen = []
        cm.run(cm.get_installed("vlm"), {"task": "t"},
               progress_cb=lambda d, t: seen.append((d, t)))
        assert seen == [(1, 3), (2, 3), (3, 3)]

    def test_garbage_progress_does_not_kill_the_run(self, tmp_path, python_entry):
        """Прогресс — украшение; ронять из-за него сделанную работу нельзя."""
        body = '''
            print("PROGRESS ой всё", flush=True)
            print("PROGRESS", flush=True)
            print("просто строка в лог", flush=True)
            result_path.write_text(json.dumps({"ok": True}), encoding="utf-8")
            sys.exit(0)
        '''
        make_component(tmp_path, body=body)
        cm = ComponentManager(tmp_path, "x")
        assert cm.run(cm.get_installed("vlm"), {"task": "t"})["ok"] is True

    def test_exit_1_reports_error_from_result(self, tmp_path, python_entry):
        body = '''
            result_path.write_text(json.dumps({"ok": False,
                "error": "картинка не читается"}, ensure_ascii=False),
                encoding="utf-8")
            sys.exit(1)
        '''
        make_component(tmp_path, body=body)
        cm = ComponentManager(tmp_path, "x")
        with pytest.raises(ComponentRunError, match="картинка не читается"):
            cm.run(cm.get_installed("vlm"), {"task": "t"})

    def test_exit_2_without_result(self, tmp_path, python_entry):
        """Фатальная ошибка окружения: result-файла может не быть вовсе."""
        make_component(tmp_path, body="sys.exit(2)")
        cm = ComponentManager(tmp_path, "x")
        with pytest.raises(ComponentRunError, match="кодом 2"):
            cm.run(cm.get_installed("vlm"), {"task": "t"})

    def test_success_without_result_is_a_failure(self, tmp_path, python_entry):
        """
        Код 0 без результата — поломка компонента, а не успех.

        Молча вернуть пустой dict значило бы записать в архив ноль описаний
        и отчитаться, что всё прошло хорошо.
        """
        make_component(tmp_path, body="sys.exit(0)")
        cm = ComponentManager(tmp_path, "x")
        with pytest.raises(ComponentRunError, match="результата"):
            cm.run(cm.get_installed("vlm"), {"task": "t"})

    def test_unreadable_result(self, tmp_path, python_entry):
        body = '''
            result_path.write_text("{битый", encoding="utf-8")
            sys.exit(0)
        '''
        make_component(tmp_path, body=body)
        cm = ComponentManager(tmp_path, "x")
        with pytest.raises(ComponentRunError, match="нечитаемый"):
            cm.run(cm.get_installed("vlm"), {"task": "t"})

    def test_silent_hang_is_stopped_by_timeout(self, tmp_path, python_entry):
        """
        Зависший компонент не выдаёт ни строки — и именно поэтому stdout
        нельзя читать блокирующим циклом. Тест краснеет, если чтение
        вернуть к `for line in proc.stdout`.
        """
        make_component(tmp_path, body="time.sleep(60)\nsys.exit(0)")
        cm = ComponentManager(tmp_path, "x")
        with pytest.raises(ComponentRunError, match="не уложился"):
            cm.run(cm.get_installed("vlm"), {"task": "t"}, timeout_sec=2)

    def test_cancel_stops_a_running_component(self, tmp_path, python_entry):
        make_component(tmp_path, body="time.sleep(60)\nsys.exit(0)")
        cm = ComponentManager(tmp_path, "x")
        with pytest.raises(ComponentCancelled):
            cm.run(cm.get_installed("vlm"), {"task": "t"},
                   cancel_flag=lambda: True)

    def test_damaged_component_refuses_to_run_with_a_hint(self, tmp_path):
        make_component(tmp_path, with_entry=False)
        cm = ComponentManager(tmp_path, "x")
        with pytest.raises(ComponentRunError, match="антивирус"):
            cm.run(cm.get_installed("vlm"), {"task": "t"})

    def test_newer_protocol_refused_at_run_too(self, tmp_path):
        """
        Проверка протокола есть и в реестре, и здесь.

        Дублирование намеренное: компонент мог быть установлен старой
        версией приложения, которая тогда его понимала.
        """
        make_component(tmp_path, protocol=PROTOCOL_VERSION + 1)
        cm = ComponentManager(tmp_path, "x")
        with pytest.raises(ComponentProtocolError, match="Обновите"):
            cm.run(cm.get_installed("vlm"), {"task": "t"})

    def test_temp_files_are_cleaned_up(self, tmp_path, python_entry):
        """Задание и результат живут во временной папке и не переживают вызов."""
        import tempfile as tf
        before = set(os.listdir(tf.gettempdir()))
        make_component(tmp_path)
        cm = ComponentManager(tmp_path, "x")
        cm.run(cm.get_installed("vlm"), {"task": "t"})
        after = set(os.listdir(tf.gettempdir()))
        assert not [n for n in after - before if n.startswith("rozitta-")]


# ──────────────────────────────────────────────────────────────────────────────
# Qt-изоляция (правило проекта)
# ──────────────────────────────────────────────────────────────────────────────

def test_no_qt_imports():
    """
    В core/components/ не должно быть Qt: модуль зовут из QThread-воркера,
    но сам он обязан оставаться чистым Python — иначе его не переиспользовать
    ни в тестах без дисплея, ни в самом компоненте.

    Проверяются именно импорты, разобранные через AST. Первая версия теста
    искала «QThread» подстрокой по файлу и краснела на слове в докстроке —
    ловила упоминание вместо зависимости.
    """
    import ast

    for path in (Path("core/components/manager.py"),
                 Path("core/components/__init__.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        qt = [m for m in imported
              if m.split(".")[0] in {"PySide6", "PyQt5", "PyQt6", "qtpy"}]
        assert not qt, f"{path}: Qt пробрался в core/components — {qt}"
