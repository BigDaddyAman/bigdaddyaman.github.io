from fastapi import FastAPI, Request, Response, HTTPException
from telethon import TelegramClient, events, types
import uvicorn
import logging
import os
from dotenv import load_dotenv
import asyncio
from database import init_db
from userdb import init_user_db
from premium import init_premium_db
from telegram_bot import setup_handlers, setup_bot

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI
app = FastAPI(title="Telegram Bot Webhook Server")

# Bot settings
api_id = int(os.getenv('API_ID'))
api_hash = os.getenv('API_HASH')
bot_token = os.getenv('BOT_TOKEN')

# Webhook settings
WEBHOOK_URL = os.getenv('WEBHOOK_URL', '').rstrip('/')
WEBHOOK_PATH = f"/webhook/{bot_token}"
PORT = int(os.getenv('PORT', 8000))

# Initialize bot globally but don't connect yet
bot = None

@app.on_event("startup")
async def startup_event():
    """Initialize everything on startup"""
    global bot
    try:
        # Initialize databases first
        await init_db()
        await init_user_db()
        await init_premium_db()
        
        # Initialize bot
        bot = await setup_bot()
        setup_handlers(bot)
        
        if not bot.is_connected():
            await bot.connect()
            
        # Set webhook
        webhook_url = f"{WEBHOOK_URL}{WEBHOOK_PATH}"
        try:
            await bot.delete_webhook()  # Clear any existing webhook
            success = await bot.set_webhook(url=webhook_url)
            if success:
                logger.info(f"Webhook set to {webhook_url}")
            else:
                raise Exception("Failed to set webhook")
        except Exception as e:
            logger.error(f"Webhook setup error: {e}")
            raise
            
        logger.info("Bot initialized successfully")
        
    except Exception as e:
        logger.error(f"Startup error: {e}")
        raise

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    global bot
    try:
        if bot and bot.is_connected():
            await bot.disconnect()
            logger.info("Bot disconnected")
    except Exception as e:
        logger.error(f"Shutdown error: {e}")

@app.get("/")
async def health_check():
    """Health check endpoint"""
    global bot
    try:
        if not bot or not bot.is_connected():
            raise HTTPException(status_code=503, detail="Bot not connected")
        return {"status": "healthy", "bot_connected": True}
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=503, detail=str(e))

@app.post(WEBHOOK_PATH)
async def handle_webhook(request: Request):
    """Handle incoming webhook updates"""
    global bot
    try:
        if not bot:
            raise HTTPException(status_code=503, detail="Bot not initialized")
            
        data = await request.json()
        await bot.process_update(types.Update.from_dict(data))
        return Response(status_code=200)
    except Exception as e:
        logger.error(f"Error handling webhook: {e}")
        return Response(status_code=500)

if __name__ == "__main__":
    config = uvicorn.Config(
        "webhook_server:app",
        host="0.0.0.0",
        port=PORT,
        workers=1,
        loop="auto",
        reload=False
    )
    server = uvicorn.Server(config)
    asyncio.run(server.serve())
