from fastapi import FastAPI, Request, Response, HTTPException
from contextlib import asynccontextmanager
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

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for FastAPI application"""
    try:
        # Initialize the bot client
        client = await telegram_bot.initialize_client()
        if not client:
            raise Exception("Failed to initialize bot client")
            
        # Initialize databases
        await init_db()
        await init_user_db()
        await init_premium_db()
        
        # Set up bot event handlers
        await telegram_bot.setup_bot_handlers(client)
        
        # Set up webhook
        await telegram_bot.setup_webhook()
        
        logger.info("Startup complete")
        yield
    except Exception as e:
        logger.error(f"Startup failed: {e}")
        raise
    finally:
        # Cleanup
        client = await telegram_bot.get_client()
        if client:
            await client.disconnect()
            logger.info("Bot disconnected")

# Initialize FastAPI with lifespan
app = FastAPI(
    title="Telegram Bot Webhook Server",
    lifespan=lifespan
)

@app.get("/")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}

@app.post(telegram_bot.WEBHOOK_PATH)
async def handle_webhook(request: Request):
    """Handle incoming webhook updates"""
    try:
        # Get webhook secret from environment
        webhook_secret = os.getenv('WEBHOOK_SECRET', '')
        if webhook_secret:
            secret = request.headers.get('X-Telegram-Bot-Api-Secret-Token')
            if secret != webhook_secret:
                raise HTTPException(status_code=403, detail="Invalid secret token")

        # Parse update data
        update_data = await request.json()
        client = await telegram_bot.get_client()
        
        # Handle different types of updates
        if 'message' in update_data:
            await telegram_bot.handle_messages(update_data['message'], client)
        elif 'callback_query' in update_data:
            await telegram_bot.handle_callback_query(update_data['callback_query'], client)

        return Response(status_code=200)
    except Exception as e:
        logger.error(f"Error handling webhook: {e}")
        return Response(status_code=500)

if __name__ == "__main__":
    port = int(os.getenv('PORT', 8080))
    uvicorn.run("webhook_server:app", host="0.0.0.0", port=port, log_level="info")
