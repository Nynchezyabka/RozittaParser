"""
features/export/filters.py — фильтр участников для экспорта (FEAT-6).

Один переключатель режима, два взаимоисключающих поведения:

    "include" — в документ попадают ТОЛЬКО выбранные участники.
                Фильтруется на уровне SQL (get_messages(user_ids=...)),
                чужие сообщения не читаются из БД вообще.

    "exclude" — в документ попадают ВСЕ, но сообщения выбранных участников
                заменяются заглушкой. Фильтруется на уровне рендера:
                строка обязана дойти до генератора, иначе заглушку негде
                нарисовать и рвётся контекст ответов (reply_to).

Асимметрия намеренная: если бы "include" тоже рисовал заглушки, документ
при выборе одного человека распух бы до размера всего чата, где 95% строк —
заглушки.

Нет импортов Qt. Нет Telethon.

Публичный API:
    UserFilter(mode, ids)     — неизменяемый объект фильтра
    UserFilter.is_hidden(uid) — рисовать ли заглушку вместо сообщения
    UserFilter.sql_ids()      — список ID для get_messages(user_ids=...)
    NO_FILTER                 — синглтон «фильтр не задан»
"""

from __future__ import annotations

import hashlib

from dataclasses import dataclass, field
from typing import Dict, FrozenSet, Iterable, List, Optional, Tuple

from core.database import telegram_user_id_variants
from core.utils import sanitize_filename

# ── Режимы ────────────────────────────────────────────────────────────────────

MODE_NONE    = "none"
MODE_INCLUDE = "include"
MODE_EXCLUDE = "exclude"

_MODES = (MODE_NONE, MODE_INCLUDE, MODE_EXCLUDE)

# ── Вид заглушки ──────────────────────────────────────────────────────────────
# Показывать ли имя автора в заглушке скрытого сообщения.
# True  → "[14:32] Мария Петрова: Сообщение скрыто"  (читаемость диалога)
# False → "[14:32] Сообщение скрыто"
# ВНИМАНИЕ: False — это НЕ анонимизация. Имя всё равно видно в строках
# "в ответ на: ..." у чужих сообщений и в упоминаниях внутри текста.
PLACEHOLDER_SHOW_AUTHOR = True

PLACEHOLDER_TEXT       = "\U0001F6AB Сообщение скрыто"
PLACEHOLDER_MEDIA_TEXT = "\U0001F6AB Медиа скрыто"


