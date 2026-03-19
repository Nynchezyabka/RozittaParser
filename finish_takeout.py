"""
finish_takeout.py — принудительно завершает зависшую Takeout-сессию Telegram.

Запуск:
    python finish_takeout.py
"""

import asyncio
import os
from pathlib import Path
from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.tl.functions.account import FinishTakeoutSessionRequest

load_dotenv()

API_ID   = int(os.getenv("TG_API_ID", "0"))
API_HASH = os.getenv("TG_API_HASH", "")

# Используем ту же сессию что и основное приложение
SESSION = str(Path(__file__).parent / "telegram_session_modern")


async def main():
    client = TelegramClient(
        session=SESSION,
        api_id=API_ID,
        api_hash=API_HASH,
        device_model="Rozitta Parser Desktop",
        system_version="Windows 11",
    )
    await client.connect()

    if not await client.is_user_authorized():
        print("❌ Сессия не авторизована. Запустите основное приложение и войдите.")
        return

    me = await client.get_me()
    print(f"✅ Подключено как: {me.first_name} (@{me.username or '—'})")

    try:
        await client(FinishTakeoutSessionRequest(success=False))
        print("✅ Takeout-сессия успешно завершена.")
        print("   Теперь можно снова использовать Takeout API в приложении.")
    except Exception as e:
        if "NO_TAKEOUT_IN_PROGRESS" in str(e):
            print("ℹ️ Активных Takeout-сессий нет — всё в порядке.")
        else:
            print(f"⚠️ Ошибка: {e}")
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
