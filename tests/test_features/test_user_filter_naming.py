"""
tests/test_features/test_user_filter_naming.py

FEAT-6 — имена файлов и шапка документа.
Соглашение проекта: служебные слова английские (ср. threads, comments,
fullchat, _to_), имена участников — данные, остаются как есть.
"""

from features.export.filters import (
    MODE_EXCLUDE,
    MODE_INCLUDE,
    NO_FILTER,
    UserFilter,
)

NAMES = {
    111: "Мария Петрова",
    222: "Иван Соколов",
    333: "Ольга Кузнецова",
    444: "Дмитрий Волков",
}


# ──────────────────────────────────────────────────────────────────────────────
# Фрагмент имени файла
# ──────────────────────────────────────────────────────────────────────────────

class TestNamePart:
    def test_no_filter_gives_empty(self):
        assert NO_FILTER.name_part() == ""

    def test_include_single_defers_to_existing_user_part(self):
        """Один выбранный — имя подставит существующий user_part, не дублируем."""
        uf = UserFilter.make(MODE_INCLUDE, [111], NAMES)
        assert uf.name_part() == ""

    def test_include_multi_uses_count(self):
        uf = UserFilter.make(MODE_INCLUDE, [111, 222, 333], NAMES)
        part = uf.name_part()
        assert part.startswith("only_3_users_")
        assert len(part.split("_")[-1]) == 4

    def test_exclude_single_uses_name(self):
        uf = UserFilter.make(MODE_EXCLUDE, [111], NAMES)
        assert uf.name_part() == "except_Мария Петрова"

    def test_exclude_multi_uses_count(self):
        uf = UserFilter.make(MODE_EXCLUDE, [111, 222], NAMES)
        assert uf.name_part().startswith("except_2_users_")

    def test_service_words_are_ascii(self):
        """Служебные слова английские — как threads/comments/fullchat."""
        uf = UserFilter.make(MODE_INCLUDE, [111, 222], NAMES)
        head = uf.name_part().split("_")[0]
        assert head.isascii()
        assert head == "only"

    def test_exclude_single_without_names_falls_back_to_count(self):
        uf = UserFilter.make(MODE_EXCLUDE, [111])
        assert uf.name_part().startswith("except_1_users_")

    def test_unsafe_chars_sanitized(self):
        uf = UserFilter.make(MODE_EXCLUDE, [111], {111: "Ivan/Bad:Name"})
        part = uf.name_part()
        assert "/" not in part
        assert ":" not in part


# ──────────────────────────────────────────────────────────────────────────────
# Хеш набора — защита от молчаливой перезаписи (I11)
# ──────────────────────────────────────────────────────────────────────────────

class TestSetHash:
    def test_different_sets_give_different_names(self):
        """Главный тест: два набора по трое не должны затирать друг друга."""
        a = UserFilter.make(MODE_INCLUDE, [111, 222, 333], NAMES)
        b = UserFilter.make(MODE_INCLUDE, [111, 222, 444], NAMES)
        assert a.name_part() != b.name_part()

    def test_same_set_is_stable(self):
        """Один и тот же набор всегда даёт одно имя — иначе плодятся дубли."""
        a = UserFilter.make(MODE_INCLUDE, [111, 222, 333], NAMES)
        b = UserFilter.make(MODE_INCLUDE, [333, 111, 222], NAMES)
        assert a.name_part() == b.name_part()

    def test_hash_is_four_chars(self):
        uf = UserFilter.make(MODE_EXCLUDE, [111, 222], NAMES)
        assert len(uf.hash4()) == 4

    def test_hash_ignores_names(self):
        """Хеш считается от ID: переименование участника не меняет имя файла."""
        a = UserFilter.make(MODE_EXCLUDE, [111, 222], NAMES)
        b = UserFilter.make(MODE_EXCLUDE, [111, 222], {111: "Другое", 222: "Имя"})
        assert a.hash4() == b.hash4()

    def test_modes_do_not_collide(self):
        a = UserFilter.make(MODE_INCLUDE, [111, 222], NAMES)
        b = UserFilter.make(MODE_EXCLUDE, [111, 222], NAMES)
        assert a.name_part() != b.name_part()


# ──────────────────────────────────────────────────────────────────────────────
# Строка шапки документа
# ──────────────────────────────────────────────────────────────────────────────

class TestHeaderLine:
    def test_no_filter_gives_empty(self):
        assert NO_FILTER.header_line() == ""

    def test_include_lists_names(self):
        uf = UserFilter.make(MODE_INCLUDE, [111, 222], NAMES)
        line = uf.header_line()
        assert line.startswith("Только выбранные участники:")
        assert "Мария Петрова" in line
        assert "Иван Соколов" in line

    def test_exclude_lists_names(self):
        uf = UserFilter.make(MODE_EXCLUDE, [111], NAMES)
        assert uf.header_line() == "Исключены из выгрузки: Мария Петрова"

    def test_long_list_is_truncated(self):
        names = {i: f"Участник{i}" for i in range(1, 16)}
        uf = UserFilter.make(MODE_EXCLUDE, list(names), names)
        line = uf.header_line(max_names=3)
        assert "и ещё 12" in line

    def test_without_names_shows_count(self):
        uf = UserFilter.make(MODE_EXCLUDE, [111, 222])
        assert uf.header_line() == "Исключены из выгрузки: 2"

    def test_include_single_still_named(self):
        """В шапке имя есть всегда, даже когда в имени файла его нет."""
        uf = UserFilter.make(MODE_INCLUDE, [111], NAMES)
        assert "Мария Петрова" in uf.header_line()


# ──────────────────────────────────────────────────────────────────────────────
# Совместимость с шагами 1-6
# ──────────────────────────────────────────────────────────────────────────────

class TestBackwardCompatibility:
    def test_make_without_names_still_works(self):
        uf = UserFilter.make(MODE_EXCLUDE, [111])
        assert uf.is_hidden(111) is True
        assert uf.names == ()

    def test_names_do_not_affect_filtering(self):
        a = UserFilter.make(MODE_EXCLUDE, [111])
        b = UserFilter.make(MODE_EXCLUDE, [111], NAMES)
        assert a.is_hidden(111) == b.is_hidden(111)
        assert a.sql_ids() == b.sql_ids()

    def test_partial_names_do_not_crash(self):
        """Имя известно не для всех ID — не падаем."""
        uf = UserFilter.make(MODE_EXCLUDE, [111, 999], {111: "Мария Петрова"})
        assert uf.header_line()
        assert uf.name_part()
