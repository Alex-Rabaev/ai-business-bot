import os
from typing import Dict, Any, List
from openai import OpenAI
from app.config import settings
from app.db.mongo import users
import inspect

openai_client = OpenAI(api_key=settings.OPENAI_API_KEY)

PROMPT_PATH = os.path.join(os.path.dirname(__file__), "prompts", "greeting_and_lang.md")
def _load_prompt():
    with open(PROMPT_PATH, encoding="utf-8") as f:
        return f.read()

SYSTEM_PROMPT = _load_prompt()

# Описание функции для function calling
update_user_language_schema = {
    "name": "update_user_language",
    "description": "Update the user's preferred language (language_code) by telegram_id.",
    "parameters": {
        "type": "object",
        "properties": {
            "telegram_id": {"type": "integer", "description": "Telegram user ID"},
            "language_code": {"type": "string", "description": "Preferred language code (e.g., 'en', 'ru')"}
        },
        "required": ["telegram_id", "language_code"]
    }
}

def second_agent_stub(*args, **kwargs):
    return "In development"

def _build_llm_messages(user_doc: Dict[str, Any], history: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """
    Конвертируем нашу историю из Mongo в формат messages для Chat Completions API.
    - "role": "system" — системная инструкция.
    - далее пары user/assistant в хронологии (берём последние 20-30, чтобы не раздувать контекст).
    """
    msgs: List[Dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]

    # Опционально подскажем контекст о пользователе (если уже знаем)
    hints = []
    if user_doc:
        for k in ("first_name", "last_name", "username", "language_code"):
            v = user_doc.get(k)
            if v:
                hints.append(f"{k}={v}")
    if hints:
        msgs.append({"role": "system", "content": "Known user hints: " + ", ".join(hints)})

    # Прикладываем недавнюю историю (до 20 сообщений) в виде user/assistant
    recent = history[-20:] if history else []
    for m in recent:
        role = m.get("role", "user")
        text = m.get("text", "")
        if not isinstance(text, str):
            text = str(text)
        # Маппим роли из нашей схемы в роли OpenAI
        if role not in ("user", "assistant"):
            role = "user"
        msgs.append({"role": role, "content": text})

    return msgs

async def generate_agent_reply(user_doc: Dict[str, Any], conversation_doc: Dict[str, Any]) -> str:
    """
    Генерирует ответ агента с поддержкой function calling.
    Если AI вызывает функцию update_user_language, обновляет пользователя и передаёт управление второму агенту.
    """
    messages = _build_llm_messages(user_doc, conversation_doc.get("messages", []))
    functions = [update_user_language_schema]
    telegram_id = user_doc.get("telegram_id")

    resp = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        temperature=0.7,
        max_tokens=220,
        functions=functions,
        function_call="auto",
    )
    choice = resp.choices[0]
    msg = choice.message

    if getattr(msg, "function_call", None):
        fn = msg.function_call
        print(f"[function_call] AI requested function: {fn.name}, arguments: {fn.arguments}")
        if fn.name == "update_user_language":
            import json
            args = json.loads(fn.arguments)
            # Всегда используем telegram_id из user_doc, игнорируя тот, что пришёл от AI
            args["telegram_id"] = telegram_id
            print(f"[function_call] Final args for update_user_language: {args}")
            update_user_language(**args)
            # После обновления языка — передаём управление второму агенту
            return second_agent_stub()
        else:
            return f"[Unknown function call: {fn.name}]"
    else:
        content = msg.content or "What is your name?"
        return content.strip()

def update_user_language(telegram_id: int, language_code: str) -> bool:
    print(f"[update_user_language] Called with telegram_id={telegram_id}, language_code={language_code}")
    result = users.update_one({"telegram_id": telegram_id}, {"$set": {"language_code": language_code}})
    print(f"[update_user_language] Modified count: {result.modified_count}")
    return result.modified_count > 0
