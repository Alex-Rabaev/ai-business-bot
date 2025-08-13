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

PROFILE_PROMPT_PATH = os.path.join(os.path.dirname(__file__), "prompts", "profile.md")
def _load_profile_prompt():
    with open(PROFILE_PROMPT_PATH, encoding="utf-8") as f:
        return f.read()
PROFILE_SYSTEM_PROMPT = _load_profile_prompt()

update_profile_summary_schema = {
    "name": "update_profile_summary",
    "description": "Update the user's business profile summary in the database.",
    "parameters": {
        "type": "object",
        "properties": {
            "telegram_id": {"type": "integer", "description": "Telegram user ID"},
            "profile_summary": {"type": "string", "description": "Short business profile summary (one sentence)"}
        },
        "required": ["telegram_id", "profile_summary"]
    }
}

update_preffered_name_schema = {
    "name": "update_preffered_name",
    "description": "Update the user's preferred name in the database.",
    "parameters": {
        "type": "object",
        "properties": {
            "telegram_id": {"type": "integer", "description": "Telegram user ID"},
            "preffered_name": {"type": "string", "description": "Preferred name for addressing the user"}
        },
        "required": ["telegram_id", "preffered_name"]
    }
}

# --- Survey agent function schema ---
save_survey_answer_schema = {
    "name": "save_survey_answer",
    "description": "Save a survey answer for the user. Pushes a question and answer to the user's survey array in the database.",
    "parameters": {
        "type": "object",
        "properties": {
            "telegram_id": {"type": "integer", "description": "Telegram user ID"},
            "question": {"type": "string", "description": "Survey question text (as asked)"},
            "answer": {"type": "string", "description": "User's answer to the survey question"}
        },
        "required": ["telegram_id", "question", "answer"]
    }
}

# --- Finish survey function schema ---
finish_survey_schema = {
    "name": "finish_survey",
    "description": "Mark the survey as complete and set the user's stage to 'summary'.",
    "parameters": {
        "type": "object",
        "properties": {
            "telegram_id": {"type": "integer", "description": "Telegram user ID"}
        },
        "required": ["telegram_id"]
    }
}


def update_profile_summary(telegram_id: int, profile_summary: str) -> bool:
    print(f"[update_profile_summary] Called with telegram_id={telegram_id}, profile_summary={profile_summary}")
    result = users.update_one({"telegram_id": telegram_id}, {"$set": {"profile_summary": profile_summary}})
    print(f"[update_profile_summary] Modified count: {result.modified_count}")
    return result.modified_count > 0

def update_preffered_name(telegram_id: int, preffered_name: str) -> bool:
    print(f"[update_preffered_name] Called with telegram_id={telegram_id}, preffered_name={preffered_name}")
    result = users.update_one({"telegram_id": telegram_id}, {"$set": {"preffered_name": preffered_name}})
    print(f"[update_preffered_name] Modified count: {result.modified_count}")
    return result.modified_count > 0

def save_survey_answer(telegram_id: int, question: str, answer: str) -> bool:
    print(f"[save_survey_answer] Called with telegram_id={telegram_id}, question={question}, answer={answer}")
    result = users.update_one(
        {"telegram_id": telegram_id},
        {"$push": {"survey": {"question": question, "answer": answer}}}
    )
    print(f"[save_survey_answer] Modified count: {result.modified_count}")
    return result.modified_count > 0

def finish_survey(telegram_id: int) -> bool:
    print(f"[finish_survey] Called with telegram_id={telegram_id}")
    from app.db.mongo import conversations
    result = conversations.update_one({"user_id": telegram_id}, {"$set": {"stage": "summary"}})
    print(f"[finish_survey] Modified count: {result.modified_count}")
    return result.modified_count > 0

# def second_agent_stub(*args, **kwargs):
#     return "In development"

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

async def generate_agent_reply(user_doc: Dict[str, Any], conversation_doc: Dict[str, Any]) -> str:
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
    # Загружаем текст опроса
    SURVEY_PROMPT_PATH = os.path.join(os.path.dirname(__file__), "prompts", "survey.md")
    with open(SURVEY_PROMPT_PATH, encoding="utf-8") as f:
        survey_prompt = f.read()
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

SUMMARY_PROMPT_PATH = os.path.join(os.path.dirname(__file__), "prompts", "summary.md")
def _load_summary_prompt():
    with open(SUMMARY_PROMPT_PATH, encoding="utf-8") as f:
        return f.read()
SUMMARY_SYSTEM_PROMPT = _load_summary_prompt()

def update_user_email_and_final_message(telegram_id: int, email: str, final_message: str) -> bool:
    print(f"[update_user_email_and_final_message] Called with telegram_id={telegram_id}, email={email}")
    result = users.update_one(
        {"telegram_id": telegram_id},
        {"$set": {"email": email, "final_message": final_message}}
    )
    print(f"[update_user_email_and_final_message] Modified count: {result.modified_count}")
    return result.modified_count > 0

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
    # Function schema for email and final message
    update_user_email_and_final_message_schema = {
        "name": "update_user_email_and_final_message",
        "description": "Save the user's email and the final message, and set the user's stage to 'final'.",
        "parameters": {
            "type": "object",
            "properties": {
                "telegram_id": {"type": "integer", "description": "Telegram user ID"},
                "email": {"type": "string", "description": "User's email address"},
                "final_message": {"type": "string", "description": "Final message to show the user (in their language)"}
            },
            "required": ["telegram_id", "email", "final_message"]
        }
    }
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

def update_user_language(telegram_id: int, language_code: str) -> bool:
    print(f"[update_user_language] Called with telegram_id={telegram_id}, preffered_language={language_code}")
    result = users.update_one({"telegram_id": telegram_id}, {"$set": {"preffered_language": language_code}})
    print(f"[update_user_language] Modified count: {result.modified_count}")
    return result.modified_count > 0
