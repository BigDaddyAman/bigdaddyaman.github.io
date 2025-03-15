from fastapi import FastAPI, Request
from telethon import events, types
import uvicorn
import logging
import os
from dotenv import load_dotenv
from telegram_bot import setup_bot, setup_handlers  # Modified import

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI
app = FastAPI()

# Initialize bot without running it
bot = setup_bot()
setup_handlers(bot)  # Setup all handlers but don't start polling

# Webhook settings from environment
WEBHOOK_URL = os.getenv('WEBHOOK_URL')
WEBHOOK_PATH = os.getenv('WEBHOOK_PATH', f"/webhook/{os.getenv('BOT_TOKEN')}")

@app.on_event("startup")
async def startup():
    """Set webhook on startup"""
    webhook_info = await bot.get_webhook_info()
    if (webhook_info.url != WEBHOOK_URL):
        await bot.set_webhook(url=WEBHOOK_URL)
    logger.info(f"Webhook set to {WEBHOOK_URL}")

@app.post(WEBHOOK_PATH)
async def handle_webhook(request: Request):
    """Handle incoming webhook updates"""
    try:
        data = await request.json()
        update = types.Update.from_dict(data)
        await bot._handle_update(update)
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Error handling webhook: {e}")
        return {"status": "error", "message": str(e)}

@app.get("/")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}

if __name__ == "__main__":
    port = int(os.getenv('PORT', 8000))
    uvicorn.run(
        "webhook_server:app",
        host="0.0.0.0",
        port=port,
        workers=1  # Use 1 worker for Telethon
    )
