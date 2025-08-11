from aiogram import Bot, Dispatcher
from aiogram.types import Message, Update
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from datetime import datetime, timezone
from typing import Tuple, Dict, Any
import json

from app.config import settings
from app.db.mongo import users, conversations  # <— твои коллекции из mongo.py

bot = Bot(
    token=settings.TG_BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher()


def _extract_text(message: Message) -> str:
    # Универсально тянем текст из text/caption, иначе пусто
    return message.text or message.caption or ""

async def _upsert_user_and_conversation(message: Message) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    now = datetime.now(timezone.utc)
    u = message.from_user
    if u is None:
        return {}, {}

    telegram_id = u.id
    first_name = u.first_name or ""
    last_name = u.last_name or ""
    username = u.username or ""
    language_code = getattr(u, "language_code", None)
    text = _extract_text(message)

    # ✅ FIX: Никакого пересечения полей между $setOnInsert и $set
    users.update_one(
        {"telegram_id": telegram_id},
        {
            "$setOnInsert": {
                "telegram_id": telegram_id,
                "created_at": now,
            },
            "$set": {
                "first_name": first_name,
                "last_name": last_name,
                "username": username,
                "language_code": language_code,
                "last_message_at": now,
                "last_message_text": text,
                "last_seen_at": now,
            },
        },
        upsert=True,
    )

    user_doc = users.find_one({"telegram_id": telegram_id}, {"_id": 0})

    # Для conversations поля тоже не пересекаем
    conversations.update_one(
        {"user_id": telegram_id},
        {
            "$setOnInsert": {
                "user_id": telegram_id,
                "created_at": now,
                "title": f"Dialog with {username or first_name or telegram_id}",
                # ⚠️ БЫЛО: "messages": [] — УБРАЛИ, чтобы не конфликтовать с $push
            },
            "$push": {
                "messages": {
                    "role": "user",
                    "text": text,
                    "ts": now,
                    "message_id": message.message_id,
                    "chat_id": message.chat.id if message.chat else None,
                }
            },
            "$set": {
                "updated_at": now
            },
        },
        upsert=True,
    )

    conversation_doc = conversations.find_one({"user_id": telegram_id}, {"_id": 0})
    return user_doc or {}, conversation_doc or {}


@dp.message()
async def on_any_message(message: Message):
    try:
        user_doc, conversation_doc = await _upsert_user_and_conversation(message)
        payload = {"user": user_doc, "conversation": conversation_doc}
        text = (
            "📄 <b>DB snapshot</b>\n"
            "Ниже актуальные данные из Mongo:\n\n"
            f"<pre><code class=\"language-json\">{json.dumps(payload, ensure_ascii=False, indent=2, default=str)}</code></pre>"
        )
        await message.answer(text)
    except Exception as e:
        # Чтобы webhook не падал 500-кой и было понятно, что случилось
        await message.answer(f"⚠️ DB error: <code>{type(e).__name__}: {str(e)}</code>")
        raise
