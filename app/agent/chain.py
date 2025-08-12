from typing import Dict, Any, List
from openai import OpenAI
from app.config import settings

openai_client = OpenAI(api_key=settings.OPENAI_API_KEY)

SYSTEM_PROMPT = """You are AI Business Buddy, a friendly, concise onboarding agent.
Goal: quickly understand who the user is.
Rules:
- Ask ONE short question at a time.
- Be warm and helpful, no sales.
- Use the user’s language if it’s clear from messages.
- Focus first on: name, role, company (or self-employed), location, main goals, current challenges.
- Based on each answer, ask the next most relevant question.
- Keep responses under 2 short sentences.
"""

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
    Вызывает OpenAI для генерации следующего короткого вопроса/реплики.
    Возвращает текст ассистента.
    """
    messages = _build_llm_messages(user_doc, conversation_doc.get("messages", []))

    resp = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        temperature=0.7,
        max_tokens=220,
    )
    content = resp.choices[0].message.content or "What is your name?"
    return content.strip()