# ── UserFilter ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class UserFilter:
    """
    Фильтр участников для одного запуска экспорта.

    Attributes:
        mode: "none" | "include" | "exclude".
        ids:  ID выбранных участников (в том виде, в каком их отдал UI).

    Каждый ID при создании разворачивается в bare+marked варианты
    (см. core.database.telegram_user_id_variants) — иначе канал-отправитель
    отфильтруется только в одной из двух форм записи (B1/B3).
    """

    mode:  str = MODE_NONE
    ids:   FrozenSet[int] = field(default_factory=frozenset)
    names: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.mode not in _MODES:
            raise ValueError(
                f"UserFilter: неизвестный режим {self.mode!r}, "
                f"допустимы {_MODES}"
            )
        object.__setattr__(self, "ids", frozenset(self.ids))

        expanded: set = set()
        for uid in self.ids:
            expanded.update(telegram_user_id_variants(uid))
        object.__setattr__(self, "_expanded", frozenset(expanded))

    # ── Фабрика ───────────────────────────────────────────────────────────────

    @classmethod
    def make(cls, mode: str, ids: Optional[Iterable[int]] = None,
             names: Optional[Dict[int, str]] = None) -> "UserFilter":
        """
        Создаёт фильтр; пустой список ID всегда даёт режим "none".

        Args:
            ids:   ID выбранных участников.
            names: {id: имя} — попадут в шапку документа и в имя файла.
                   Необязательны: без них останутся только счётчики.
        """
        ids_set = frozenset(int(i) for i in (ids or ()) if i)
        if not ids_set:
            return NO_FILTER
        names = names or {}
        ordered = tuple(names[i] for i in sorted(ids_set) if i in names)
        return cls(mode=mode, ids=ids_set, names=ordered)

    # ── Запросы ───────────────────────────────────────────────────────────────

    @property
    def is_active(self) -> bool:
        """True, если фильтр реально что-то меняет."""
        return self.mode != MODE_NONE and bool(self.ids)

    def matches(self, uid: Optional[int]) -> bool:
        """
        True → участник отмечен в списке фильтра.

        Предикат один на оба режима, а вот следствие разное: в "include"
        отмеченные остаются, в "exclude" — прячутся. Нужен отдельно от
        is_hidden(), потому что в режиме «по постам» include-фильтрация
        комментариев происходит на уровне рендера, а не в SQL: в SQL она
        вымыла бы вместе с чужими комментариями и сами посты, которые
        приходят от имени канала.

        Строки без отправителя (user_id IS NULL — служебные сообщения)
        не отмечены никогда.
        """
        if not self.is_active or uid is None:
            return False
        return uid in self._expanded

    def is_hidden(self, uid: Optional[int]) -> bool:
        """
        True → вместо сообщения рисуется заглушка.

        Только для режима "exclude". Строки без отправителя (user_id IS NULL —
        служебные сообщения) никогда не скрываются.
        """
        if self.mode != MODE_EXCLUDE:
            return False
        return self.matches(uid)

    def sql_ids(self) -> Optional[List[int]]:
        """
        Список ID для DBManager.get_messages(user_ids=...).

        Не None только для режима "include" — в "exclude" строки обязаны
        дойти до рендера. Возвращаются исходные ID: разворачивать в варианты
        будет сам get_messages().
        """
        if self.mode != MODE_INCLUDE or not self.ids:
            return None
        return sorted(self.ids)

    def label(self) -> str:
        """Человекочитаемая метка для лога."""
        if not self.is_active:
            return "все участники"
        word = "только" if self.mode == MODE_INCLUDE else "кроме"
        return f"{word} {len(self.ids)} чел."

    # ── Имя файла ─────────────────────────────────────────────────────────────

    def hash4(self) -> str:
        """
        Четыре шестнадцатеричных символа от набора ID.

        Нужны против молчаливой перезаписи: два разных набора из трёх человек
        дали бы одинаковое only_3_users и вторая выгрузка затёрла бы первую
        (правило I11 — разные настройки не должны давать одно имя файла).
        """
        raw = ",".join(str(i) for i in sorted(self.ids))
        # sha256, а не md5: хеш здесь — идентификатор набора ID для
        # имени файла, не защита, но md5 ловят сканеры безопасности.
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:4]

    def name_part(self) -> str:
        """
        Фрагмент имени файла без ведущего подчёркивания.

        Соглашение проекта: служебные слова английские (ср. threads, comments,
        fullchat), имена участников — данные, остаются как есть.

            include, 1 выбран   → ""  (имя уже подставит существующий user_part)
            include, 2 и больше → "only_3_users_7f2a"
            exclude, 1 выбран   → "except_Мария"
            exclude, 2 и больше → "except_2_users_7f2a"
        """
        if not self.is_active:
            return ""

        n = len(self.ids)

        if self.mode == MODE_INCLUDE:
            if n == 1:
                return ""
            return f"only_{n}_users_{self.hash4()}"

        if n == 1 and self.names:
            return f"except_{sanitize_filename(self.names[0])}"
        return f"except_{n}_users_{self.hash4()}"

    # ── Шапка документа ───────────────────────────────────────────────────────

    def header_line(self, max_names: int = 10) -> str:
        """
        Строка для шапки документа. Пустая строка — фильтра не было.

            "Только выбранные участники: Мария Петрова, Иван Соколов"
            "Исключены из выгрузки: Мария Петрова и ещё 4"

        Если имена не передавались в make(), выводится только количество.
        """
        if not self.is_active:
            return ""

        prefix = ("Только выбранные участники"
                  if self.mode == MODE_INCLUDE else "Исключены из выгрузки")
        n = len(self.ids)

        if not self.names:
            return f"{prefix}: {n}"

        shown = list(self.names[:max_names])
        rest = n - len(shown)
        listed = ", ".join(shown)
        if rest > 0:
            listed += f" и ещё {rest}"
        return f"{prefix}: {listed}"


# Синглтон «фильтр не задан» — безопасный дефолт везде, где фильтра нет.
NO_FILTER = UserFilter()
