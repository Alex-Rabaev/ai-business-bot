# AI Business Bot

Telegram bot for collecting small business profiles and conducting surveys about CRM system needs.

## What the bot does

**AI Business Buddy** is an intelligent assistant that:

1. **Determines user's preferred language** for communication
2. **Collects business profile** (name, business type, team size)
3. **Conducts detailed survey** about client management, appointments, and CRM needs
4. **Analyzes responses** and provides personalized recommendations
5. **Collects email** for early access to the product (6 months free)

## Tech Stack

- **Python** + **FastAPI** (webhook for Telegram)
- **aiogram** for Telegram Bot API
- **OpenAI GPT-4** for conversation processing
- **MongoDB** for storing users and conversations

## Setup

1. Install dependencies: `pip install -r requirements.txt`
2. Create `.env` file with required variables (see `config.py`)
3. Run: `uvicorn app.main:app --host 0.0.0.0 --port 8000`

## Environment Variables

```
TG_BOT_TOKEN=your_telegram_bot_token
WEBHOOK_URL=https://your-domain.com
WEBHOOK_SECRET=your_webhook_secret
MONGO_URI=mongodb://
MONGO_DB=ai_business_bot
OPENAI_API_KEY=your_openai_api_key
```