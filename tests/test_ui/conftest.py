"""
tests/test_ui/conftest.py

Общие фикстуры для UI-тестов: QApplication, тестовые данные.
"""
import sys
import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    """QApplication на всю сессию тестов (один экземпляр)."""
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app
