# -*- coding: utf-8 -*-
"""
N-2 — период в имени файла считается по фактическому охвату среза.

Ключевой тест — test_two_alltime_runs_get_different_names: он краснеет
на коде до патча, где метка «за всё время» была константой и вторая
выгрузка затирала первую.
"""
import pytest

from core.database import DBManager
from features.export.filters import MODE_EXCLUDE, MODE_INCLUDE, NO_FILTER, UserFilter
from features.export.ui import (
    ExportParams,
    PERIOD_ALLTIME,
    _iso_day,
    _resolve_period_label,
)

CHAT_ID = -1001234567890
ALICE = 111
BOB = 222


def _msg(db, mid, date, *, user_id=ALICE, topic_id=None, is_comment=0, post_id=None):
    db.insert_message(
        chat_id=CHAT_ID,
        message_id=mid,
        date=date,
        user_id=user_id,
        topic_id=topic_id,
        is_comment=is_comment,
        post_id=post_id,
        text=f"msg {mid}",
    )


@pytest.fixture
def db(tmp_path):
    with DBManager(str(tmp_path / "t.db")) as conn:
        _msg(conn, 1, "2023-10-06 05:37:00")
        _msg(conn, 2, "2024-05-01 12:00:00", user_id=BOB)
        _msg(conn, 3, "2026-08-01 09:15:00")
        _msg(conn, 4, "2026-09-30 10:00:00", topic_id=7)
        _msg(conn, 5, "2027-01-15 08:00:00", is_comment=1, post_id=3)
        yield conn


def _params(**kw):
    base = dict(chat_id=CHAT_ID, chat_title="Тест", period_label=PERIOD_ALLTIME)
    base.update(kw)
    return ExportParams(**base)


# ── _iso_day ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "value,expected",
    [
        ("2023-10-06 05:37:00", "2023-10-06"),
        ("2023-10-06", "2023-10-06"),
        (None, None),
        ("", None),
        ("2023-10", None),
        ("не дата вовсе", None),
    ],
)
def test_iso_day(value, expected):
    assert _iso_day(value) == expected


# ── get_coverage: срез ────────────────────────────────────────────────


def test_coverage_full_chat(db):
    assert db.get_coverage(CHAT_ID) == ("2023-10-06 05:37:00", "2026-09-30 10:00:00")


def test_coverage_excludes_comments_by_default(db):
    """Комментарий 2027 года не попадает, пока include_comments=False."""
    _, date_max = db.get_coverage(CHAT_ID)
    assert date_max == "2026-09-30 10:00:00"


def test_coverage_with_comments_is_wider(db):
    assert db.get_coverage(CHAT_ID, include_comments=True)[1] == "2027-01-15 08:00:00"


def test_coverage_narrows_by_topic(db):
    assert db.get_coverage(CHAT_ID, topic_id=7) == (
        "2026-09-30 10:00:00",
        "2026-09-30 10:00:00",
    )


def test_coverage_narrows_by_user(db):
    assert db.get_coverage(CHAT_ID, user_ids=[BOB]) == (
        "2024-05-01 12:00:00",
        "2024-05-01 12:00:00",
    )


def test_coverage_empty_slice(db):
    assert db.get_coverage(CHAT_ID, user_ids=[999999]) == (None, None)


# ── метка ─────────────────────────────────────────────────────────────


def test_label_gets_actual_coverage(db):
    assert (
        _resolve_period_label(db, _params())
        == "alltime_2023-10-06_to_2026-09-30"
    )


def test_label_follows_topic_filter(db):
    label = _resolve_period_label(db, _params(topic_id=7))
    assert label == "alltime_2026-09-30_to_2026-09-30"


def test_include_filter_narrows_label(db):
    """Режим «только выбранные» режется в SQL — охват сужается вместе с ним."""
    label = _resolve_period_label(db, _params(user_filter=UserFilter.make(MODE_INCLUDE, [BOB])))
    assert label == "alltime_2024-05-01_to_2024-05-01"


def test_exclude_filter_does_not_narrow_label(db):
    """
    Режим «кроме выбранных» строки не режет — они доходят до рендера
    заглушкой, значит их даты законно остаются в охвате.
    """
    label = _resolve_period_label(db, _params(user_filter=UserFilter.make(MODE_EXCLUDE, [BOB])))
    assert label == "alltime_2023-10-06_to_2026-09-30"


def test_requested_period_is_left_alone(db):
    """Решение 3а: выгрузка с заданными датами метку не меняет."""
    p = _params(period_label="2024-01-01_to_2024-03-31")
    assert _resolve_period_label(db, p) == "2024-01-01_to_2024-03-31"


def test_empty_slice_keeps_label(db):
    p = _params(user_filter=UserFilter.make(MODE_INCLUDE, [999999]))
    assert _resolve_period_label(db, p) == PERIOD_ALLTIME


def test_no_filter_is_default(db):
    assert _params().user_filter is NO_FILTER


# ── регрессия N-2 ─────────────────────────────────────────────────────


def test_two_alltime_runs_get_different_names(db):
    """
    Две выгрузки «за всё время»: между ними в архив дописан свежий день.
    Имена обязаны разойтись — иначе вторая затрёт первую, а для чата
    с автоудалением восстановить будет нечего.

    Краснеет на коде до патча: там метка была константой.
    """
    first = _resolve_period_label(db, _params())

    _msg(db, 6, "2026-10-15 07:00:00")
    second = _resolve_period_label(db, _params())

    assert first != second
    assert first == "alltime_2023-10-06_to_2026-09-30"
    assert second == "alltime_2023-10-06_to_2026-10-15"
