# -*- coding: utf-8 -*-
"""
Чип распознавания действительно рисует выделение.

Проверка по пикселям, а не по таблице стилей: строка стилей у ChipButton
была корректной всё время — заливка и рамка не рисовались из-за того, что
голый QWidget внутри layout игнорирует background-color без
WA_StyledBackground. Проверка вида «в styleSheet() есть нужный цвет»
проходила бы зелёной при полностью невидимом выделении.

Пиксели НЕ берутся по фиксированным координатам: ширина глифов и метрики
шрифта разные на разных системах, и точка, попавшая в заливку на одной
машине, попадёт в эмодзи на другой (именно так этот тест и падал с
#bebebe). Вместо этого считается гистограмма цветов по площади виджета —
заливка занимает большую часть пилюли независимо от шрифта.

Виджет намеренно кладётся внутрь родителя: у окна верхнего уровня фон
рисуется и без атрибута, поэтому в отдельной проверке дефект не
воспроизводится.
"""
from collections import Counter

import pytest
from PySide6.QtWidgets import QHBoxLayout, QWidget

from core.ui_shared.styles import ACCENT_ORANGE, ACCENT_SOFT_ORANGE
from core.ui_shared.widgets import ChipButton, MediaButton

HOST_BG = "#101010"  # заведомо не совпадает ни с одним цветом темы


def _render(widget):
    """Кладёт виджет в родителя с известным фоном и отрисовывает."""
    host = QWidget()
    host.setStyleSheet(f"background:{HOST_BG};")
    layout = QHBoxLayout(host)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(widget)
    layout.addStretch(1)
    host.resize(400, 60)
    host.show()
    return host.grab().toImage(), widget.geometry()


def _histogram(widget) -> Counter:
    """Цвета по площади виджета, от частого к редкому."""
    img, geo = _render(widget)
    counter: Counter = Counter()
    for y in range(geo.y(), geo.y() + geo.height()):
        for x in range(geo.x(), geo.x() + geo.width()):
            counter[img.pixelColor(x, y).name().lower()] += 1
    return counter


def _fill(widget) -> str:
    """Самый частый цвет — заливка."""
    return _histogram(widget).most_common(1)[0][0]


def _share(counter: Counter, color: str) -> float:
    total = sum(counter.values())
    return counter[color.lower()] / total if total else 0.0


# ── заливка и рамка ───────────────────────────────────────────────────


def test_active_chip_is_filled_with_soft_orange(qapp):
    """
    Регрессия: до исправления вся площадь чипа была цветом родителя —
    выделение не рисовалось вообще.
    """
    assert _fill(ChipButton("🎤", "Голос", "voice", True)) == ACCENT_SOFT_ORANGE.lower()


def test_active_chip_has_orange_border(qapp):
    counter = _histogram(ChipButton("🎤", "Голос", "voice", True))
    assert counter[ACCENT_ORANGE.lower()] > 0, "рамка не нарисована"


def test_active_chip_does_not_show_through(qapp):
    """
    Фон родителя допустим только по срезанным углам — если его много,
    значит чип себя не нарисовал.
    """
    counter = _histogram(ChipButton("🎤", "Голос", "voice", True))
    assert _share(counter, HOST_BG) < 0.10


def test_inactive_chip_is_not_orange(qapp):
    counter = _histogram(ChipButton("🎤", "Голос", "voice", False))
    assert counter.most_common(1)[0][0] != ACCENT_SOFT_ORANGE.lower()


def test_inactive_chip_still_paints_itself(qapp):
    """Выключенный чип тоже виден — своя заливка, не дырка в родителе."""
    counter = _histogram(ChipButton("🎤", "Голос", "voice", False))
    assert counter.most_common(1)[0][0] != HOST_BG


def test_chip_matches_media_tile_when_selected(qapp):
    """
    Два способа сказать «выбрано» на одном экране обязаны выглядеть
    одинаково — ради этого галочка и убиралась.
    """
    assert _fill(ChipButton("🎤", "Голос", "voice", True)) == _fill(
        MediaButton("📹", "Кружки", "video_note", True)
    )


# ── форма пилюли ──────────────────────────────────────────────────────


def test_corners_are_rounded(qapp):
    """
    Регрессия: радиус был задан числом 30, а Qt скругляет угол, только
    пока радиус не больше половины высоты. Ряд растягивал чип по высоте
    соседей, и угол становился прямым.
    """
    img, geo = _render(ChipButton("🎤", "Голос", "voice", True))
    corner = img.pixelColor(geo.x(), geo.y()).name().lower()
    assert corner == HOST_BG, "угол не срезан — скругления нет"


def test_left_edge_is_border_colour(qapp):
    """Середина левой кромки — на рамке в любой раскладке."""
    img, geo = _render(ChipButton("🎤", "Голос", "voice", True))
    edge = img.pixelColor(geo.x(), geo.y() + geo.height() // 2)
    assert edge.red() > 200 and edge.green() > 100 and edge.blue() < 60


def test_radius_is_half_the_height(qapp):
    """Условие, при котором Qt вообще рисует скругление."""
    assert ChipButton._PILL_R * 2 == ChipButton._PILL_H


def test_height_is_fixed(qapp):
    """
    Иначе ряд растягивает чип по высоте самого высокого соседа, и радиус
    снова перестаёт совпадать с половиной высоты.
    """
    chip = ChipButton("🎤", "Голос", "voice", True)
    host = QWidget()
    layout = QHBoxLayout(host)
    layout.addWidget(chip)
    host.resize(400, 200)
    host.show()
    assert chip.height() == ChipButton._PILL_H


# ── прямая проверка условия ───────────────────────────────────────────


@pytest.mark.parametrize("active", [True, False])
def test_styled_background_attribute_is_set(qapp, active):
    """
    Если пиксельные проверки однажды станут нестабильны на CI, причина
    дефекта останется закреплённой здесь.
    """
    from PySide6.QtCore import Qt

    chip = ChipButton("🎤", "Голос", "voice", active)
    assert chip.testAttribute(Qt.WidgetAttribute.WA_StyledBackground)
