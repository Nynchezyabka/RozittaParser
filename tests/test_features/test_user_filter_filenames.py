"""
tests/test_features/test_user_filter_filenames.py

FEAT-6 — имя файла отражает фильтр участников.

Главный риск: выгрузка с фильтром и полный архив того же чата за тот же
период получают одно имя, и вторая молча затирает первую (правило I11).
"""

import os

import pytest

from core.database import DBManager
from features.export.filters import MODE_EXCLUDE, MODE_INCLUDE, UserFilter
from features.export.generator import (
    DocxGenerator,
    HtmlGenerator,
    JsonGenerator,
    MarkdownGenerator,
)

NAMES = {111: "Мария Петрова", 222: "Иван Соколов", 333: "Ольга Кузнецова"}


@pytest.fixture
def db_three():
    with DBManager(":memory:") as db:
        db.insert_messages_batch([
            {
                "chat_id": -1001, "message_id": i,
                "date": f"2024-01-15 10:0{i}:00",
                "topic_id": None, "user_id": uid, "username": NAMES[uid],
                "text": f"текст {NAMES[uid]}",
                "media_path": None, "file_type": None, "file_size": None,
                "reply_to_msg_id": None, "post_id": None,
                "is_comment": 0, "from_linked_group": 0,
            }
            for i, uid in enumerate([111, 222, 333], start=1)
        ])
        yield db


def _name(db, out_dir, user_filter=None, username=None):
    kwargs = {"user_filter": user_filter} if user_filter else {}
    gen = MarkdownGenerator(db, output_dir=str(out_dir), **kwargs)
    path = gen.generate(-1001, "Чат", username=username,
                        period_label="fullchat")[0]
    return os.path.basename(path)


# ──────────────────────────────────────────────────────────────────────────────
# Уникальность имён
# ──────────────────────────────────────────────────────────────────────────────

class TestFilenameUniqueness:
    def test_filter_does_not_overwrite_full_archive(self, db_three, tmp_path):
        """Главный тест: отфильтрованная выгрузка не затирает полный архив."""
        full = _name(db_three, tmp_path)
        filtered = _name(db_three, tmp_path,
                         UserFilter.make(MODE_EXCLUDE, [222], NAMES))
        assert full != filtered

    def test_different_excluded_users_differ(self, db_three, tmp_path):
        a = _name(db_three, tmp_path,
                  UserFilter.make(MODE_EXCLUDE, [111], NAMES))
        b = _name(db_three, tmp_path,
                  UserFilter.make(MODE_EXCLUDE, [222], NAMES))
        assert a != b

    def test_different_sets_of_two_differ(self, db_three, tmp_path):
        """Два разных набора по двое — разные хеши, разные файлы."""
        a = _name(db_three, tmp_path,
                  UserFilter.make(MODE_INCLUDE, [111, 222], NAMES))
        b = _name(db_three, tmp_path,
                  UserFilter.make(MODE_INCLUDE, [111, 333], NAMES))
        assert a != b

    def test_include_and_exclude_differ(self, db_three, tmp_path):
        a = _name(db_three, tmp_path,
                  UserFilter.make(MODE_INCLUDE, [111, 222], NAMES))
        b = _name(db_three, tmp_path,
                  UserFilter.make(MODE_EXCLUDE, [111, 222], NAMES))
        assert a != b

    def test_all_variants_produce_distinct_files(self, db_three, tmp_path):
        """Семь разных настроек — семь файлов на диске, ничего не затёрто."""
        variants = [
            None,
            UserFilter.make(MODE_EXCLUDE, [111], NAMES),
            UserFilter.make(MODE_EXCLUDE, [222], NAMES),
            UserFilter.make(MODE_EXCLUDE, [111, 222], NAMES),
            UserFilter.make(MODE_EXCLUDE, [111, 333], NAMES),
            UserFilter.make(MODE_INCLUDE, [111, 222], NAMES),
            UserFilter.make(MODE_INCLUDE, [111, 333], NAMES),
        ]
        names = {_name(db_three, tmp_path, uf) for uf in variants}
        assert len(names) == len(variants)
        produced = [f for f in os.listdir(tmp_path) if f.endswith(".md")]
        assert len(produced) == len(variants)


# ──────────────────────────────────────────────────────────────────────────────
# Соглашение по именам
# ──────────────────────────────────────────────────────────────────────────────

class TestFilenameConvention:
    def test_exclude_single_uses_name(self, db_three, tmp_path):
        name = _name(db_three, tmp_path,
                     UserFilter.make(MODE_EXCLUDE, [111], NAMES))
        assert "except_Мария Петрова" in name

    def test_exclude_multi_uses_count_and_hash(self, db_three, tmp_path):
        name = _name(db_three, tmp_path,
                     UserFilter.make(MODE_EXCLUDE, [111, 222], NAMES))
        assert "except_2_users_" in name

    def test_include_multi_uses_count_and_hash(self, db_three, tmp_path):
        name = _name(db_three, tmp_path,
                     UserFilter.make(MODE_INCLUDE, [111, 222], NAMES))
        assert "only_2_users_" in name

    def test_include_single_uses_name(self, db_three, tmp_path):
        """Р-3: один выбранный — «only_Имя», а не голое имя без слова."""
        name = _name(db_three, tmp_path,
                     UserFilter.make(MODE_INCLUDE, [111], NAMES),
                     username=NAMES[111])
        assert "only_Мария Петрова" in name

    def test_username_no_longer_doubles_the_filter(self, db_three, tmp_path):
        """
        Р-3: username в имя не идёт. Он заполнялся ровно тогда, когда фильтр
        в режиме include с одним выбранным, — то есть называл того же
        человека вторым способом, и имя получало его дважды.
        """
        uf = UserFilter.make(MODE_INCLUDE, [111], NAMES)
        with_username = _name(db_three, tmp_path, uf, username=NAMES[111])
        without       = _name(db_three, tmp_path, uf)
        assert with_username == without
        assert with_username.count("Мария Петрова") == 1

    def test_no_filter_name_unchanged(self, db_three, tmp_path):
        assert _name(db_three, tmp_path) == "Чат_fullchat.md"


# ──────────────────────────────────────────────────────────────────────────────
# Все четыре генератора
# ──────────────────────────────────────────────────────────────────────────────

class TestAllGenerators:
    @pytest.mark.parametrize("generator_cls", [
        MarkdownGenerator, HtmlGenerator, JsonGenerator, DocxGenerator,
    ])
    def test_filter_reaches_every_generator(self, db_three, tmp_path,
                                            generator_cls):
        """
        Фрагмент фильтра должен попасть в имя во всех форматах.

        Этот тест краснеет, если рефакторинг общей сборки имени потеряет
        фильтр в одном из путей.
        """
        uf = UserFilter.make(MODE_EXCLUDE, [111, 222], NAMES)
        gen = generator_cls(db_three, output_dir=str(tmp_path), user_filter=uf)
        path = gen.generate(-1001, "Чат", period_label="fullchat")[0]
        assert "except_2_users_" in os.path.basename(path)
