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
from datetime import datetime
from fastapi.responses import JSONResponse
from telegram_bot import setup_bot_handlers, initialize_client  # Update import

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
WEBHOOK_PATH = os.getenv('WEBHOOK_PATH')
WEBHOOK_URL = os.getenv('WEBHOOK_URL')
PORT = int(os.getenv('PORT', 8080))  # Change default port to 8080
WEBHOOK_SECRET = os.getenv('WEBHOOK_SECRET', '')  # Add this line near other env vars

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
    """Set up webhook for the bot with rate limit handling"""
    try:
        async with aiohttp.ClientSession() as session:
            # Delete existing webhook first
            async with session.get(
                f'https://api.telegram.org/bot{bot_token}/deleteWebhook'
            ) as resp:
                await resp.json()

            # Retry logic for setting webhook
            while True:
                webhook_data = {
                    'url': WEBHOOK_URL,
                    'max_connections': 100,
                    'allowed_updates': ['message', 'callback_query'],
                    'drop_pending_updates': True
                }
                async with session.post(
                    f'https://api.telegram.org/bot{bot_token}/setWebhook',
                    json=webhook_data
                ) as resp:
                    result = await resp.json()
                    if result.get('ok'):
                        logger.info(f"Webhook set successfully to {WEBHOOK_URL}")
                        return True
                    elif result.get('error_code') == 429:
                        retry_after = result.get('parameters', {}).get('retry_after', 60)
                        logger.warning(f"Rate limited. Retrying after {retry_after} seconds...")
                        await asyncio.sleep(retry_after)
                    else:
                        logger.error(f"Failed to set webhook: {result}")
                        return False
    except Exception as e:
        logger.error(f"Error in webhook setup: {e}")
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

        # Initialize bot first
        retry_count = 0
        max_retries = 3
        while retry_count < max_retries:
            logger.info(f"Initializing bot (attempt {retry_count + 1}/{max_retries})...")
            try:
                client = await initialize_client()
                if client and client.is_connected():
                    await setup_bot_handlers()
                    logger.info("Bot handlers initialized")
                    break
            except Exception as e:
                logger.error(f"Bot initialization attempt failed: {e}")
                retry_count += 1
                if retry_count < max_retries:
                    await asyncio.sleep(10)

        if retry_count == max_retries:
            raise HTTPException(status_code=503, detail="Bot initialization failed")

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
        
        # Set up webhook with retries
        webhook_success = False
        webhook_retries = 3
        while webhook_retries > 0:
            if await setup_webhook():
                webhook_success = True
                break
            webhook_retries -= 1
            if webhook_retries > 0:
                await asyncio.sleep(30)  # Longer wait between webhook setup attempts
        
        if not webhook_success:
            logger.warning("Proceeding without webhook - will retry during health checks")
                
        yield
        
    except Exception as e:
        logger.error(f"Startup error: {str(e)}")
        raise
    finally:
        if 'client' in globals() and client and client.is_connected():
            await client.disconnect()
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
        "status": "unhealthy",
        "checks": {
            "database": False,
            "bot": False,
            "webhook": False
        },
        "timestamp": datetime.utcnow().isoformat()
    }
    
    try:
        # Check database with timeout
        db_check = asyncio.create_task(wait_for_db())
        try:
            health["checks"]["database"] = await asyncio.wait_for(db_check, timeout=5.0)
        except asyncio.TimeoutError:
            logger.warning("Database health check timed out")
        
        # Check bot connection with timeout
        bot_check = asyncio.create_task(check_bot_auth())
        try:
            health["checks"]["bot"] = await asyncio.wait_for(bot_check, timeout=5.0)
        except asyncio.TimeoutError:
            logger.warning("Bot health check timed out")
            
        # Check webhook with timeout
        webhook_check = asyncio.create_task(get_webhook_info())
        try:
            current_webhook = await asyncio.wait_for(webhook_check, timeout=5.0)
            health["checks"]["webhook"] = (current_webhook == WEBHOOK_URL)
        except asyncio.TimeoutError:
            logger.warning("Webhook health check timed out")
            
        # Determine overall health status
        all_checks = health["checks"].values()
        if all(all_checks):
            health["status"] = "healthy"
        elif any(all_checks):
            health["status"] = "degraded"
        
        # Return appropriate status code
        status_code = 200 if health["status"] == "healthy" else 503
        return JSONResponse(content=health, status_code=status_code)
            
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        health["error"] = str(e)
        return JSONResponse(content=health, status_code=503)

@app.post(WEBHOOK_PATH)
async def handle_webhook(request: Request):
    """Handle incoming webhook updates"""
    try:
        # Only check secret if it's configured
        if WEBHOOK_SECRET:
            secret = request.headers.get('X-Telegram-Bot-Api-Secret-Token')
            if secret != WEBHOOK_SECRET:
                logger.warning("Invalid webhook secret received")
                raise HTTPException(status_code=403, detail="Invalid secret token")

        update_data = await request.json()
        update = types.Update.from_dict(update_data)

        # Handle different types of updates
        if update.message:
            await handle_message(update.message)
        elif update.callback_query:
            await handle_callback_query(update.callback_query)

        return Response(status_code=200)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error handling webhook: {e}")
        return Response(status_code=500)

# Update main to run both bot and web server
if __name__ == "__main__":
    import asyncio
    import uvicorn
    
    async def run_server():
        config = uvicorn.Config(
            "webhook_server:app",
            host="0.0.0.0",
            port=PORT,
            log_level="info"
        )
        server = uvicorn.Server(config)
        await server.serve()

    async def main():
        # Run both the bot and the web server
        await asyncio.gather(
            run_server(),
            client.run_until_disconnected()
        )

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    except Exception as e:
        logger.error(f"Fatal error: {str(e)}")
        raise
