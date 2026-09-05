"""
core/components/ — подсистема загружаемых компонентов.

Тяжёлые ML-функции не помещаются в основной exe, поэтому живут отдельными
сборками, которые приложение качает по требованию и вызывает как
subprocess. Спецификация — COMPONENTS.md в корне репозитория.

Здесь только чистый Python: ни Qt, ни доступа к БД Розитты. Вызывается из
QThread-воркера, поэтому синхронный и блокирующий — это нормально.
"""

from core.components.manager import ComponentManager, InstalledComponent

__all__ = ["ComponentManager", "InstalledComponent"]
