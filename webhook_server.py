from fastapi import FastAPI, Request, Response, HTTPException
from telethon import TelegramClient, events, types
from telethon.errors import FloodWaitError, AuthKeyError
from telethon.sessions import MemorySession  # Add this import
import uvicorn
import logging
import os
from dotenv import load_dotenv
import asyncio
import aiohttp
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

# Update Webhook settings
WEBHOOK_HOST = os.getenv('WEBHOOK_HOST')
WEBHOOK_PATH = os.getenv('WEBHOOK_PATH', f"/webhook/{bot_token}")
WEBHOOK_URL = os.getenv('WEBHOOK_URL')
PORT = int(os.getenv('PORT', 8000))

# Initialize bot globally with MemorySession
bot = TelegramClient(
    MemorySession(),  # Use MemorySession instead of string
    api_id, 
    api_hash,
    system_version="4.16.30-vxCUSTOM",
    device_model="Railway Server"
)

# Create initialization function
async def initialize_bot():
    """Initialize and start the bot with flood wait handling"""
    max_retries = 3
    current_retry = 0
    
    while current_retry < max_retries:
        try:
            if not bot.is_connected():
                await bot.connect()
            
            if not await bot.is_user_authorized():
                await bot.start(bot_token=bot_token)
                
            logger.info("Bot initialized successfully")
            return True
            
        except FloodWaitError as e:
            wait_time = e.seconds
            logger.warning(f"Hit flood wait limit. Waiting {wait_time} seconds...")
            await asyncio.sleep(wait_time)
            current_retry += 1
            
        except AuthKeyError:
            logger.error("Authentication key error. Recreating session...")
            if bot.is_connected():
                await bot.disconnect()
            bot.session = MemorySession()
            current_retry += 1
            
        except Exception as e:
            logger.error(f"Failed to initialize bot: {e}")
            return False
            
    logger.error("Failed to initialize bot after maximum retries")
    return False

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

async def get_webhook_info():
    """Get current webhook info using Telegram Bot API"""
    async with aiohttp.ClientSession() as session:
        url = f"https://api.telegram.org/bot{bot_token}/getWebhookInfo"
        async with session.get(url) as response:
            if response.status == 200:
                data = await response.json()
                return data.get('result', {}).get('url', '')
            return None

async def setup_webhook():
    """Set up webhook for the bot"""
    try:
        # Delete any existing webhook
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f'https://api.telegram.org/bot{bot_token}/deleteWebhook'
            ) as resp:
                await resp.json()  # Clear any existing webhook

        # Set new webhook
        async with aiohttp.ClientSession() as session:
            webhook_data = {
                'url': WEBHOOK_URL,
                'max_connections': 100,
                'allowed_updates': ['message', 'callback_query']
            }
            async with session.post(
                f'https://api.telegram.org/bot{bot_token}/setWebhook',
                json=webhook_data
            ) as resp:
                result = await resp.json()
                if result.get('ok'):
                    logger.info(f"Webhook set successfully to {WEBHOOK_URL}")
                    return True
                else:
                    logger.error(f"Failed to set webhook: {result}")
                    return False
    except Exception as e:
        logger.error(f"Error setting webhook: {e}")
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

        # Initialize bot with retries
        retry_count = 0
        max_retries = 3
        while retry_count < max_retries:
            logger.info(f"Initializing bot (attempt {retry_count + 1}/{max_retries})...")
            if await initialize_bot():
                break
            retry_count += 1
            if retry_count < max_retries:
                await asyncio.sleep(10)  # Wait between retries
        
        if retry_count == max_retries:
            raise HTTPException(status_code=503, detail="Bot initialization failed after multiple attempts")

        # Check database connection
        logger.info("Checking database connection...")
        if not await wait_for_db():
            logger.error("Database connection failed!")
            raise HTTPException(status_code=503, detail="Database unavailable")

        # Initialize databases
        logger.info("Initializing databases...")
        await init_db()
        await init_user_db()
        await init_premium_db()
        
        # Set up webhook
        if not await setup_webhook():
            raise HTTPException(status_code=503, detail="Webhook setup failed")
                
        yield
        
    except Exception as e:
        logger.error(f"Startup error: {e}")
        raise
    finally:
        # Cleanup
        if bot and bot.is_connected():
            await bot.disconnect()
            logger.info("Bot disconnected")

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
        current_webhook = await get_webhook_info()
        if current_webhook == f"{WEBHOOK_URL}{WEBHOOK_PATH}":
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
        # Verify secret token if set
        if WEBHOOK_SECRET:
            secret = request.headers.get('X-Telegram-Bot-Api-Secret-Token')
            if secret != WEBHOOK_SECRET:
                raise HTTPException(status_code=403, detail="Invalid secret token")

        update_data = await request.json()
        update = types.Update.from_dict(update_data)

        # Handle different types of updates
        if update.message:
            await handle_message(update.message)
        elif update.callback_query:
            await handle_callback_query(update.callback_query)

        return Response(status_code=200)
    except Exception as e:
        logger.error(f"Error handling webhook: {e}")
        return Response(status_code=500)

# Modify the main part
if __name__ == "__main__": 
    try:
        uvicorn.run(
            "webhook_server:app",
            host="0.0.0.0",
            port=PORT,
            workers=1,
            loop="asyncio",
            log_level="info",
            reload=False
        )
    except Exception as e:
        logger.error(f"Server startup error: {e}")
        raise
