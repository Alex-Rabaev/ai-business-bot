import os
from typing import Dict, Any, List
from openai import OpenAI
from app.config import settings
from app.agent.tools.db_ops import (
    update_profile_summary,
    update_preffered_name,
    save_all_survey_answers,
    finish_survey,
    update_user_email_and_final_message,
    update_user_language,
)
from app.agent.tools.chain_tools import (
    update_user_language_schema,
    update_profile_summary_schema,
    update_preffered_name_schema,
    finish_survey_with_answers_schema,
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
            print(f"--------->>>>>>>>>>>>>>>>>>>>>>>>>>>>[function_call] Fresh user doc: {fresh_user_doc}")
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
    preffered_language = user_doc.get("preffered_language")
    print(f"[profile agent] Language code: {preffered_language}")
    system_prompt = PROFILE_SYSTEM_PROMPT + f"\n\nRespond in {preffered_language}. When you have enough information, call the function update_profile_summary with a short summary (one sentence) based on the user's answers. When you learn the user's preferred name, call the function update_preffered_name."
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
        model="gpt-4o",
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
            from app.db.mongo import conversations, users
            conversations.update_one({"user_id": telegram_id}, {"$set": {"stage": "survey"}})
            fresh_user_doc = users.find_one({"telegram_id": telegram_id}, {"_id": 0}) or user_doc
            print(f"PPPPPPPPP-------------->>>>>>>>>>>>>[profile function_call] Fresh user doc: {fresh_user_doc}")
            # Если stage стал 'survey', можно вызвать survey_agent снаружи (handlers)
            return await generate_survey_agent_reply(fresh_user_doc, conversation_doc)
        elif fn.name == "update_preffered_name":
            print(f"[profile function_call] Final args for update_preffered_name: {args}")
            update_preffered_name(**args)
            # Добавляем assistant message в историю, чтобы LLM видел, что имя уже сохранено
            from app.db.mongo import conversations, users
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
            fresh_user_doc = users.find_one({"telegram_id": telegram_id}, {"_id": 0}) or user_doc
            return await generate_profile_agent_reply(fresh_user_doc, conversation_doc)
        else:
            return f"[Unknown function call: {fn.name}]"
    else:
        content = msg.content or "Could you tell me more about your business?"
        return content.strip()


async def generate_survey_agent_reply(user_doc: Dict[str, Any], conversation_doc: Dict[str, Any]) -> str:
    """
    РАДИКАЛЬНОЕ РЕШЕНИЕ: AI ведет весь опрос как обычный диалог.
    В конце, когда пользователь ответил на все вопросы, AI анализирует всю историю
    и сохраняет все пары Q&A за один раз через finish_survey_with_answers.
    """
    preffered_language = user_doc.get("preffered_language")
    profile_summary = user_doc.get("profile_summary")
    survey_prompt = load_survey_prompt()
    
    # Модифицируем промпт для нового подхода
    enhanced_prompt = survey_prompt + f"""
    
IMPORTANT: Do NOT save individual answers during the survey. Just conduct the survey as a natural conversation.
When the user has answered all relevant questions (you can skip questions that are not applicable based on their answers), 
call finish_survey_with_answers with ALL question-answer pairs extracted from our conversation.

Instructions for finish_survey_with_answers:
1. Review the entire conversation history
2. Extract each question you asked and the user's answer
3. Format them as an array of objects with 'question' and 'answer' fields
4. Include only actual survey questions and answers, not greetings or confirmations

Respond in {preffered_language}.

Use user's profile summary for an individual approach: {profile_summary}
"""
    
    # Фильтруем только сообщения stage='survey'
    history = [m for m in conversation_doc.get("messages", []) if m.get("stage") == "survey"]
    msgs: List[Dict[str, str]] = [{"role": "system", "content": enhanced_prompt}]
    
    # Добавляем всю историю опроса
    for m in history:
        role = m.get("role", "user")
        text = m.get("text", "")
        if not isinstance(text, str):
            text = str(text)
        if role not in ("user", "assistant"):
            role = "user"
        msgs.append({"role": role, "content": text})
    
    functions = [finish_survey_with_answers_schema]
    telegram_id = user_doc.get("telegram_id")
    
    resp = openai_client.chat.completions.create(
        model="gpt-4o",
        messages=msgs,
        temperature=1,
        max_tokens=1024,  # Увеличиваем для обработки всех Q&A
        functions=functions,
        function_call="auto",
    )
    choice = resp.choices[0]
    msg = choice.message
    
    if getattr(msg, "function_call", None):
        fn = msg.function_call
        print(f"[survey function_call] AI requested function: {fn.name}, arguments: {fn.arguments}")
        import json
        try:
            print(f"[survey function_call] Raw arguments: {fn.arguments}")
            args = json.loads(fn.arguments)
        except json.JSONDecodeError as e:
            print(f"[survey function_call] JSONDecodeError: {e}")
            print(f"[survey function_call] Offending JSON (first 1000 chars): {fn.arguments[:1000]}")
            raise
        args["telegram_id"] = telegram_id  # всегда подставляем реальный id
        
        if fn.name == "finish_survey_with_answers":
            print(f"[survey function_call] Saving {len(args.get('survey_data', []))} Q&A pairs")
            # Сохраняем все ответы
            save_all_survey_answers(telegram_id, args.get('survey_data', []))
            # Переключаем stage
            finish_survey(telegram_id)
            # Переходим к summary
            from app.agent.chain import generate_summary_agent_reply
            from app.db.mongo import users, conversations
            fresh_user_doc = users.find_one({"telegram_id": telegram_id}, {"_id": 0}) or user_doc
            fresh_conversation_doc = conversations.find_one({"user_id": telegram_id}, {"_id": 0}) or conversation_doc
            print(f"UUUUUUUUSSSSSSSSEEEEEEEERRRRRRRRR________---------->>>>>>>>>>>[survey function_call] Fresh user doc: {fresh_user_doc}")
            print(f"[survey function_call] Fresh conversation doc: {fresh_conversation_doc}")
            return await generate_summary_agent_reply(fresh_user_doc, fresh_conversation_doc)
        else:
            return f"[Unknown function call: {fn.name}]"
    else:
        content = msg.content or "Let me ask you about your business needs..."
        return content.strip()


async def generate_summary_agent_reply(user_doc: Dict[str, Any], conversation_doc: Dict[str, Any]) -> str:
    """
    Ведёт диалог по summary, собирает email, генерирует финальное сообщение, сохраняет его и переводит stage на 'final'.
    """
    preffered_language = user_doc.get("preffered_language")
    profile_summary = user_doc.get("profile_summary")
    survey_data = user_doc.get("survey")
    system_prompt = SUMMARY_SYSTEM_PROMPT + f"""
    \n\nRespond in {preffered_language}. 

    Use user's profile summary for an individual approach: {profile_summary}
    
    Use user's survey data for an individual approach: {survey_data}
    
    When you receive the user's email, call the function update_user_email_and_final_message with the email and a final message for the user (in their language) that says they are in the queue and will be contacted.
    """
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
        model="gpt-4o",
        messages=msgs,
        temperature=1,
        max_tokens=1024,
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
