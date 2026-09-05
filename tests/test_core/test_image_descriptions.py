# -*- coding: utf-8 -*-
"""
tests/test_core/test_image_descriptions.py — таблица описаний (CM-3).

Форма зеркальна transcriptions, поэтому и проверки те же: перезапись вместо
дублей, отбор кандидатов, карта для генераторов. Отдельно закреплён отбор
по типу файла — рассинхрон с тем, что пишет парсер, даёт тихий отказ, ровно
как было с кружочками в STT.
"""
import pytest

from core.database import DBManager

CHAT = -1001


def _msg(db, message_id, file_type, media_path="p.jpg", date="2024-01-01 10:00:00"):
    db.insert_messages_batch([{
        "chat_id": CHAT, "message_id": message_id, "date": date,
        "topic_id": None, "user_id": 1, "username": "кто-то", "text": "",
        "media_path": media_path, "file_type": file_type, "file_size": 1,
        "reply_to_msg_id": None, "post_id": None,
        "is_comment": 0, "from_linked_group": 0,
    }])


@pytest.fixture
def db():
    with DBManager(":memory:") as d:
        yield d


class TestInsert:
    def test_roundtrip(self, db):
        _msg(db, 1, "photo")
        db.insert_image_description(1, CHAT, "куст в цвету")
        assert db.get_image_descriptions_for_chat(CHAT) == {1: "куст в цвету"}

    def test_repeat_replaces_not_duplicates(self, db):
        """
        Перезапись делает выгрузку возобновляемой: пачку, остановленную на
        середине, можно запустить снова.
        """
        _msg(db, 1, "photo")
        db.insert_image_description(1, CHAT, "первое")
        db.insert_image_description(1, CHAT, "второе")
        assert db.get_image_descriptions_for_chat(CHAT) == {1: "второе"}

    def test_model_type_recorded(self, db):
        """Знать, какой моделью сделано описание, нужно при смене весов."""
        _msg(db, 1, "photo")
        db.insert_image_description(1, CHAT, "текст", model_type="qwen3vl-4b")
        with db._cursor() as cur:
            cur.execute("SELECT model_type FROM image_descriptions")
            assert cur.fetchone()[0] == "qwen3vl-4b"


class TestCandidates:
    def test_photo_is_a_candidate(self, db):
        _msg(db, 1, "photo")
        assert [r["message_id"] for r in db.get_vlm_candidates(CHAT)] == [1]

    def test_described_photo_drops_out(self, db):
        """
        Повторный запуск не должен описывать одно и то же дважды: это часы
        работы и деньги на ветер, а результат тот же.
        """
        _msg(db, 1, "photo")
        db.insert_image_description(1, CHAT, "готово")
        assert db.get_vlm_candidates(CHAT) == []

    @pytest.mark.parametrize("file_type", ["voice", "videomessage", "video",
                                           "file", "document"])
    def test_non_images_are_not_candidates(self, db, file_type):
        """
        Отбор по типу — здесь, а не у вызывающего: media_path есть и у
        голосовых, и у документов, а описывать имеет смысл картинки.
        """
        _msg(db, 1, file_type)
        assert db.get_vlm_candidates(CHAT) == []

    def test_type_matches_what_the_parser_actually_writes(self, db):
        """
        Строка типа обязана совпадать с тем, что кладёт в file_type парсер.

        Рассинхрон даёт тихий отказ: кандидатов ноль, в журнале «нечего
        описывать», исключения нет — ровно так кружочки год не попадали
        в STT (`videomessage` против `video_note`).

        Поэтому берём литералы прямо из исходника `_detect_media_type` и
        проверяем, что хотя бы один из них наш отбор принимает. Тест
        краснеет и когда парсер переименует тип, и когда SQL разойдётся
        с парсером.
        """
        import ast
        import inspect
        import textwrap

        from features.parser.api import ParserService

        # dedent обязателен: getsource отдаёт метод с отступом класса,
        # и ast.parse на нём спотыкается.
        source = textwrap.dedent(inspect.getsource(
            ParserService._detect_media_type))
        tree = ast.parse(source)
        returned = {
            node.value.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Return)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        }
        assert "photo" in returned, (
            f"парсер больше не пишет 'photo', он пишет {sorted(returned)} — "
            f"отбор кандидатов в get_vlm_candidates() надо править вслед"
        )

        for kind in returned:
            _msg(db, hash(kind) % 10_000, kind)
        got = {r["file_type"] for r in db.get_vlm_candidates(CHAT)}
        assert got == {"photo"}, (
            f"отбор принимает {sorted(got)}; описывать имеет смысл только "
            f"изображения"
        )

    def test_message_without_media_ignored(self, db):
        _msg(db, 1, "photo", media_path=None)
        assert db.get_vlm_candidates(CHAT) == []

    def test_empty_media_path_ignored(self, db):
        _msg(db, 1, "photo", media_path="")
        assert db.get_vlm_candidates(CHAT) == []

    def test_chronological_order(self, db):
        """Порядок важен для прогресса: человек видит, докуда дошло."""
        _msg(db, 3, "photo", date="2024-03-01 10:00:00")
        _msg(db, 1, "photo", date="2024-01-01 10:00:00")
        _msg(db, 2, "photo", date="2024-02-01 10:00:00")
        got = [r["message_id"] for r in db.get_vlm_candidates(CHAT)]
        assert got == [1, 2, 3]

    def test_other_chat_not_touched(self, db):
        _msg(db, 1, "photo")
        db.insert_messages_batch([{
            "chat_id": -2002, "message_id": 9, "date": "2024-01-01 10:00:00",
            "topic_id": None, "user_id": 1, "username": "x", "text": "",
            "media_path": "q.jpg", "file_type": "photo", "file_size": 1,
            "reply_to_msg_id": None, "post_id": None,
            "is_comment": 0, "from_linked_group": 0,
        }])
        assert [r["message_id"] for r in db.get_vlm_candidates(CHAT)] == [1]


class TestDescriptionsMap:
    def test_empty_chat(self, db):
        assert db.get_image_descriptions_for_chat(CHAT) == {}

    def test_only_this_chat(self, db):
        _msg(db, 1, "photo")
        db.insert_image_description(1, CHAT, "наше")
        db.insert_image_description(1, -2002, "чужое")
        assert db.get_image_descriptions_for_chat(CHAT) == {1: "наше"}
