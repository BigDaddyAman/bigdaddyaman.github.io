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
WEBHOOK_URL = os.getenv('WEBHOOK_URL')
WEBHOOK_PATH = f"/webhook/{bot_token}"
PORT = int(os.getenv('PORT', 8000))

# Initialize bot
bot = TelegramClient('bot', api_id, api_hash).start(bot_token=bot_token)

@app.on_event("startup")
async def startup_event():
    """Initialize everything on startup"""
    try:
        # Initialize databases
        await init_db()
        await init_user_db()
        await init_premium_db()
        
        # Set webhook
        await bot.connect()
        if not await bot.is_user_authorized():
            logger.error("Bot not authorized!")
            raise HTTPException(status_code=500, detail="Bot not authorized")
            
        # Set webhook
        webhook_info = await bot.get_webhook_info()
        if webhook_info.url != WEBHOOK_URL:
            success = await bot.set_webhook(url=f"{WEBHOOK_URL}{WEBHOOK_PATH}")
            if success:
                logger.info(f"Webhook set to {WEBHOOK_URL}{WEBHOOK_PATH}")
            else:
                logger.error("Failed to set webhook")
                raise HTTPException(status_code=500, detail="Failed to set webhook")
                
        logger.info("Bot initialized successfully")
    except Exception as e:
        logger.error(f"Startup error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    try:
        await bot.disconnect()
        logger.info("Bot disconnected")
    except Exception as e:
        logger.error(f"Shutdown error: {e}")

@app.get("/")
async def health_check():
    """Health check endpoint"""
    try:
        if not bot.is_connected():
            await bot.connect()
        return {"status": "healthy", "bot_connected": True}
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=503, detail="Bot not connected")

@app.post(WEBHOOK_PATH)
async def handle_webhook(request: Request):
    """Handle incoming webhook updates"""
    try:
        data = await request.json()
        update = types.Update.from_dict(data)
        
        # Process update
        await bot.process_update(update)
        return Response(status_code=200)
    except Exception as e:
        logger.error(f"Error handling webhook: {e}")
        return Response(status_code=500)

if __name__ == "__main__":
    uvicorn.run(
        "webhook_server:app",
        host="0.0.0.0",
        port=PORT,
        workers=1,  # Single worker for Telethon
        loop="uvloop",
        reload=False
    )
