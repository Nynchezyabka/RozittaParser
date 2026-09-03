# -*- coding: utf-8 -*-
"""
tests/test_features/test_export_naming.py

Схема имён файлов экспорта (docs/EXPORT_NAMING.md, разделы 5-6):

    {чат}[_{топик}][_{kind}][_{фильтр}][_threads][_comments][_{период}]

Проверяются решения Р-3…Р-6 и закрытая ими дыра D-3. Главный риск во всём
разделе один и тот же (правило I11): две выгрузки с разными настройками
получают одно имя, и вторая молча затирает первую.
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
    _build_base_name,
)

CHAT_ID = -1001
NAMES = {111: "Мария Петрова", 222: "Иван Соколов"}


# ══════════════════════════════════════════════════════════════════════════════
# Сборка имени — без базы
# ══════════════════════════════════════════════════════════════════════════════

class TestSlotOrder:
    """Р-4: слоты идут от общего к частному, порядок один на все виды."""

    def test_bare_chat(self):
        assert _build_base_name("Чат", period_label="alltime") == "Чат_alltime"

    def test_kind_goes_right_after_topic(self):
        name = _build_base_name(
            "Чат", topic_name="Терраса", kind="post_42",
            include_comments=True, period_label="alltime",
        )
        assert name == "Чат_Терраса_post_42_comments_alltime"

    def test_topic_id_used_when_name_missing(self):
        name = _build_base_name("Чат", topic_id=7, period_label="alltime")
        assert name == "Чат_topic7_alltime"

    def test_topic_name_wins_over_id(self):
        name = _build_base_name(
            "Чат", topic_name="Терраса", topic_id=7, period_label="alltime")
        assert "topic7" not in name
        assert "Терраса" in name

    def test_filter_precedes_mode_markers(self):
        name = _build_base_name(
            "Чат",
            user_filter=UserFilter.make(MODE_EXCLUDE, [111], NAMES),
            include_comments=True,
            period_label="alltime",
        )
        assert name == "Чат_except_Мария Петрова_comments_alltime"


class TestArchiveSlotIsGone:
    """Р-5: у единого файла слота kind нет вовсе."""

    def test_single_file_has_no_kind_word(self):
        assert _build_base_name("Чат", period_label="alltime") == "Чат_alltime"

    def test_archive_word_absent(self):
        assert "archive" not in _build_base_name("Чат", period_label="alltime")


class TestPeriodIsSkippedWhenKindHasDate:
    """
    Р-6: метка периода не пишется рядом с day_/month_.

    Иначе «Чат_day_2024-01-15_2024-01-01_to_2024-03-31» — вторая дата
    одинакова на всех файлах выгрузки и не различает ничего.
    """

    @pytest.mark.parametrize("kind", ["day_2024-01-15", "month_2024-01"])
    def test_dated_kind_drops_period(self, kind):
        name = _build_base_name("Чат", kind=kind, period_label="alltime")
        assert name == f"Чат_{kind}"

    def test_post_kind_keeps_period(self):
        """У поста своей даты в имени нет — период нужен."""
        name = _build_base_name("Чат", kind="post_42", period_label="alltime")
        assert name == "Чат_post_42_alltime"

    def test_dated_kind_still_keeps_filter(self):
        """Убирается период, а не всё подряд: фильтр обязан уцелеть."""
        name = _build_base_name(
            "Чат", kind="day_2024-01-15",
            user_filter=UserFilter.make(MODE_EXCLUDE, [111], NAMES),
            period_label="alltime",
        )
        assert name == "Чат_day_2024-01-15_except_Мария Петрова"


class TestWhoSlot:
    """
    Р-3 + запасное «кто» для режима веток.

    В ветках участник приходит отдельным user_id, а не фильтром (O-2).
    Без запасного слота ветки всех участников чата получили бы одно имя.
    """

    def test_who_used_when_filter_is_silent(self):
        name = _build_base_name(
            "Чат", who="Мария Петрова",
            user_filter_mode="threads", period_label="alltime")
        assert name == "Чат_Мария Петрова_threads_alltime"

    def test_filter_wins_over_who(self):
        """Иначе имя назовёт одного человека дважды."""
        name = _build_base_name(
            "Чат", who="Мария Петрова",
            user_filter=UserFilter.make(MODE_INCLUDE, [111], NAMES),
            user_filter_mode="threads", period_label="alltime",
        )
        assert name.count("Мария Петрова") == 1
        assert name == "Чат_only_Мария Петрова_threads_alltime"

    def test_different_thread_owners_differ(self):
        a = _build_base_name("Чат", who="Мария", user_filter_mode="threads")
        b = _build_base_name("Чат", who="Иван", user_filter_mode="threads")
        assert a != b


# ══════════════════════════════════════════════════════════════════════════════
# D-3 — фильтр в именах режима «по постам»
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def channel():
    """Канал с двумя постами и комментариями двух человек к каждому."""
    with DBManager(":memory:") as db:
        rows = []
        for pid in (10, 20):
            rows.append({
                "chat_id": CHAT_ID, "message_id": pid,
                "date": "2024-01-15 10:00:00",
                "topic_id": None, "user_id": 999, "username": "Канал",
                "text": f"Пост {pid}", "media_path": None,
                "file_type": None, "file_size": None,
                "reply_to_msg_id": None, "post_id": None,
                "is_comment": 0, "from_linked_group": 0,
            })
            for offset, uid in enumerate((111, 222), start=1):
                rows.append({
                    "chat_id": CHAT_ID, "message_id": pid + offset,
                    "date": f"2024-01-15 10:0{offset}:00",
                    "topic_id": None, "user_id": uid, "username": NAMES[uid],
                    "text": f"Комментарий {NAMES[uid]}", "media_path": None,
                    "file_type": None, "file_size": None,
                    "reply_to_msg_id": pid, "post_id": pid,
                    "is_comment": 1, "from_linked_group": 1,
                })
        db.insert_messages_batch(rows)
        yield db


_BY_POST_GENERATORS = [
    (JsonGenerator, "generate_by_posts", ".json"),
    (MarkdownGenerator, "generate_by_posts", ".md"),
    (HtmlGenerator, "generate_by_posts", ".html"),
]


class TestByPostsCarriesTheFilter:
    """
    Дыра D-3: путь «по постам» собирал имя сам и терял фрагмент фильтра.
    Выгрузка «пост 42 без Марии» затирала «пост 42 целиком».
    """

    @pytest.mark.parametrize("gen_cls,method,ext", _BY_POST_GENERATORS)
    def test_filtered_does_not_overwrite_full(self, channel, tmp_path,
                                              gen_cls, method, ext):
        uf = UserFilter.make(MODE_EXCLUDE, [111], NAMES)

        full = getattr(gen_cls(channel, output_dir=str(tmp_path)), method)(
            CHAT_ID, "Канал", include_comments=True, period_label="alltime")
        filtered = getattr(
            gen_cls(channel, output_dir=str(tmp_path), user_filter=uf), method
        )(CHAT_ID, "Канал", include_comments=True, period_label="alltime")

        assert {os.path.basename(p) for p in full} != \
               {os.path.basename(p) for p in filtered}
        produced = [f for f in os.listdir(tmp_path) if f.endswith(ext)]
        assert len(produced) == len(full) + len(filtered)

    @pytest.mark.parametrize("gen_cls,method,ext", _BY_POST_GENERATORS)
    def test_filter_fragment_is_in_the_name(self, channel, tmp_path,
                                            gen_cls, method, ext):
        uf = UserFilter.make(MODE_EXCLUDE, [111, 222], NAMES)
        paths = getattr(
            gen_cls(channel, output_dir=str(tmp_path), user_filter=uf), method
        )(CHAT_ID, "Канал", include_comments=True, period_label="alltime")
        for p in paths:
            assert "except_2_users_" in os.path.basename(p)

    @pytest.mark.parametrize("gen_cls,method,ext", _BY_POST_GENERATORS)
    def test_post_number_stays_in_the_name(self, channel, tmp_path,
                                           gen_cls, method, ext):
        """Номер поста — адрес файла, он обязан пережить перестановку слотов."""
        paths = getattr(gen_cls(channel, output_dir=str(tmp_path)), method)(
            CHAT_ID, "Канал", include_comments=True, period_label="alltime")
        names = {os.path.basename(p) for p in paths}
        assert any("post_10" in n for n in names)
        assert any("post_20" in n for n in names)


# ══════════════════════════════════════════════════════════════════════════════
# DOCX — календарное дробление и единый файл
# ══════════════════════════════════════════════════════════════════════════════

class TestDocxNames:
    def test_single_file_has_no_archive_word(self, channel, tmp_path):
        gen = DocxGenerator(channel, output_dir=str(tmp_path))
        path = gen.generate(CHAT_ID, "Канал", period_label="alltime")[0]
        assert "archive" not in os.path.basename(path)

    def test_day_split_has_no_trailing_period(self, channel, tmp_path):
        gen = DocxGenerator(channel, output_dir=str(tmp_path))
        paths = gen.generate(CHAT_ID, "Канал", split_mode="day",
                             period_label="alltime")
        for p in paths:
            name = os.path.basename(p)
            assert "day_2024-01-15" in name
            assert "alltime" not in name

    def test_month_split_has_no_trailing_period(self, channel, tmp_path):
        gen = DocxGenerator(channel, output_dir=str(tmp_path))
        paths = gen.generate(CHAT_ID, "Канал", split_mode="month",
                             period_label="alltime")
        for p in paths:
            name = os.path.basename(p)
            assert "month_2024-01" in name
            assert "alltime" not in name

    def test_filter_still_separates_day_files(self, channel, tmp_path):
        """
        Р-6 убрал период — но не право фильтра различать файлы.
        Без фрагмента фильтра выгрузка за тот же день затёрла бы полную.
        """
        uf = UserFilter.make(MODE_EXCLUDE, [111], NAMES)
        full = DocxGenerator(channel, output_dir=str(tmp_path)).generate(
            CHAT_ID, "Канал", split_mode="day", period_label="alltime")
        filtered = DocxGenerator(
            channel, output_dir=str(tmp_path), user_filter=uf).generate(
            CHAT_ID, "Канал", split_mode="day", period_label="alltime")
        assert {os.path.basename(p) for p in full} != \
               {os.path.basename(p) for p in filtered}
