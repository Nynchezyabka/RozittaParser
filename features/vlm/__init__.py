"""
features/vlm/ — описание изображений на стороне приложения.

Здесь то, что делает Розитта вокруг компонента: собирает задание, разбирает
результат, кладёт описания в БД и — главное — обрамляет ответ модели, прежде
чем тот попадёт в документ.

Сам компонент живёт в component_vlm/ и сюда не импортируется: у него своё
окружение и свой цикл выпуска. Связь — только через протокол (COMPONENTS.md).
"""

from features.vlm.api import (
    IMAGE_MARK,
    frame_for_html,
    frame_for_markdown,
    sanitize_description,
)

__all__ = [
    "IMAGE_MARK",
    "frame_for_html",
    "frame_for_markdown",
    "sanitize_description",
]
