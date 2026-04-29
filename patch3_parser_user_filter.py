"""
PATCH 3 — features/parser/api.py
Задача: добавить фильтрацию по user_ids в _get_post_replies,
чтобы при парсинге «посты + комментарии» с фильтром участника
скачивались только комментарии нужного человека.

Run: python patch3_parser_user_filter.py
"""


PATH = "features/parser/api.py"

with open(PATH, encoding="utf-8") as f:
    src = f.read()
original = src

# ── PATCH 3-A: добавить user_ids в сигнатуру _get_post_replies ──────────────

OLD_SIG = (
    "    async def _get_post_replies(\n"
    "        self,\n"
    "        channel_id:     int,\n"
    "        post_id:        int,\n"
    "        linked_chat_id: int,\n"
    "        media_filter:   Optional[List[str]],\n"
    "        topic_id:       Optional[int] = None,\n"
    "        limit:          int           = MAX_COMMENT_LIMIT,\n"
    "        insert_fn:      Optional[Callable] = None,\n"
    "    ) -> int:"
)

NEW_SIG = (
    "    async def _get_post_replies(\n"
    "        self,\n"
    "        channel_id:     int,\n"
    "        post_id:        int,\n"
    "        linked_chat_id: int,\n"
    "        media_filter:   Optional[List[str]],\n"
    "        topic_id:       Optional[int]      = None,\n"
    "        limit:          int                = MAX_COMMENT_LIMIT,\n"
    "        insert_fn:      Optional[Callable] = None,\n"
    "        user_ids:       Optional[List[int]] = None,\n"
    "    ) -> int:"
)

if OLD_SIG not in src:
    print("WARN: PATCH 3-A (signature) not found — проверьте строку")
else:
    src = src.replace(OLD_SIG, NEW_SIG, 1)
    print("OK: PATCH 3-A applied (_get_post_replies signature)")

# ── PATCH 3-B: добавить фильтр user_ids в цикл комментариев ─────────────────

OLD_LOOP = (
    "                async for comment in self._client.iter_messages(\n"
    "                    group_peer,\n"
    "                    reply_to = root_id,\n"
    "                    limit    = limit,\n"
    "                ):\n"
    "                    row, media_err = await self._process_message(\n"
    "                        message      = comment,"
)

NEW_LOOP = (
    "                async for comment in self._client.iter_messages(\n"
    "                    group_peer,\n"
    "                    reply_to = root_id,\n"
    "                    limit    = limit,\n"
    "                ):\n"
    "                    # Фильтр по участнику — пропускаем чужие комментарии\n"
    "                    if user_ids and comment.sender_id not in user_ids:\n"
    "                        continue\n"
    "                    row, media_err = await self._process_message(\n"
    "                        message      = comment,"
)

if OLD_LOOP not in src:
    print("WARN: PATCH 3-B (loop filter) not found")
else:
    src = src.replace(OLD_LOOP, NEW_LOOP, 1)
    print("OK: PATCH 3-B applied (user_ids filter in comment loop)")

# ── PATCH 3-C: найти вызов _get_post_replies и передать user_ids ─────────────
# Ищем место вызова через regex — сигнатура вызова может варьироваться

OLD_CALL = (
    "                    downloaded = await self._get_post_replies(\n"
    "                        channel_id     = normalized_id,\n"
    "                        post_id        = post_id,\n"
    "                        linked_chat_id = linked_chat_id,\n"
    "                        media_filter   = params.media_filter,\n"
    "                        topic_id       = params.topic_id,\n"
    "                        insert_fn      = insert_fn,\n"
    "                    )"
)
NEW_CALL = (
    "                    downloaded = await self._get_post_replies(\n"
    "                        channel_id     = normalized_id,\n"
    "                        post_id        = post_id,\n"
    "                        linked_chat_id = linked_chat_id,\n"
    "                        media_filter   = params.media_filter,\n"
    "                        topic_id       = params.topic_id,\n"
    "                        insert_fn      = insert_fn,\n"
    "                        user_ids       = params.user_ids,\n"
    "                    )"
)

if OLD_CALL not in src:
    print("WARN: PATCH 3-C (call site) not found")
else:
    src = src.replace(OLD_CALL, NEW_CALL, 1)
    print("OK: PATCH 3-C applied (user_ids=params.user_ids added to call site)")

# ── Запись ───────────────────────────────────────────────────────────────────
if src != original:
    with open(PATH, "w", encoding="utf-8") as f:
        f.write(src)
    print(f"\n✅ Сохранено: {PATH}")
else:
    print("\n⚠️ Файл не изменён — все патчи уже применены или не найдены")
