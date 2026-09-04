# -*- coding: utf-8 -*-
"""
tests/test_core/test_dependencies.py

Обязательные зависимости установлены в том окружении, где идут тесты.

Зачем отдельный файл. Список для CI (`.github/workflows/requirements-test.txt`)
— не копия `requirements.txt`: тяжёлые faster-whisper и pyinstaller туда
сознательно не попадают. Из-за этого список живёт своей жизнью и однажды уже
разошёлся: `python-frontmatter` добавили в requirements.txt вместе с пресетом
«База знаний», в CI-список — нет. Результат — 19 падений на CI при зелёном
прогоне у всех локально, причём в логе это выглядело как поломка пресета,
а не как отсутствующий пакет.

Здесь та же поломка даёт один понятный тест вместо девятнадцати непонятных.

Опциональные зависимости (faster-whisper, opentele2, python-socks, simpleeval)
сюда НЕ добавлять: код обязан работать без них, а тест обязан быть зелёным
в окружении, где их нет.
"""
import importlib

import pytest

# (модуль для импорта, пакет в requirements, ради чего он нужен)
REQUIRED = [
    ("PySide6",     "PySide6",             "интерфейс"),
    ("telethon",    "Telethon",            "Telegram MTProto API"),
    ("docx",        "python-docx",         "экспорт в DOCX"),
    ("frontmatter", "python-frontmatter",  "YAML-шапки в MD (пресет «База знаний»)"),
]


@pytest.mark.parametrize("module,package,why", REQUIRED)
def test_required_dependency_importable(module, package, why):
    try:
        importlib.import_module(module)
    except ImportError as exc:
        pytest.fail(
            f"Не импортируется {module!r} ({why}).\n"
            f"Пакет {package} должен быть и в requirements.txt, "
            f"и в .github/workflows/requirements-test.txt.\n"
            f"Причина: {exc}"
        )
