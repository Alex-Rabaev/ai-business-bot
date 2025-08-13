import os
from typing import Dict, Any, List
from openai import OpenAI
from app.config import settings
from app.agent.tools.db_ops import (
    update_profile_summary,
    update_preffered_name,
    save_survey_answer,
    finish_survey,
    update_user_email_and_final_message,
    update_user_language,
)
from app.agent.tools.chain_tools import (
    update_user_language_schema,
    update_profile_summary_schema,
    update_preffered_name_schema,
    save_survey_answer_schema,
    finish_survey_schema,
    update_user_email_and_final_message_schema,
)
from app.agent.tools.prompt_loader import (
    load_greeting_and_lang_prompt,
    load_profile_prompt,
    load_summary_prompt,
    load_survey_prompt,
)

openai_client = OpenAI(api_key=settings.OPENAI_API_KEY)

SYSTEM_PROMPT = load_greeting_and_lang_prompt()
PROFILE_SYSTEM_PROMPT = load_profile_prompt()
SUMMARY_SYSTEM_PROMPT = load_summary_prompt()


def _build_llm_messages(user_doc: Dict[str, Any], history: List[Dict[str, Any]], stage: str = None) -> List[Dict[str, str]]:
    """
    Конвертируем историю из Mongo в формат messages для Chat Completions API.
    Если указан stage, берём только сообщения этого этапа.
    """
    msgs: List[Dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    hints = []
    if user_doc:
        for k in ("first_name", "last_name", "username", "language_code", "preffered_language"):
            v = user_doc.get(k)
            if v:
                hints.append(f"{k}={v}")
    if hints:
        msgs.append({"role": "system", "content": "Known user hints: " + ", ".join(hints)})
    if stage:
        history = [m for m in history if m.get("stage") == stage]
    recent = history[-20:] if history else []
    for m in recent:
        role = m.get("role", "user")
        text = m.get("text", "")
        if not isinstance(text, str):
            text = str(text)
        if role not in ("user", "assistant"):
            role = "user"
        msgs.append({"role": role, "content": text})
    return msgs


async def generate_greet_and_lang_agent_reply(user_doc: Dict[str, Any], conversation_doc: Dict[str, Any]) -> str:
    """
    Генерирует ответ агента с поддержкой function calling.
    Если AI вызывает функцию update_user_language, обновляет пользователя и передаёт управление второму агенту.
    """
    messages = _build_llm_messages(user_doc, conversation_doc.get("messages", []), stage="language")
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
            args["telegram_id"] = telegram_id  # всегда подставляем реальный id
            print(f"[function_call] Final args for update_user_language: {args}")
            update_user_language(**args)
            # Переключаем stage на 'profile'
            from app.db.mongo import conversations, users
            conversations.update_one({"user_id": telegram_id}, {"$set": {"stage": "profile"}})
            # Перечитываем user_doc с актуальным preffered_language
            fresh_user_doc = users.find_one({"telegram_id": telegram_id}, {"_id": 0}) or user_doc
            return await generate_profile_agent_reply(fresh_user_doc, conversation_doc)
        else:
            return f"[Unknown function call: {fn.name}]"
    else:
        content = msg.content or "What is your name?"
        return content.strip()


async def generate_profile_agent_reply(user_doc: Dict[str, Any], conversation_doc: Dict[str, Any]) -> str:
    """
    Ведёт диалог по бизнес-профилю, собирает ответы, генерирует summary и сохраняет его через function_call.
    """
    language_code = user_doc.get("preffered_language")
    system_prompt = PROFILE_SYSTEM_PROMPT + f"\n\nRespond in {language_code}. When you have enough information, call the function update_profile_summary with a short summary (one sentence) based on the user's answers. When you learn the user's preferred name, call the function update_preffered_name."
    # Фильтруем только сообщения stage='profile'
    history = [m for m in conversation_doc.get("messages", []) if m.get("stage") == "profile"]
    msgs: List[Dict[str, str]] = [{"role": "system", "content": system_prompt}]
    for m in history[-20:]:
        role = m.get("role", "user")
        text = m.get("text", "")
        if not isinstance(text, str):
            text = str(text)
        if role not in ("user", "assistant"):
            role = "user"
        msgs.append({"role": role, "content": text})
    functions = [update_profile_summary_schema, update_preffered_name_schema]
    telegram_id = user_doc.get("telegram_id")
    resp = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=msgs,
        temperature=0.7,
        max_tokens=220,
        functions=functions,
        function_call="auto",
    )
    choice = resp.choices[0]
    msg = choice.message
    if getattr(msg, "function_call", None):
        fn = msg.function_call
        print(f"[profile function_call] AI requested function: {fn.name}, arguments: {fn.arguments}")
        import json
        args = json.loads(fn.arguments)
        args["telegram_id"] = telegram_id  # всегда подставляем реальный id
        if fn.name == "update_profile_summary":
            print(f"[profile function_call] Final args for update_profile_summary: {args}")
            update_profile_summary(**args)
            # Переключаем stage на 'survey'
            from app.db.mongo import conversations
            conversations.update_one({"user_id": telegram_id}, {"$set": {"stage": "survey"}})
            # Если stage стал 'survey', можно вызвать survey_agent снаружи (handlers)
            return await generate_survey_agent_reply(user_doc, conversation_doc)
        elif fn.name == "update_preffered_name":
            print(f"[profile function_call] Final args for update_preffered_name: {args}")
            update_preffered_name(**args)
            # Добавляем assistant message в историю, чтобы LLM видел, что имя уже сохранено
            from app.db.mongo import conversations
            from datetime import datetime, timezone
            conversations.update_one(
                {"user_id": telegram_id},
                {"$push": {"messages": {
                    "role": "assistant",
                    "text": f"Имя пользователя для обращения сохранено: {args['preffered_name']}.",
                    "ts": datetime.now(timezone.utc),
                    "stage": "profile"
                }}}
            )
            # Перечитываем conversation_doc для актуальной истории
            conversation_doc = conversations.find_one({"user_id": telegram_id}, {"_id": 0}) or conversation_doc
            return await generate_profile_agent_reply(user_doc, conversation_doc)
        else:
            return f"[Unknown function call: {fn.name}]"
    else:
        content = msg.content or "Could you tell me more about your business?"
        return content.strip()


