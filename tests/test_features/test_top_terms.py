# -*- coding: utf-8 -*-
"""
N-17 (A) — раздел «О чём этот архив».

Частотный срез считается детерминированно, без модели и без сети.
Проверяется сама функция извлечения и её попадание в оглавление и паспорт.
"""
import json

import pytest

from core.database import DBManager
from features.export.knowledge_base import (
    KnowledgeBaseBuilder,
    _looks_like_word,
    extract_top_terms,
)

CHAT_ID = -1001234567890


# ── extract_top_terms ─────────────────────────────────────────────────


def test_counts_and_orders_by_frequency():
    texts = ["дренаж дренаж плитка"] * 3
    assert extract_top_terms(texts, min_freq=1) == [("дренаж", 6), ("плитка", 3)]


def test_ties_broken_alphabetically():
    """Порядок не должен зависеть от порядка чтения из БД."""
    forward = extract_top_terms(["плитка дренаж"] * 5, min_freq=1)
    backward = extract_top_terms(["дренаж плитка"] * 5, min_freq=1)
    assert forward == backward == [("дренаж", 5), ("плитка", 5)]


def test_stopwords_are_dropped():
    texts = ["который который который дренаж дренаж дренаж"]
    assert extract_top_terms(texts, min_freq=1) == [("дренаж", 3)]


def test_short_and_long_words_are_dropped():
    """Границы длины: 6–18 символов включительно."""
    texts = ["сад " * 9 + "дренаж " * 9 + "сельскохозяйственнейший " * 9]
    words = [w for w, _ in extract_top_terms(texts, min_freq=1)]
    assert "дренаж" in words
    assert "сад" not in words
    assert "сельскохозяйственнейший" not in words


def test_digits_and_punctuation_are_not_terms():
    texts = ["2026-08-07 https://t.me/c/123/456 дренаж дренаж"]
    assert extract_top_terms(texts, min_freq=1) == [("дренаж", 2)]


def test_case_is_folded():
    assert extract_top_terms(["Дренаж ДРЕНАЖ дренаж"], min_freq=1) == [("дренаж", 3)]


def test_limit_is_respected():
    texts = ["дренаж плитка растения освещение террасы"]
    assert len(extract_top_terms(texts, limit=2, min_freq=1)) == 2


def test_min_freq_filters_rare_words():
    texts = ["дренаж " * 5 + "плитка"]
    assert extract_top_terms(texts, min_freq=5) == [("дренаж", 5)]


def test_falls_back_when_nothing_meets_min_freq():
    """Маленький архив: лучше показать что-то, чем пустой раздел."""
    assert extract_top_terms(["дренаж плитка"], min_freq=100) == [
        ("дренаж", 1),
        ("плитка", 1),
    ]


@pytest.mark.parametrize("texts", [[], [""], ["   "], ["... 2026 ..."]])
def test_empty_input_gives_empty_result(texts):
    assert extract_top_terms(texts) == []


def test_word_forms_are_counted_separately():
    """
    Словоформы не склеиваются — так же ведёт себя токенизатор
    Библиотекаря, на который срез равняется. Зафиксировано осознанно.
    """
    result = dict(extract_top_terms(["террасы террасе террасы"], min_freq=1))
    assert result == {"террасы": 2, "террасе": 1}


# ── _looks_like_word ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    "term,expected",
    [
        ("дренаж", True),
        ("освещение", True),
        ("вздрогнув", True),          # 4 согласных подряд — на границе
        ("бабушкадействительно", True),   # склейку ловит лимит длины, не эвристика
        ("вздрсгнув", False),         # 5 согласных подряд
        ("ааааааа", False),           # только гласные
        ("бвгджзк", False),           # только согласные
    ],
)
def test_looks_like_word(term, expected):
    assert _looks_like_word(term) is expected


# ── интеграция: оглавление и паспорт ──────────────────────────────────


@pytest.fixture
def archive(tmp_path):
    db_path = tmp_path / "parser.db"
    with DBManager(str(db_path)) as db:
        db.insert_chat(chat_id=CHAT_ID, title="Сад", chat_type="channel")
        for i in range(1, 9):
            db.insert_message(
                chat_id=CHAT_ID,
                message_id=i,
                date=f"2026-08-{i:02d} 10:00:00",
                user_id=555,
                username="Садовник",
                text="дренаж террасы и плитка, дренаж обязателен",
                is_comment=0,
            )
        # Комментарии не должны попасть в срез.
        for i in range(100, 140):
            db.insert_message(
                chat_id=CHAT_ID,
                message_id=i,
                date="2026-08-09 10:00:00",
                user_id=777,
                text="спасибоспасибо болтовня болтовня болтовня",
                is_comment=1,
                post_id=1,
            )
        yield db, tmp_path


def test_index_has_section_and_ignores_comments(archive, tmp_path):
    db, out = archive
    builder = KnowledgeBaseBuilder(db=db, output_dir=str(out))
    builder.build(chat_id=CHAT_ID, chat_title="Сад", period_label="alltime",
                  exported_files=[])

    index = (out / "00_Оглавление.md").read_text(encoding="utf-8")
    assert "## О чём этот архив" in index
    assert "дренаж" in index
    assert "болтовня" not in index, "комментарии не должны попадать в срез"


def test_section_precedes_chronology(archive, tmp_path):
    db, out = archive
    KnowledgeBaseBuilder(db=db, output_dir=str(out)).build(
        chat_id=CHAT_ID, chat_title="Сад", period_label="alltime",
        exported_files=[])

    index = (out / "00_Оглавление.md").read_text(encoding="utf-8")
    assert index.index("## О чём этот архив") < index.index("## Посты канала")


def test_passport_carries_machine_readable_terms(archive, tmp_path):
    db, out = archive
    KnowledgeBaseBuilder(db=db, output_dir=str(out)).build(
        chat_id=CHAT_ID, chat_title="Сад", period_label="alltime",
        exported_files=[])

    passport = json.loads(
        (out / "archive_passport.json").read_text(encoding="utf-8")
    )
    terms = passport["top_terms"]
    assert terms and all({"term", "count"} <= set(t) for t in terms)
    assert terms[0]["term"] == "дренаж"


def test_media_only_archive_skips_section(tmp_path):
    """Пустой заголовок хуже отсутствия раздела."""
    with DBManager(str(tmp_path / "p.db")) as db:
        db.insert_chat(chat_id=CHAT_ID, title="Фото", chat_type="channel")
        db.insert_message(chat_id=CHAT_ID, message_id=1,
                          date="2026-08-01 10:00:00", user_id=1,
                          file_type="photo", is_comment=0)
        KnowledgeBaseBuilder(db=db, output_dir=str(tmp_path)).build(
            chat_id=CHAT_ID, chat_title="Фото", period_label="alltime",
            exported_files=[])

    index = (tmp_path / "00_Оглавление.md").read_text(encoding="utf-8")
    assert "## О чём этот архив" not in index
