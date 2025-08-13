# Function calling schemas for agents

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
