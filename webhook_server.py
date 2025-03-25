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
from contextlib import asynccontextmanager

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
bot = TelegramClient(
    'bot_session', 
    api_id, 
    api_hash,
    system_version="4.16.30-vxCUSTOM",
    device_model="Railway Server"
)

# Add this line after bot initialization
loop = asyncio.get_event_loop()
loop.run_until_complete(bot.start(bot_token=bot_token))

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

@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        # Print environment variables (without sensitive data)
        logger.info(f"Starting bot with webhook URL: {WEBHOOK_URL}")
        logger.info(f"Port: {PORT}")
        logger.info(f"API ID present: {'Yes' if api_id else 'No'}")
        logger.info(f"API Hash present: {'Yes' if api_hash else 'No'}")
        logger.info(f"Bot Token present: {'Yes' if bot_token else 'No'}")

        # Check database connection first
        logger.info("Checking database connection...")
        if not await wait_for_db():
            logger.error("Database connection failed!")
            raise HTTPException(status_code=503, detail="Database unavailable")

        # Initialize databases
        logger.info("Initializing databases...")
        await init_db()
        await init_user_db()
        await init_premium_db()

        # Check bot connection
        logger.info("Checking bot connection...")
        if not bot.is_connected():
            await bot.connect()
        
        me = await bot.get_me()
        if not me:
            raise Exception("Bot authentication failed")
        logger.info(f"Bot connected successfully as @{me.username}")
        
        # Set webhook with retries
        webhook_success = False
        retries = 3
        while retries > 0 and not webhook_success:
            try:
                webhook_info = await bot.get_webhook_info()
                if webhook_info.url != f"{WEBHOOK_URL}{WEBHOOK_PATH}":
                    success = await bot.set_webhook(url=f"{WEBHOOK_URL}{WEBHOOK_PATH}")
                    if success:
                        logger.info(f"Webhook set to: {WEBHOOK_URL}{WEBHOOK_PATH}")
                        webhook_success = True
                    else:
                        raise Exception("Webhook setting returned False")
                else:
                    logger.info("Webhook already set correctly")
                    webhook_success = True
                break
            except Exception as e:
                retries -= 1
                logger.error(f"Webhook setup attempt failed ({3-retries}/3): {e}")
                if retries == 0:
                    raise HTTPException(status_code=503, detail=f"Failed to set webhook: {str(e)}")
                await asyncio.sleep(5)
                
        yield
        
        # Cleanup
        await bot.disconnect()
        logger.info("Bot disconnected")
        
    except Exception as e:
        logger.error(f"Startup error: {e}")
        if bot and bot.is_connected():
            await bot.disconnect()
        raise

# Update FastAPI initialization to use lifespan
app = FastAPI(
    title="Telegram Bot Webhook Server",
    lifespan=lifespan
)

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
    try:
        uvicorn.run(
            "webhook_server:app",
            host="0.0.0.0",
            port=PORT,
            workers=1,
            loop="asyncio",  # Changed from uvloop to asyncio for better compatibility
            log_level="info",
            reload=False
        )
    except Exception as e:
        logger.error(f"Server startup error: {e}")
        raise
