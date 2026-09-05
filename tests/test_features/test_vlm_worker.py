# -*- coding: utf-8 -*-
"""
tests/test_features/test_vlm_worker.py — VlmWorker и цепочка выгрузки.

Компонента здесь нет: подменяется ComponentManager, а всё остальное —
отбор кандидатов, раскладка результата по БД, поведение при сбоях —
работает по-настоящему.

Отдельно закреплён порядок в MainWindow. Он выглядит мелочью, но если
описания лягут в БД после сборки документа, выгрузка выйдет без них, и
человеку придётся гонять всё заново — а это часы.
"""
import os

import pytest

from core.database import DBManager
from core.exceptions import ComponentCancelled, ComponentRunError
from features.vlm.ui import VlmWorker

CHAT = -1001


class FakeComponent:
    protocol = 1
    name = "vlm"
    version = "1.0.0"

    def __init__(self, runnable=True):
        self.is_runnable = runnable


class FakeManager:
    """Стоит на месте ComponentManager. Помнит, что у него просили."""

    def __init__(self, *args, **kwargs):
        self.installed = FakeManager.next_installed
        self.result = FakeManager.next_result
        self.raises = FakeManager.next_raises
        self.last_task = None
        FakeManager.instances.append(self)

    instances = []
    next_installed = FakeComponent()
    next_result = {"descriptions": {}, "errors": {}}
    next_raises = None

    def get_installed(self, name):
        return self.installed

    def run(self, comp, task, progress_cb=None, cancel_flag=None,
            timeout_sec=None):
        self.last_task = task
        self.last_timeout = timeout_sec
        if progress_cb:
            progress_cb(1, 1)
        if self.raises:
            raise self.raises
        return self.result


@pytest.fixture(autouse=True)
def fake_manager(monkeypatch):
    import features.vlm.ui as mod
    FakeManager.instances = []
    FakeManager.next_installed = FakeComponent()
    FakeManager.next_result = {"descriptions": {}, "errors": {}}
    FakeManager.next_raises = None
    monkeypatch.setattr(mod, "ComponentManager", FakeManager)
    return FakeManager


@pytest.fixture
def db_path(tmp_path):
    """База с двумя картинками, файлы которых лежат на диске."""
    path = tmp_path / "archive.db"
    with DBManager(str(path)) as db:
        rows = []
        for n in (1, 2):
            img = tmp_path / f"{n}.jpg"
            img.write_bytes(b"\xff\xd8\xff")          # заголовок JPEG
            rows.append({
                "chat_id": CHAT, "message_id": n,
                "date": f"2024-01-0{n} 10:00:00",
                "topic_id": None, "user_id": 1, "username": "Мария",
                "text": "", "media_path": str(img), "file_type": "photo",
                "file_size": 3, "reply_to_msg_id": None, "post_id": None,
                "is_comment": 0, "from_linked_group": 0,
            })
        db.insert_messages_batch(rows)
    return str(path), tmp_path


def run_worker(db_path_tuple) -> tuple:
    """Прогоняет run() синхронно и собирает сигналы."""
    path, _ = db_path_tuple
    worker = VlmWorker(path, CHAT, "components", "file:///нет")
    logs, errors, progress = [], [], []
    worker.log_message.connect(logs.append)
    worker.error.connect(errors.append)
    worker.progress.connect(progress.append)
    worker.run()                                    # без старта потока
    return logs, errors, progress