async def generate_survey_agent_reply(user_doc: Dict[str, Any], conversation_doc: Dict[str, Any]) -> str:
    """
    Ведёт опрос по вопросам из survey.md, сохраняет каждый ответ через функцию save_survey_answer.
    После завершения опроса переводит stage на 'summary' через функцию finish_survey.
    """
    language_code = user_doc.get("preffered_language")
    survey_prompt = load_survey_prompt()
    system_prompt = survey_prompt + f"\n\nRespond in {language_code}. After each user answer, call save_survey_answer with the question and answer. When the survey is complete, call finish_survey."
    # Фильтруем только сообщения stage='survey'
    history = [m for m in conversation_doc.get("messages", []) if m.get("stage") == "survey"]
    msgs: List[Dict[str, str]] = [{"role": "system", "content": system_prompt}]
    for m in history[-20:]:
        role = m.get("role", "user")
        text = m.get("text", "")
        if not isinstance(text, str):
            text = str(text)
        if role not in ("user", "assistant"):
            role = "user"
        msgs.append({"role": role, "content": text})
    functions = [save_survey_answer_schema, finish_survey_schema]
    telegram_id = user_doc.get("telegram_id")
    resp = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=msgs,
        temperature=0.7,
        max_tokens=220,
        functions=functions,
        function_call="auto",
    )
    choice = resp.choices[0]
    msg = choice.message
    if getattr(msg, "function_call", None):
        fn = msg.function_call
        print(f"[survey function_call] AI requested function: {fn.name}, arguments: {fn.arguments}")
        import json
        args = json.loads(fn.arguments)
        args["telegram_id"] = telegram_id  # всегда подставляем реальный id
        if fn.name == "save_survey_answer":
            print(f"[survey function_call] Final args for save_survey_answer: {args}")
            save_survey_answer(**args)
            # Добавляем system message для LLM, чтобы он знал, что ответ сохранён
            from app.db.mongo import conversations
            from datetime import datetime, timezone
            conversations.update_one(
                {"user_id": telegram_id},
                {"$push": {"messages": {
                    "role": "system",
                    "text": "The answer to the previous question has been saved, move on to the next question.",
                    "ts": datetime.now(timezone.utc),
                    "stage": "survey"
                }}}
            )
            conversation_doc = conversations.find_one({"user_id": telegram_id}, {"_id": 0}) or conversation_doc
            return await generate_survey_agent_reply(user_doc, conversation_doc)
        elif fn.name == "finish_survey":
            print(f"[survey function_call] Final args for finish_survey: {args}")
            finish_survey(**args)
            # Immediately start summary agent
            from app.agent.chain import generate_summary_agent_reply
            return await generate_summary_agent_reply(user_doc, conversation_doc)
        else:
            return f"[Unknown function call: {fn.name}]"
    else:
        content = msg.content or "Thank you for completing the survey!"
        return content.strip()


async def generate_summary_agent_reply(user_doc: Dict[str, Any], conversation_doc: Dict[str, Any]) -> str:
    """
    Ведёт диалог по summary, собирает email, генерирует финальное сообщение, сохраняет его и переводит stage на 'final'.
    """
    language_code = user_doc.get("preffered_language")
    system_prompt = SUMMARY_SYSTEM_PROMPT + f"\n\nRespond in {language_code}. When you receive the user's email, call the function update_user_email_and_final_message with the email and a final message for the user (in their language) that says they are in the queue and will be contacted."
    # Фильтруем только сообщения stage='summary'
    history = [m for m in conversation_doc.get("messages", []) if m.get("stage") == "summary"]
    msgs: List[Dict[str, str]] = [{"role": "system", "content": system_prompt}]
    for m in history[-20:]:
        role = m.get("role", "user")
        text = m.get("text", "")
        if not isinstance(text, str):
            text = str(text)
        if role not in ("user", "assistant"):
            role = "user"
        msgs.append({"role": role, "content": text})
    telegram_id = user_doc.get("telegram_id")
    resp = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=msgs,
        temperature=0.7,
        max_tokens=220,
        functions=[update_user_email_and_final_message_schema],
        function_call="auto",
    )
    choice = resp.choices[0]
    msg = choice.message
    if getattr(msg, "function_call", None):
        fn = msg.function_call
        print(f"[summary function_call] AI requested function: {fn.name}, arguments: {fn.arguments}")
        import json
        args = json.loads(fn.arguments)
        args["telegram_id"] = telegram_id
        if fn.name == "update_user_email_and_final_message":
            print(f"[summary function_call] Final args for update_user_email_and_final_message: {args}")
            update_user_email_and_final_message(**args)
            # Переводим stage на 'final'
            from app.db.mongo import conversations
            conversations.update_one({"user_id": telegram_id}, {"$set": {"stage": "final"}})
            return args["final_message"]
        else:
            return f"[Unknown function call: {fn.name}]"
    else:
        content = msg.content or "Please provide your email to get early access."
        return content.strip()
