from app.db.mongo import users, conversations
from typing import Any, List, Dict

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

def save_all_survey_answers(telegram_id: int, survey_data: List[Dict[str, str]]) -> bool:
    """
    Сохраняет все пары вопрос-ответ за один раз.
    survey_data: список словарей с ключами 'question' и 'answer'
    """
    print(f"[save_all_survey_answers] Called with telegram_id={telegram_id}, {len(survey_data)} Q&A pairs")
    
    # Очищаем старые данные опроса и сохраняем новые
    result = users.update_one(
        {"telegram_id": telegram_id},
        {"$set": {"survey": survey_data}}
    )
    print(f"[save_all_survey_answers] Modified count: {result.modified_count}")
    return result.modified_count > 0

def finish_survey(telegram_id: int) -> bool:
    print(f"[finish_survey] Called with telegram_id={telegram_id}")
    result = conversations.update_one({"user_id": telegram_id}, {"$set": {"stage": "summary"}})
    print(f"[finish_survey] Modified count: {result.modified_count}")
    return result.modified_count > 0

def update_user_email_and_final_message(telegram_id: int, email: str, final_message: str) -> bool:
    print(f"[update_user_email_and_final_message] Called with telegram_id={telegram_id}, email={email}")
    result = users.update_one(
        {"telegram_id": telegram_id},
        {"$set": {"email": email, "final_message": final_message}}
    )
    print(f"[update_user_email_and_final_message] Modified count: {result.modified_count}")
    return result.modified_count > 0

def update_user_language(telegram_id: int, language_code: str) -> bool:
    print(f"[update_user_language] Called with telegram_id={telegram_id}, preffered_language={language_code}")
    result = users.update_one({"telegram_id": telegram_id}, {"$set": {"preffered_language": language_code}})
    print(f"[update_user_language] Modified count: {result.modified_count}")
    return result.modified_count > 0
