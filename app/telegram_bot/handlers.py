from aiogram.types import Message
from app.db.mongo import users, conversations
from app.agent.chain import generate_greet_and_lang_agent_reply, generate_profile_agent_reply, generate_survey_agent_reply, generate_summary_agent_reply
import html
import json
from datetime import datetime, timezone
from typing import Tuple, Dict, Any

def _extract_text(message: Message) -> str:
    # Универсально тянем текст из text/caption, иначе пусто
    return message.text or message.caption or ""

def _now_utc():
    return datetime.now(timezone.utc)

async def _upsert_user_and_push_user_message(message: Message) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    now = _now_utc()
    u = message.from_user
    if not u:
        return {}, {}

    telegram_id = u.id
    first_name = u.first_name or ""
    last_name = u.last_name or ""
    username = u.username or ""
    language_code = getattr(u, "language_code", None)
    text = _extract_text(message)

    # Получаем текущий stage (по умолчанию language)
    conv = conversations.find_one({"user_id": telegram_id}, {"stage": 1})
    stage = conv.get("stage") if conv and "stage" in conv else "language"

    # USERS: создаём при первом появлении и обновляем на каждый апдейт
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
    user_doc = users.find_one({"telegram_id": telegram_id}, {"_id": 0}) or {}

    # CONVERSATIONS: создаём запись диалога (без поля messages в $setOnInsert!) и пушим входящий месседж
    conversations.update_one(
        {"user_id": telegram_id},
        {
            "$setOnInsert": {
                "user_id": telegram_id,
                "created_at": now,
                "title": f"Dialog with {username or first_name or telegram_id}",
            },
            "$push": {
                "messages": {
                    "role": "user",
                    "text": text,
                    "ts": now,
                    "message_id": message.message_id,
                    "chat_id": message.chat.id if message.chat else None,
                    "stage": stage,
                }
            },
            "$set": {"updated_at": now},
        },
        upsert=True,
    )
    conversation_doc = conversations.find_one({"user_id": telegram_id}, {"_id": 0}) or {}
    return user_doc, conversation_doc

async def _delete_user_and_conversation(telegram_id: int):
    users.delete_one({"telegram_id": telegram_id})
    conversations.delete_one({"user_id": telegram_id})

def _push_assistant_message(user_id: int, text: str):
    now = _now_utc()
    # Получаем текущий stage (по умолчанию language)
    conv = conversations.find_one({"user_id": user_id}, {"stage": 1})
    stage = conv.get("stage") if conv and "stage" in conv else "language"
    conversations.update_one(
        {"user_id": user_id},
        {
            "$push": {
                "messages": {
                    "role": "assistant",
                    "text": text,
                    "ts": now,
                    "stage": stage,
                }
            },
            "$set": {"updated_at": now},
        },
        upsert=True,  # на всякий случай (если конкурентно создаётся)
    )

from app.telegram_bot.bot import dp
try:
    from aiogram.exceptions import CancelHandler
except ImportError:
    CancelHandler = None

@dp.message(lambda message: message.text and message.text.strip() == "/reset")
async def on_reset_command(message: Message):
    u = message.from_user
    if not u:
        await message.answer("Пользователь не найден.")
        if CancelHandler:
            raise CancelHandler()
        return
    telegram_id = u.id
    await _delete_user_and_conversation(telegram_id)
    await message.answer("Your data has been reset. The conversation will start over. Send any message to start.")
    if CancelHandler:
        raise CancelHandler()
    return

@dp.message()
async def on_any_message(message: Message):
    try:
        # 1) Сохраняем пользователя и входящее сообщение
        user_doc, conversation_doc = await _upsert_user_and_push_user_message(message)
        stage = conversation_doc.get("stage", "language")
        if stage == "language":
            agent_reply = await generate_greet_and_lang_agent_reply(user_doc, conversation_doc)
        elif stage == "profile":
            agent_reply = await generate_profile_agent_reply(user_doc, conversation_doc)
        elif stage == "survey":
            agent_reply = await generate_survey_agent_reply(user_doc, conversation_doc)
        elif stage == "summary":
            agent_reply = await generate_summary_agent_reply(user_doc, conversation_doc)
        elif stage == "final":
            # Always reply with the saved final_message in user's preferred language
            agent_reply = user_doc.get("final_message") or "You are in the queue for the service, we will contact you."
        else:
            agent_reply = "Что бы вы хотели обсудить?"
        _push_assistant_message(user_doc["telegram_id"], agent_reply)
        safe_reply = html.escape(agent_reply)
        await message.answer(safe_reply)
    except Exception as e:
        print(f"[BOT ERROR] {type(e).__name__}: {e}")
        await message.answer(f"⚠️ Error: <code>{type(e).__name__}: {str(e)}</code>")
        raise
