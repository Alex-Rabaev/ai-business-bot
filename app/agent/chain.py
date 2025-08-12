from typing import Dict, Any, List
from openai import OpenAI
from app.config import settings
from app.db.mongo import users
import os
import json

openai_client = OpenAI(api_key=settings.OPENAI_API_KEY)

# Load system prompt from markdown file
_PROMPT_PATH = os.path.join(os.path.dirname(__file__), "prompts", "greeting_and_lang.md")
with open(_PROMPT_PATH, "r", encoding="utf-8") as f:
    BASE_SYSTEM_PROMPT = f.read().strip()

# Extra instruction to guide tool usage and handoff behavior
TOOL_USAGE_INSTRUCTION = (
    "\n\nTools: You may call the function set_user_language(language_code) when you are confident "
    "about the user's preferred dialogue language (use ISO short codes like 'en', 'ru', 'uk', 'de', 'es', etc.). "
    "After successfully calling the function, immediately hand off by replying with the fixed phrase: 'В процессе разработки'."
)

SYSTEM_PROMPT = BASE_SYSTEM_PROMPT + TOOL_USAGE_INSTRUCTION

# OpenAI tool (function) schema for updating user's language
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "set_user_language",
            "description": "Persist the user's preferred language code to the database (ISO 639-1 like 'en', 'ru', 'uk').",
            "parameters": {
                "type": "object",
                "properties": {
                    "language_code": {
                        "type": "string",
                        "description": "Two-letter language code inferred from the user's preference (e.g., 'en', 'ru', 'uk', 'de', 'es').",
                        "minLength": 2,
                        "maxLength": 5,
                    }
                },
                "required": ["language_code"],
                "additionalProperties": False,
            },
            "strict": True,
        },
    }
]


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


def _persist_language_code(telegram_id: int, language_code: str) -> None:
    users.update_one(
        {"telegram_id": telegram_id},
        {"$set": {"language_code": language_code}},
        upsert=False,
    )


async def generate_agent_reply(user_doc: Dict[str, Any], conversation_doc: Dict[str, Any]) -> str:
    """
    Вызывает OpenAI для генерации следующего короткого вопроса/реплики.
    Возвращает текст ассистента.
    Поддерживает function calling: если модель вызывает set_user_language, обновляем БД и отвечаем заглушкой.
    """
    messages = _build_llm_messages(user_doc, conversation_doc.get("messages", []))

    resp = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        temperature=0.7,
        max_tokens=220,
        tools=TOOLS,
        tool_choice="auto",
    )

    choice = resp.choices[0]
    msg = choice.message

    # Handle tool calls if any
    tool_calls = getattr(msg, "tool_calls", None) or []
    if tool_calls:
        for call in tool_calls:
            fn = call.function
            if not fn or fn.name != "set_user_language":
                continue
            try:
                args = json.loads(fn.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            language_code = args.get("language_code")
            if language_code and user_doc and user_doc.get("telegram_id"):
                _persist_language_code(int(user_doc["telegram_id"]), str(language_code))
        # After successful tool call(s), hand off to the next agent (stub)
        from app.agent.main_agent_stub import generate_reply as stub_next_agent
        return stub_next_agent(user_doc, conversation_doc)

    # Otherwise return the model's text content
    content = msg.content or "What is your name?"
    return content.strip()
