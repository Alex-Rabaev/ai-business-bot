import os

def load_prompt(prompt_path: str) -> str:
    with open(prompt_path, encoding="utf-8") as f:
        return f.read()

# Для совместимости, если нужно, можно добавить алиасы:
def load_greeting_and_lang_prompt():
    path = os.path.join(os.path.dirname(__file__), "../prompts/greeting_and_lang.md")
    return load_prompt(path)

def load_profile_prompt():
    path = os.path.join(os.path.dirname(__file__), "../prompts/profile.md")
    return load_prompt(path)

def load_summary_prompt():
    path = os.path.join(os.path.dirname(__file__), "../prompts/summary.md")
    return load_prompt(path)

def load_survey_prompt():
    path = os.path.join(os.path.dirname(__file__), "../prompts/survey.md")
    return load_prompt(path)
