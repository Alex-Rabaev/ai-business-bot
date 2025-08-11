from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Telegram
    TG_BOT_TOKEN: str
    WEBHOOK_URL: str
    WEBHOOK_SECRET: str

    # Mongo
    MONGO_URI: str
    MONGO_DB: str

    # LLM
    OPENAI_API_KEY: str

    class Config:
        env_file = ".env"


settings = Settings()