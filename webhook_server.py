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
import asyncpg

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

async def wait_for_db():
    """Wait for database to become available"""
    retries = 5
    while retries > 0:
        try:
            # Test database connection
            conn = await asyncpg.connect(
                database=os.getenv('PGDATABASE'),
                user=os.getenv('PGUSER'),
                password=os.getenv('PGPASSWORD'),
                host=os.getenv('PGHOST'),
                port=os.getenv('PGPORT')
            )
            await conn.close()
            return True
        except Exception as e:
            logger.warning(f"Database not ready, retrying... ({e})")
            retries -= 1
            await asyncio.sleep(5)
    return False

async def check_bot_auth():
    """Check if bot is properly authenticated"""
    try:
        if not bot.is_connected():
            await bot.connect()
        me = await bot.get_me()
        return bool(me)
    except Exception as e:
        logger.error(f"Bot auth check failed: {e}")
        return False

@app.on_event("startup")
async def startup_event():
    """Initialize everything on startup with proper checks"""
    try:
        # Wait for database
        logger.info("Waiting for database...")
        if not await wait_for_db():
            raise HTTPException(status_code=503, detail="Database unavailable")

        # Initialize databases
        logger.info("Initializing databases...")
        await init_db()
        await init_user_db()
        await init_premium_db()
        
        # Connect and check bot
        logger.info("Connecting bot...")
        await bot.connect()
        if not await check_bot_auth():
            raise HTTPException(status_code=503, detail="Bot authentication failed")
            
        # Set webhook with retries
        retries = 3
        while retries > 0:
            try:
                webhook_info = await bot.get_webhook_info()
                if webhook_info.url != WEBHOOK_URL:
                    success = await bot.set_webhook(url=f"{WEBHOOK_URL}{WEBHOOK_PATH}")
                    if success:
                        logger.info(f"Webhook set to {WEBHOOK_URL}{WEBHOOK_PATH}")
                        break
                else:
                    logger.info("Webhook already set correctly")
                    break
            except Exception as e:
                logger.warning(f"Webhook setup attempt {4-retries} failed: {e}")
                retries -= 1
                if retries == 0:
                    raise HTTPException(status_code=503, detail="Failed to set webhook")
                await asyncio.sleep(5)
                
        logger.info("Bot initialized successfully")
    except Exception as e:
        logger.error(f"Startup error: {e}")
        raise HTTPException(status_code=503, detail=str(e))

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
    """Comprehensive health check endpoint"""
    health = {
        "status": "healthy",
        "checks": {
            "database": False,
            "bot": False,
            "webhook": False
        }
    }
    
    try:
        # Check database
        if await wait_for_db():
            health["checks"]["database"] = True
        
        # Check bot connection
        if await check_bot_auth():
            health["checks"]["bot"] = True
            
        # Check webhook
        webhook_info = await bot.get_webhook_info()
        if webhook_info.url == f"{WEBHOOK_URL}{WEBHOOK_PATH}":
            health["checks"]["webhook"] = True
            
        # Overall health status
        if all(health["checks"].values()):
            health["status"] = "healthy"
        else:
            health["status"] = "degraded"
            raise HTTPException(status_code=503, detail=health)
            
        return health
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        health["status"] = "unhealthy"
        raise HTTPException(status_code=503, detail=health)

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
