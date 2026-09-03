# -*- coding: utf-8 -*-
"""
N-17 (B) — таблица постов канала: месяцы, без «Автора», ссылки ↗.
"""
import pytest

from core.database import DBManager
from features.export.knowledge_base import (
    KnowledgeBaseBuilder,
    _month_key,
    _tg_post_link,
)

CHAT_ID = -1002058687771


# ── помощники ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "iso,expected",
    [
        ("2026-08-07 10:00:00", "2026-08"),
        ("2026-08-07", "2026-08"),
        ("2026-08", "2026-08"),
        (None, "?"),
        ("", "?"),
        ("2026", "?"),
    ],
)
def test_month_key(iso, expected):
    assert _month_key(iso) == expected


def test_link_strips_the_minus_hundred_prefix():
    assert _tg_post_link(-1002058687771, 652) == "https://t.me/c/2058687771/652"


def test_link_handles_plain_negative_id():
    assert _tg_post_link(-12345, 7) == "https://t.me/c/12345/7"


@pytest.mark.parametrize(
    "chat_id,message_id",
    [(None, 1), (-100123, None), (0, 1), (-100123, 0)],
)
def test_link_needs_both_parts(chat_id, message_id):
    assert _tg_post_link(chat_id, message_id) is None


def test_link_matches_export_format():
    """
    Формат обязан совпадать с экспортом (generator._tg_message_link, I15),
    иначе оглавление и документы поведут в разные места.
    """
    from features.export.generator import _COL_CHAT_ID, _tg_message_link

    row = [None] * 20
    row[_COL_CHAT_ID] = CHAT_ID
    from features.export.generator import (
        _COL_IS_COMMENT,
        _COL_MESSAGE_ID,
        _COL_POST_ID,
    )
    row[_COL_MESSAGE_ID] = 652
    row[_COL_IS_COMMENT] = 0
    row[_COL_POST_ID] = None

    assert _tg_post_link(CHAT_ID, 652) == _tg_message_link(row)


# ── таблица ───────────────────────────────────────────────────────────


@pytest.fixture
def channel(tmp_path):
    with DBManager(str(tmp_path / "p.db")) as db:
        db.insert_chat(chat_id=CHAT_ID, title="Канал", chat_type="channel")
        posts = [
            (1, "2026-06-10 10:00:00", "Июньский пост про дренаж участка"),
            (2, "2026-07-03 10:00:00", "Июльский пост про плитку на террасе"),
            (3, "2026-07-20 10:00:00", "Ещё июльский про освещение террасы"),
            (4, "2026-08-07 10:00:00", "Августовский про растения в тени"),
        ]
        for mid, date, text in posts:
            db.insert_message(chat_id=CHAT_ID, message_id=mid, date=date,
                              user_id=999, username="Канал", text=text,
                              is_comment=0)
        yield db, tmp_path


def _index(db, out):
    KnowledgeBaseBuilder(db=db, output_dir=str(out)).build(
        chat_id=CHAT_ID, chat_title="Канал", period_label="alltime",
        exported_files=[])
    return (out / "00_Оглавление.md").read_text(encoding="utf-8")


def test_author_column_is_gone(channel):
    content = _index(*channel)
    assert "| Автор |" not in content
    assert "| № | Дата | О чём | Файлы | ↗ |" in content


def test_months_become_subheadings(channel):
    content = _index(*channel)
    for month in ("### 2026-06", "### 2026-07", "### 2026-08"):
        assert month in content


def test_months_are_chronological(channel):
    content = _index(*channel)
    assert (
        content.index("### 2026-06")
        < content.index("### 2026-07")
        < content.index("### 2026-08")
    )


def test_numbering_is_continuous_across_months(channel):
    """
    Номер поста используют как ссылку в разговоре — он не должен
    сбрасываться на каждом месяце.
    """
    content = _index(*channel)
    for n in (1, 2, 3, 4):
        assert f"| {n} | 2026-" in content


def test_every_post_has_a_link(channel):
    content = _index(*channel)
    for mid in (1, 2, 3, 4):
        assert f"[↗](https://t.me/c/2058687771/{mid})" in content


def test_header_repeats_in_every_month_block(channel):
    """Таблица разрезана на блоки — каждому нужна своя шапка."""
    content = _index(*channel)
    assert content.count("| № | Дата | О чём | Файлы | ↗ |") == 3