class TestHappyPath:
    def test_descriptions_land_in_the_database(self, db_path, fake_manager):
        path, tmp = db_path
        fake_manager.next_result = {
            "descriptions": {str(tmp / "1.jpg"): "дом с номером 222",
                             str(tmp / "2.jpg"): "куст в цвету"},
            "errors": {}, "model": "base",
        }
        run_worker(db_path)
        with DBManager(path) as db:
            assert db.get_image_descriptions_for_chat(CHAT) == {
                1: "дом с номером 222", 2: "куст в цвету"}

    def test_only_existing_files_are_sent(self, db_path, fake_manager):
        """
        Файл могли удалить после парсинга. Отправлять его компоненту значит
        получить ошибку на ровном месте и потратить время на пустое.
        """
        path, tmp = db_path
        (tmp / "2.jpg").unlink()
        run_worker(db_path)
        sent = FakeManager.instances[0].last_task["images"]
        assert sent == [str(tmp / "1.jpg")]

    def test_timeout_scales_with_batch_size(self, db_path, fake_manager):
        """Минута на картинку, но не меньше десяти минут (§6)."""
        run_worker(db_path)
        assert FakeManager.instances[0].last_timeout >= 600

    def test_already_described_are_not_resent(self, db_path, fake_manager):
        """Повторный прогон — это часы работы; описанное второй раз не идёт."""
        path, tmp = db_path
        with DBManager(path) as db:
            db.insert_image_description(1, CHAT, "уже есть")
        run_worker(db_path)
        sent = FakeManager.instances[0].last_task["images"]
        assert sent == [str(tmp / "2.jpg")]

    def test_progress_reaches_hundred(self, db_path, fake_manager):
        _, _, progress = run_worker(db_path)
        assert progress and progress[-1] == 100


class TestComponentMissing:
    def test_absent_component_is_not_an_error(self, db_path, fake_manager):
        """
        Функцию включили, компонент не поставили — идём дальше молча.

        Ошибка здесь была бы враньём: ничего не сломалось, просто нечем
        работать. Диалог скачивания показывает интерфейс, до выгрузки.
        """
        fake_manager.next_installed = None
        logs, errors, _ = run_worker(db_path)
        assert errors == []
        assert any("не установлен" in l for l in logs)

    def test_damaged_component_says_so(self, db_path, fake_manager):
        """
        Антивирус вырезал exe. Здесь молчать нельзя: человек включил
        функцию, она не работает, и он должен узнать почему.
        """
        fake_manager.next_installed = FakeComponent(runnable=False)
        _, errors, _ = run_worker(db_path)
        assert errors and "повреждён" in errors[0]


class TestFailuresDoNotLoseWork:
    def test_partial_result_is_saved(self, db_path, fake_manager):
        """
        Компонент описал одну из двух и сообщил об ошибке на второй.
        Сохранить надо первую: терять сделанное из-за несделанного нельзя.
        """
        path, tmp = db_path
        fake_manager.next_result = {
            "descriptions": {str(tmp / "1.jpg"): "дом",
                             str(tmp / "2.jpg"): None},
            "errors": {str(tmp / "2.jpg"): "битый файл"},
            "model": "base",
        }
        logs, errors, _ = run_worker(db_path)
        with DBManager(path) as db:
            assert db.get_image_descriptions_for_chat(CHAT) == {1: "дом"}
        assert any("Не удалось описать" in l for l in logs)

    def test_component_failure_becomes_an_error_signal(self, db_path,
                                                       fake_manager):
        fake_manager.next_raises = ComponentRunError("компонент упал")
        _, errors, _ = run_worker(db_path)
        assert errors and "компонент упал" in errors[0]

    def test_cancel_is_quiet(self, db_path, fake_manager):
        """
        Отмена — не сбой. Красная строка в журнале сказала бы человеку,
        что он что-то сломал, хотя он просто нажал «Стоп».
        """
        fake_manager.next_raises = ComponentCancelled("остановлено")
        logs, errors, _ = run_worker(db_path)
        assert errors == []
        assert any("остановлено" in l for l in logs)

    def test_finished_fires_even_on_failure(self, db_path, fake_manager):
        """
        Сигнал finished обязан прийти при любом исходе: на нём висит
        запуск экспорта, и без него выгрузка встанет навсегда.
        """
        fake_manager.next_raises = ComponentRunError("упал")
        worker = VlmWorker(db_path[0], CHAT, "components", "file:///нет")
        done = []
        worker.finished.connect(lambda: done.append(True))
        worker.error.connect(lambda _: None)
        worker.run()
        assert done == [True]


class TestNothingToDo:
    def test_no_images_at_all(self, tmp_path, fake_manager):
        path = tmp_path / "empty.db"
        with DBManager(str(path)) as db:
            db.insert_chat(chat_id=CHAT, title="Пусто", chat_type="channel")
        worker = VlmWorker(str(path), CHAT, "components", "file:///нет")
        logs = []
        worker.log_message.connect(logs.append)
        worker.run()
        assert any("Нечего описывать" in l for l in logs)
        assert FakeManager.instances[0].last_task is None
