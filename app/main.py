from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from aiogram.types import Update

from app.config import settings
from app.telegram_bot.bot import bot, dp
from app.db.mongo import users, conversations


WEBHOOK_PATH = f"/telegram/{settings.TG_BOT_TOKEN}"

def build_webhook_url() -> str:
    base = settings.WEBHOOK_URL.rstrip("/")
    return f"{base}{WEBHOOK_PATH}"

@asynccontextmanager
async def lifespan(app: FastAPI):
    # === Индексы БД (выполнятся один раз, если их ещё нет) ===
    try:
        users.create_index("telegram_id", unique=True, name="uniq_telegram_id")
        conversations.create_index("user_id", unique=True, name="uniq_user_id")
        conversations.create_index("updated_at", name="idx_updated_at")
    except Exception as e:
        print(f"[WARN] Index creation skipped/error: {e}")
        
    # Ставит вебхук при старте приложения
    await bot.set_webhook(
        url=build_webhook_url(),
        secret_token=settings.WEBHOOK_SECRET,  # Telegram пришлёт этот токен в заголовке
        allowed_updates=dp.resolve_used_update_types(),
    )
    try:
        yield
    finally:
        # Снимаем вебхук и закрываем HTTP‑сессию бота
        await bot.delete_webhook(drop_pending_updates=False)
        await bot.session.close()

app = FastAPI(title="AI Business Buddy - Telegram Webhook (lifespan)", lifespan=lifespan)

@app.post(WEBHOOK_PATH)
async def telegram_webhook(request: Request):
    # Валидируем секрет из заголовка Telegram
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    if secret != settings.WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="Invalid secret token")

    # Преобразуем JSON в aiogram Update и передаём в диспетчер
    update = Update.model_validate(await request.json())
    await dp.feed_webhook_update(bot, update)
    return {"ok": True}

# Для быстрой проверки, что API живо
@app.get("/")
async def root():
    return {"status": "ok", "webhook": build_webhook_url()}