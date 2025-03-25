from fastapi import FastAPI, Request, Response, HTTPException
import telegram_bot
from telethon import events, types
import logging
import os
from dotenv import load_dotenv
import asyncio
import uvicorn
from database import init_db
from userdb import init_user_db
from premium import init_premium_db

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI
app = FastAPI(title="Telegram Bot Webhook Server")

# Bot settings
PORT = int(os.getenv('PORT', 8080))
WEBHOOK_SECRET = os.getenv('WEBHOOK_SECRET', '')

async def startup():
    """Initialize bot and databases on startup"""
    try:
        # Initialize the bot client
        client = await telegram_bot.initialize_client()
        if not client:
            raise Exception("Failed to initialize bot client")
            
        # Set up bot event handlers
        await telegram_bot.setup_bot_handlers(client)
        
        # Initialize databases
        await init_db()
        await init_user_db()
        await init_premium_db()
        
        # Set up webhook
        await telegram_bot.setup_webhook()
        
        logger.info("Startup complete")
        return True
    except Exception as e:
        logger.error(f"Startup failed: {e}")
        return False

@app.on_event("startup")
async def on_startup():
    if not await startup():
        raise Exception("Failed to complete startup")

@app.get("/")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}

@app.post(telegram_bot.WEBHOOK_PATH)
async def handle_webhook(request: Request):
    """Handle incoming webhook updates"""
    try:
        if WEBHOOK_SECRET:
            secret = request.headers.get('X-Telegram-Bot-Api-Secret-Token')
            if secret != WEBHOOK_SECRET:
                raise HTTPException(status_code=403, detail="Invalid secret token")

        update_data = await request.json()
        update = types.Update.from_dict(update_data)

        client = await telegram_bot.get_client()
        if update.message:
            await telegram_bot.handle_message(update.message, client)
        elif update.callback_query:
            await telegram_bot.handle_callback_query(update.callback_query, client)

        return Response(status_code=200)
    except Exception as e:
        logger.error(f"Error handling webhook: {e}")
        return Response(status_code=500)

if __name__ == "__main__":
    uvicorn.run("webhook_server:app", host="0.0.0.0", port=PORT, log_level="info")
