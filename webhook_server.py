from fastapi import FastAPI, Request, Response, HTTPException, BackgroundTasks
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
from redis_cache import redis_cache
import time

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def cleanup_old_cache():
    """Cleanup task to remove old cache entries"""
    while True:
        try:
            # Use scan_iter instead of keys for better performance
            pattern = "msg:*"
            keys = await redis_cache.scan_iter(pattern)
            current_time = time.time()
            
            for key in keys:
                try:
                    value = await redis_cache.get(key)
                    if value and (current_time - float(value)) > 30:
                        await redis_cache.delete(key)
                except Exception as e:
                    logger.debug(f"Error cleaning up key {key}: {e}")
                    continue
                    
        except Exception as e:
            logger.error(f"Cache cleanup error: {e}")
            
        await asyncio.sleep(30)  # Run every 30 seconds

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for FastAPI application"""
    try:
        # Initialize Redis first
        if not redis_cache.redis:
            logger.error("Failed to initialize Redis")
            
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
        
        # Start cache cleanup task
        asyncio.create_task(cleanup_old_cache())
        
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
            logger.info(f"Handling message update: {update_data['message'].get('text', '')}")
            await telegram_bot.handle_webhook_message(update_data['message'], client)
            return Response(status_code=200)
        elif 'callback_query' in update_data:
            logger.info("Handling callback query update")
            await telegram_bot.handle_webhook_callback(update_data['callback_query'], client)
            return Response(status_code=200)

        return Response(status_code=200)
    except Exception as e:
        logger.error(f"Error handling webhook: {e}")
        return Response(status_code=500)

if __name__ == "__main__":
    port = int(os.getenv('PORT', 8080))
    uvicorn.run("webhook_server:app", host="0.0.0.0", port=port, log_level="info")
