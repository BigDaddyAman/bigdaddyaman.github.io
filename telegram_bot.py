import logging
from fastapi import FastAPI, Request
from telethon import TelegramClient, events, Button, errors
from telethon.tl.types import Document, DocumentAttributeFilename, InputPeerUser
from telethon.errors.rpcerrorlist import UserIsBlockedError, FloodWaitError, UserDeactivatedError
import uuid
import re
import math
from datetime import datetime, timedelta  # Add timedelta import here
import base64
from dotenv import load_dotenv
import os
import asyncio
from database import (
    init_db, store_file_metadata, store_token,
    get_file_by_id, get_file_by_token, search_files, count_search_results,
    AsyncPostgresConnection
)
from userdb import (
    init_user_db, add_user, get_all_users, 
    get_user_count, update_user_activity, get_active_users_count
)
from premium import init_premium_db, is_premium, add_or_renew_premium, get_premium_status
from telethon.sessions import MemorySession  # Add this import
from telethon.tl.types import (
    InputPeerChannel,
    ChannelParticipantsSearch
)

from telethon.tl.functions.channels import GetParticipantRequest
import json
import aiohttp
from fastapi.middleware.cors import CORSMiddleware

# Add these imports at the top
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,  # Change to INFO to reduce verbosity
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

# Your API ID, hash, and bot token
api_id = int(os.getenv('API_ID'))
api_hash = os.getenv('API_HASH')
bot_token = os.getenv('BOT_TOKEN')

# Configure FastAPI
from contextlib import asynccontextmanager

# Move client initialization after event loop setup
client = None
application = None

async def setup_clients():
    global client, application
    
    # Initialize TelegramClient
    client = TelegramClient(
        MemorySession(),
        api_id,
        api_hash,
        connection_retries=None,
        auto_reconnect=True
    )
    
    # Initialize python-telegram-bot application
    application = Application.builder().token(bot_token).build()
    
    # Start both clients
    await client.start(bot_token=bot_token)
    await application.initialize()
    
    return client, application

@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        # Initialize databases first
        await init_db()
        await init_user_db()
        await init_premium_db()
        
        # Initialize bot and clients
        await setup_clients()
        await init_bot()
        
        logger.info("Bot started successfully")
        yield
    except Exception as e:
        logger.error(f"Startup error: {e}")
        raise
    finally:
        # Cleanup
        if client:
            await client.disconnect()
        if application:
            await application.shutdown()

# Update FastAPI app initialization
app = FastAPI(lifespan=lifespan)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

VIDEO_EXTENSIONS = ['.mp4', '.mkv', '.webm', '.ts', '.mov', '.avi', '.flv', '.wmv', '.m4v', '.mpeg', '.mpg', '.3gp', '.3g2']

# List of authorized user IDs
AUTHORIZED_USER_IDS = [7951420571, 1509468839]  # Replace with your user ID and future moderator IDs

# Add this constant near the top with other constants
REQUIRED_CHANNEL = -1001457047091  # Use channel ID instead of username
CHANNEL_INVITE_LINK = "https://t.me/+EdVjRJbcJUBmYWJl"  # Add invite link

# Add bot username constant near the top with other constants
BOT_USERNAME = "@Kakifilemv1Bot"

# Add this function near the top with other utility functions
def format_filename(filename: str) -> str:
    """Format filename consistently when storing or displaying"""
    if not filename:
        return filename
        
    # First extract any years from the filename
    years = re.findall(r'[\[\(\{]?((?:19|20)\d{2})[\]\}\)]?', filename)
    
    # Create clean version without any brackets
    clean = re.sub(r'[\[\(\{].*?[\]\}\)]', '.', filename)
    clean = re.sub(r'[^a-zA-Z0-9.]', '.', clean)
    
    # Clean up dots
    clean = re.sub(r'\.+', '.', clean)
    clean = clean.strip('.')
    
    # If we found a year, make sure it's included in correct format
    if years:
        year = years[0]  # Take first year found
        # Remove any existing year from clean name
        clean = re.sub(r'\.?\d{4}\.?', '.', clean)
        # Split into parts and insert year after title
        parts = clean.split('.')
        if len(parts) > 1:
            # Insert year after first part (title)
            parts.insert(1, year)
        else:
            # Just append year if single part
            parts.append(year)
        clean = '.'.join(parts)
    
    # Final cleanup of multiple dots
    clean = re.sub(r'\.+', '.', clean)
    clean = clean.strip('.')
    
    return clean

# Add this new function near other utility functions
def format_caption(caption: str) -> str:
    """Format caption with dots instead of spaces and remove special characters"""
    if not caption:
        return caption
        
    # Remove "Credit" line if exists
    caption = re.sub(r'\nCredit.*', '', caption)
    
    # First extract any years from the caption
    years = re.findall(r'[\[\(\{]?((?:19|20)\d{2})[\]\}\)]?', caption)
    
    # Replace special characters with dots, but keep brackets/parentheses temporarily
    clean = caption
    clean = re.sub(r'[^a-zA-Z0-9\s\(\)\[\]\{\}]', '.', clean)
    
    # Remove brackets but keep their content
    clean = re.sub(r'[\(\[\{]', '.', clean)
    clean = re.sub(r'[\)\]\}]', '.', clean)
    
    # Replace spaces with dots
    clean = re.sub(r'\s+', '.', clean)
    
    # Clean up multiple dots
    clean = re.sub(r'\.+', '.', clean)
    
    # Remove leading/trailing dots
    clean = clean.strip('.')
    
    return clean

# Add this new function near other utility functions
def format_button_text(text: str) -> str:
    """Format button text to be concise with dots"""
    if not text:
        return "Unknown File"
        
    # First extract any years from the text
    years = re.findall(r'[\[\(\{]?((?:19|20)\d{2})[\]\}\)]?', text)
    
    # Replace special characters with dots
    clean = re.sub(r'[^a-zA-Z0-9\s\(\)\[\]\{\}]', '.', text)
    
    # Remove brackets but keep their content
    clean = re.sub(r'[\(\[\{]', '.', clean)
    clean = re.sub(r'[\)\]\}]', '.', clean)
    
    # Replace spaces with dots
    clean = re.sub(r'\s+', '.', clean)
    
    # Clean up multiple dots
    clean = re.sub(r'\.+', '.', clean)
    
    # Remove leading/trailing dots
    clean = clean.strip('.')
    
    return clean

def normalize_keyword(keyword):
    # Remove all special characters and replace with space
    keyword = re.sub(r'[^a-zA-Z0-9\s]', ' ', keyword).lower()
    keyword = re.sub(r'\s+', ' ', keyword)  # Replace multiple spaces with single space
    return keyword.strip()

def split_keywords(keyword):
    # Split the normalized keyword into individual words
    return keyword.split()

# Replace the existing is_user_in_channel function
async def is_user_in_channel(client, user_id):
    try:
        # First check if user is admin
        if user_id in AUTHORIZED_USER_IDS:
            logger.info(f"Admin user {user_id} detected, skipping channel check")
            return True
            
        try:
            # Try to get channel entity directly using ID
            channel = await client.get_entity(REQUIRED_CHANNEL)  # Use integer directly
            participant = await client(GetParticipantRequest(
                channel=channel,
                participant=user_id
            ))
            logger.info(f"User {user_id} found in channel")
            return True
        except Exception as e:
            if "USER_NOT_PARTICIPANT" in str(e):
                return False
            logger.warning(f"Channel check error: {e}")
            return False
            
    except Exception as e:
        logger.error(f"Channel membership check error: {e}")
        # If we can't verify, assume not in channel for safety
        return False

# Add error handler for the client
@client.on(events.NewMessage)
async def error_handler(event):
    try:
        # Your existing event handling code here
        # ...
        raise events.StopPropagation
    except events.StopPropagation:
        pass  # Stop propagation is expected, do nothing
    except Exception as e:
        logger.error(f"Uncaught error: {str(e)}", exc_info=True)

async def init_bot():
    try:
        # Get bot info
        bot_info = await client.get_me()
        logger.info(f"Bot initialized: @{bot_info.username}")
        
        # Get channel info and verify bot's admin status - MODIFIED
        try:
            channel = await client.get_entity(REQUIRED_CHANNEL)  # Use integer directly
            participant = await client(GetParticipantRequest(
                channel=channel,
                participant=bot_info.id
            ))
            
            if not participant.participant.admin_rights:
                logger.warning("⚠️ Bot is not an admin in the channel!")
            else:
                logger.info("✅ Bot confirmed as channel admin")
                
        except ValueError as e:
            logger.error(f"Channel access error: {e}")
            raise
            
    except Exception as e:
        logger.error(f"Bot initialization error: {e}")
        raise

@app.post(os.getenv('WEBHOOK_PATH'))
async def telegram_webhook(request: Request):
    try:
        update = await request.json()
        
        # Single entry point for all updates
        if 'message' in update:
            await handle_message(update['message'])
        elif 'callback_query' in update:
            await handle_callback(update['callback_query'])
            
        return {'ok': True}
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return {'ok': False}

# Use Telegram Bot API instead of Telethon for sending messages
async def send_message(chat_id, text, reply_markup=None):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
        
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as resp:
            return await resp.json()

# Keep Telethon only for file operations
# Use regular Bot API for everything else

# Add handlers for different message types
async def handle_start_command(message):
    # Implementation of /start command handler
    # ...existing start command logic...
    pass

async def handle_stats_command(message):
    # Implementation of /stats command handler  
    # ...existing stats command logic...
    pass

async def handle_broadcast_command(message):
    # Implementation of /broadcast command handler
    # ...existing broadcast command logic... 
    pass

async def handle_search_query(message):
    # Implementation of search query handler
    # ...existing search logic...
    pass

async def handle_document_upload(message):
    # Implementation of document upload handler
    # ...existing document handling logic...
    pass

async def handle_callback_query(callback_query):
    # Implementation of callback query handler
    # ...existing callback query logic...
    pass

async def main():
    try:
        # Initialize bot first
        await init_bot()
        
        # Then initialize databases
        await init_db()
        await init_user_db()
        await init_premium_db()
        
        # Start bot
        await client.start()
        logger.info("Main bot created")

        # Add a test message to verify bot is working
        logger.info("Bot is now running and listening for messages...")

        # Modify the start function
        @client.on(events.NewMessage(pattern='/start'))
        async def start(event):
            # Check channel membership first
            if not await is_user_in_channel(client, event.sender_id):
                keyboard = [
                    [Button.url("Join Channel", CHANNEL_INVITE_LINK)]
                ]
                await event.reply(
                    "⚠️ Welcome! You must join our channel first to use this bot!\n\n"
                    "1. Click the button below to join\n"
                    "2. After joining, come back and send /start again",
                    buttons=keyboard
                )
                return

            user = event.sender
            await add_user(
                user_id=user.id,
                username=user.username,
                first_name=user.first_name,
                last_name=user.last_name
            )
            command_args = event.message.text.split()
            if len(command_args) > 1:
                token = command_args[1]
                try:
                    decoded_token = base64.urlsafe_b64decode(token.encode()).decode()
                    logger.debug(f"Decoded token: {decoded_token}")

                    result = await get_file_by_token(token)
                    logger.debug(f"Token verification result: {result}")

                    if result:
                        file_id = result

                        file_info = await get_file_by_id(file_id)
                        logger.debug(f"File fetch result: {file_info}")

                        if file_info:
                            # Note: asyncpg returns Record object, access by key
                            id = file_info['id']
                            access_hash = file_info['access_hash']
                            file_reference = file_info['file_reference']
                            mime_type = file_info['mime_type']
                            file_name = file_info['file_name']

                            formatted_caption = file_name.replace(" ", ".").replace("@", "")

                            document = Document(
                                id=int(id),
                                access_hash=int(access_hash),
                                file_reference=bytes(file_reference),  # Convert memoryview to bytes
                                date=None,
                                mime_type=mime_type,
                                size=None,
                                dc_id=None,
                                attributes=[DocumentAttributeFilename(file_name=file_name)]
                            )

                            try:
                                await client.send_file(
                                    event.sender_id,
                                    file=document,
                                    caption=f"{format_caption(file_info['caption'])}\n\n{BOT_USERNAME}"  # Modified
                                )
                                logger.info(f"File {file_name} sent successfully.")
                            except Exception as e:
                                logger.error(f"Error sending file: {e}")
                                await event.respond('Failed to send the file.')
                        else:
                            await event.respond('File not found in the database.')
                            logger.error("File not found in the database.")
                    else:
                        await event.respond('Invalid token.')
                        logger.error("Invalid token.")
                except (ValueError, UnicodeDecodeError) as e:
                    logger.error(f"Token decoding error: {e}")
                    await event.respond('Failed to decode the token. Please try again.')
            else:
                await event.respond('Hantar movies apa yang anda mahu.')
                logger.warning("No token provided.")

        @client.on(events.NewMessage)
        async def handle_messages(event):
            if event.is_private:
                # Check channel membership first
                if not await is_user_in_channel(client, event.sender_id):
                    keyboard = [
                        [Button.url("Join Channel", CHANNEL_INVITE_LINK)]
                    ]
                    await event.reply(
                        "⚠️ You must join our channel first to use this bot!\n\n"
                        "1. Click the button below to join\n"
                        "2. After joining, come back and try again",
                        buttons=keyboard
                    )
                    return

                await update_user_activity(event.sender_id)
                if event.message.document:
                    try:
                        user_id = event.message.sender_id
                        logger.debug(f"User ID: {user_id}")

                        if user_id not in AUTHORIZED_USER_IDS:
                            await event.reply("Maaf, anda tidak dibenarkan menghantar media kepada bot ini.")
                            return

                        document = event.message.document
                        file_name = None
                        for attr in event.message.document.attributes:
                            if isinstance(attr, DocumentAttributeFilename):
                                file_name = format_filename(attr.file_name)  # Format filename when storing
                                break

                        caption = event.message.message or ""
                        keywords = normalize_keyword(caption) + " " + normalize_keyword(file_name)
                        keyword_list = split_keywords(keywords)

                        logger.debug(f"Received document message: {event.message}")
                        logger.debug(f"Caption: {caption}")
                        logger.debug(f"Keywords: {keywords}")
                        logger.debug(f"File Name: {file_name}")
                        logger.debug(f"Mime Type: {document.mime_type}")

                        # Convert id and access_hash to strings before storing
                        id = str(document.id)
                        access_hash = str(document.access_hash)
                        file_reference = document.file_reference
                        mime_type = document.mime_type

                        logger.debug(f"Inserting file metadata: id={id}, access_hash={access_hash}, file_reference={file_reference}, mime_type={mime_type}, caption={caption}, keywords={keywords}, file_name={file_name}")
                        await store_file_metadata(id, access_hash, file_reference, mime_type, caption, keywords, file_name)
                        await event.reply('File metadata stored.')
                    except Exception as e:
                        logger.error(f"Error handling document message: {e}")
                        await event.reply('Failed to store file metadata.')

                elif event.message.text:
                    try:
                        if event.message.text.startswith('/'):
                            return

                        text = normalize_keyword(event.message.text.lower().strip())
                        keyword_list = split_keywords(text)

                        page = 1  # Default to first page
                        page_size = 10  # Number of results per page
                        offset = (page - 1) * page_size

                        db_results = await search_files(keyword_list, page_size, offset)

                        total_results = await count_search_results(keyword_list)
                        total_pages = math.ceil(total_results / page_size)

                        video_results = [result for result in db_results if any(result[2].lower().endswith(ext) for ext in VIDEO_EXTENSIONS)]

                        if video_results:
                            header = f"{total_results} Results for '{text}'"
                            buttons = []
                            for result in video_results:
                                id, caption, file_name, rank = result  # Unpack all 4 values
                                token = await store_token(str(id))
                                if token:
                                    import urllib.parse
                                    display_name = format_button_text(file_name or caption or "Unknown File")  # Modified
                                    safe_video_name = urllib.parse.quote(file_name, safe='')
                                    safe_token = urllib.parse.quote(token, safe='')
                                    if await is_premium(event.sender_id):
                                        buttons.append([Button.inline(display_name, f"{id}|{page}")])
                                    else:
                                        website_link = f"https://bigdaddyaman.github.io?token={safe_token}&videoName={safe_video_name}"
                                        buttons.append([Button.url(display_name, website_link)])
                            
                            # Pagination Buttons
                            pagination_buttons = []
                            start_page = max(1, page - 2)
                            end_page = min(total_pages, start_page + 4)

                            for p in range(start_page, end_page + 1):
                                if p == page:
                                    pagination_buttons.append(Button.inline(f"[{p}]", f"ignore|{text}|{p}"))
                                else:
                                    pagination_buttons.append(Button.inline(str(p), f"page|{text}|{p}"))

                            if page > 1:
                                pagination_buttons.insert(0, Button.inline("Prev", f"page|{text}|{page - 1}"))
                            if page < total_pages:
                                pagination_buttons.append(Button.inline("Next", f"page|{text}|{page + 1}"))

                            buttons.append(pagination_buttons)
                            if total_pages > 1:
                                buttons.append([
                                    Button.inline("First Page", f"page|{text}|1"),
                                    Button.inline("Last Page", f"page|{total_pages}")  # Added text parameter
                                ])

                            await event.respond(header, buttons=buttons)
                        else:
                            await event.reply('Movies yang anda cari belum ada boleh request di @Request67_bot.')
                    except Exception as e:
                        logger.error(f"Error handling text message: {e}")
                        await event.reply('Failed to process your request.')

        @client.on(events.CallbackQuery)
        async def callback_query_handler(event):
            try:
                data = event.data.decode('utf-8')
                user_id = event.sender_id
                
                if data.startswith("page|"):
                    parts = data.split("|")
                    if len(parts) < 3:
                        return  # Silently ignore invalid page data
                        
                    _, keyword, page = parts
                    page = int(page)
                    page_size = 10
                    offset = (page - 1) * page_size
                    
                    keyword_list = split_keywords(keyword)
                    db_results = await search_files(keyword_list, page_size, offset)
                    total_results = await count_search_results(keyword_list)
                    total_pages = math.ceil(total_results / page_size)
                    
                    video_results = [result for result in db_results if any(result[2].lower().endswith(ext) for ext in VIDEO_EXTENSIONS)]
                    
                    if video_results:
                        header = f"{total_results} Results for '{keyword}'"
                        buttons = []
                        for result in video_results:
                            id, caption, file_name, rank = result
                            token = await store_token(str(id))
                            if token:
                                import urllib.parse
                                display_name = format_button_text(file_name or caption or "Unknown File")  # Modified
                                safe_video_name = urllib.parse.quote(file_name, safe='')
                                safe_token = urllib.parse.quote(token, safe='')
                                
                                website_link = f"https://bigdaddyaman.github.io?token={safe_token}&videoName={safe_video_name}"
                                buttons.append([Button.url(display_name, website_link)])
                        
                        # Pagination Buttons
                        pagination_buttons = []
                        start_page = max(1, page - 2)
                        end_page = min(total_pages, start_page + 4)
                        
                        if page > 1:
                            pagination_buttons.append(Button.inline("Prev", f"page|{keyword}|{page-1}"))
                        for p in range(start_page, end_page + 1):
                            if p == page:
                                pagination_buttons.append(Button.inline(f"[{p}]", f"ignore|{keyword}|{p}"))
                            else:
                                pagination_buttons.append(Button.inline(str(p), f"page|{keyword}|{p}"))
                        if page < total_pages:
                            pagination_buttons.append(Button.inline("Next", f"page|{keyword}|{page+1}"))
                        
                        buttons.append(pagination_buttons)

                        # Only add First/Last page buttons if there are more than one page
                        if total_pages > 1:
                            buttons.append([
                                Button.inline("First Page", f"page|{keyword}|1"),
                                Button.inline("Last Page", f"page|{total_pages}")  # Added keyword parameter
                            ])
                        
                        try:
                            await event.edit(header, buttons=buttons)
                        except errors.MessageNotModifiedError:
                            pass  # Silently ignore "message not modified" errors
                    else:
                        try:
                            await event.edit("No more results.")
                        except errors.MessageNotModifiedError:
                            pass
                            
                elif data.startswith("ignore|"):
                    # Do nothing for current page clicks
                    await event.answer("Current page")
                else:
                    # Handle direct file ID clicks for premium users
                    id, current_page = data.split("|")
                    file_info = await get_file_by_id(str(id))
                    
                    if not file_info:
                        await event.respond("File not found.")
                        return

                    if await is_premium(user_id):
                        # Premium users get direct file
                        document = Document(
                            id=int(file_info['id']),
                            access_hash=int(file_info['access_hash']),
                            file_reference=bytes(file_info['file_reference']),
                            date=None,
                            mime_type=file_info['mime_type'],
                            size=None,
                            dc_id=None,
                            attributes=[DocumentAttributeFilename(file_name=file_info['file_name'])]
                        )

                        try:
                            progress_msg = await event.respond("🎖 Premium user detected! Preparing your file...")
                            await asyncio.sleep(1.5)
                            
                            await client.send_file(
                                event.sender_id,
                                file=document,
                                caption=f"{format_caption(file_info['caption'])}\n\n{BOT_USERNAME}"  # Modified
                            )
                            await progress_msg.delete()
                        except Exception as e:
                            logger.error(f"Error sending file to premium user: {e}")
                            await progress_msg.edit('⚠️ Failed to send file. Please try again or contact support.')
                    else:
                        # Free users get website link - direct open without confirmation
                        token = await store_token(str(id))
                        if token:
                            video_name = file_info['file_name']
                            import urllib.parse
                            safe_video_name = urllib.parse.quote(video_name, safe='')
                            safe_token = urllib.parse.quote(token, safe='')
                            website_link = f"https://bigdaddyaman.github.io?token={safe_token}&videoName={safe_video_name}"
                            # Use new message with URL button instead of answer
                            buttons = [[Button.url("🎬 Download Movie", website_link)]]
                            await event.edit("Choose download option:", buttons=buttons)
                        else:
                            await event.respond("Failed to generate download link.")

            except Exception as e:
                # Silently log errors without showing to user
                logger.error(f"Error in callback query handler: {e}")
                return

        @client.on(events.NewMessage(pattern='/listdb'))
        async def list_db(event):
            logger.debug("Executing /listdb command")
            c.execute("SELECT * FROM files")
            results = c.fetchall()
            logger.debug(f"Database entries: {results}")
            await event.reply(f"Database entries: {results}")

        @client.on(events.NewMessage(pattern='/stats'))
        async def stats_command(event):
            if event.sender_id not in AUTHORIZED_USER_IDS:
                await event.reply("You are not authorized to use this command.")
                return
                
            user_count = await get_user_count()
            active_users = await get_active_users_count()  # Add this function to userdb.py
            
            stats_message = (
                "📊 Bot Statistics 📊\n\n"
                f"👥 Total Users: {user_count}\n"
                f"📱 Active Users (24h): {active_users}\n"
                f"🤖 Bot Status: Online\n"
                f"⏰ Last Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                "Admin Commands:\n"
                "• /broadcast - Send message to all users\n"
                "• /stats - Show these statistics"
            )
            
            await event.reply(stats_message)

        @client.on(events.NewMessage(pattern='/broadcast'))
        async def broadcast_command(event):
            if event.sender_id not in AUTHORIZED_USER_IDS:
                await event.reply("You are not authorized to use this command.")
                return
            
            # Get the message to broadcast
            reply = await event.get_reply_message()
            if not reply and not event.message.text.replace('/broadcast', '').strip():
                usage = (
                    "Usage:\n"
                    "1. Text broadcast: /broadcast your message\n"
                    "2. Media broadcast: Reply to a photo/video with /broadcast [caption]\n"
                    "3. Media without caption: Reply with '/broadcast none'\n"
                    "\nNote: Broadcast will not be sent to admin users."
                )
                await event.reply(usage)
                return
                
            users = await get_all_users()
            sent = 0
            failed = 0
            skipped = 0
            blocked = 0
            invalid = 0
            
            # Show progress message
            progress = await event.reply("🚀 Broadcasting message...")
            
            try:
                for user in users:
                    user_id = user['user_id']
                    
                    # Skip if user is an admin
                    if user_id in AUTHORIZED_USER_IDS:
                        skipped += 1
                        continue
                        
                    try:
                        # Get peer directly from ID
                        try:
                            peer = await client.get_input_entity(user_id)
                            if not peer:
                                raise ValueError("Could not get peer")
                        except (ValueError, TypeError):
                            # Try getting entity from API
                            try:
                                full_user = await client.get_entity(user_id)
                                if full_user:
                                    peer = await client.get_input_entity(full_user)
                                else:
                                    raise ValueError("Could not get user entity")
                            except:
                                invalid += 1
                                logger.warning(f"Could not resolve user {user_id}")
                                continue

                        # Add delay between messages
                        await asyncio.sleep(0.5)

                        if reply:
                            if reply.media:
                                caption = None
                                if event.message.text.strip().lower() != '/broadcast none':
                                    caption = event.message.text.replace('/broadcast', '').strip() or reply.text
                                
                                try:
                                    await client.send_file(
                                        peer,
                                        file=reply.media,
                                        caption=caption
                                    )
                                    sent += 1
                                except Exception as e:
                                    logger.error(f"Error sending media to {user_id}: {e}")
                                    failed += 1
                            else:
                                try:
                                    await client.send_message(peer, reply.text)
                                    sent += 1
                                except Exception as e:
                                    logger.error(f"Error sending text to {user_id}: {e}")
                                    failed += 1
                        else:
                            message = event.message.text.replace('/broadcast', '').strip()
                            try:
                                await client.send_message(peer, message)
                                sent += 1
                            except Exception as e:
                                logger.error(f"Error sending message to {user_id}: {e}")
                                failed += 1

                        if sent % 5 == 0:
                            await progress.edit(
                                f"🚀 Broadcasting...\n"
                                f"✅ Sent: {sent}\n"
                                f"❌ Failed: {failed}\n"
                                f"🚫 Blocked: {blocked}\n"
                                f"⚠️ Invalid: {invalid}\n"
                                f"⏩ Skipped (admins): {skipped}"
                            )
                        
                    except UserIsBlockedError:
                        blocked += 1
                        logger.warning(f"User {user_id} has blocked the bot")
                    except FloodWaitError as e:
                        wait_time = e.seconds
                        logger.warning(f"Hit flood limit. Waiting {wait_time} seconds")
                        await progress.edit(f"Hit rate limit. Waiting {wait_time} seconds before continuing...")
                        await asyncio.sleep(wait_time)
                    except Exception as e:
                        logger.error(f"Unexpected error for user {user_id}: {e}")
                        failed += 1

            finally:
                report = (
                    "📬 Broadcast Completed\n\n"
                    f"✅ Successfully sent: {sent}\n"
                    f"❌ Failed: {failed}\n"
                    f"🚫 Blocked: {blocked}\n"
                    f"⚠️ Invalid users: {invalid}\n"
                    f"⏩ Skipped (admins): {skipped}\n"
                    f"👥 Total reach: {sent + failed + blocked + invalid}\n"
                    f"📊 Success rate: {(sent/(sent+failed+blocked+invalid)*100 if sent+failed+blocked+invalid>0 else 0):.1f}%\n\n"
                    f"Total users in database: {len(users)}"
                )
                await progress.edit(report)

        @client.on(events.NewMessage(pattern='/renew'))
        async def renew_premium(event):
            if event.sender_id not in AUTHORIZED_USER_IDS:
                await event.reply("You are not authorized to use this command.")
                return

            try:
                args = event.message.text.split()
                if len(args) != 3:
                    await event.reply("Usage: /renew <user_id> <days>")
                    return

                user_id = int(args[1])
                days = int(args[2])

                if await add_or_renew_premium(user_id, days):
                    expiry_date = (datetime.now() + timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
                    success_message = (
                        "✅ Premium access granted!\n\n"
                        f"👤 User ID: {user_id}\n"
                        f"⏳ Duration: {days} days\n"
                        f"📅 Expires: {expiry_date}"
                    )
                    await event.reply(success_message)
                else:
                    await event.reply("Failed to renew premium subscription.")
            except ValueError:
                await event.reply("Invalid user ID or number of days.")
            except Exception as e:
                logger.error(f"Error in renew_premium: {e}")
                await event.reply("An error occurred while processing the request.")

        @client.on(events.NewMessage(chats=-1002459978004))  # Your backup channel ID
        async def handle_channel_messages(event):
            try:
                if event.message.document:
                    document = event.message.document
                    file_name = None
                    for attr in event.message.document.attributes:
                        if isinstance(attr, DocumentAttributeFilename):
                            file_name = attr.file_name
                            break

                    caption = event.message.message or ""
                    keywords = normalize_keyword(caption) + " " + normalize_keyword(file_name)
                    keyword_list = split_keywords(keywords)

                    logger.info(f"Auto-storing file from channel: {file_name}")
                    
                    # Convert id and access_hash to strings before storing
                    id = str(document.id)
                    access_hash = str(document.access_hash)
                    file_reference = document.file_reference
                    mime_type = document.mime_type

                    await store_file_metadata(
                        id=id,
                        access_hash=access_hash,
                        file_reference=file_reference,
                        mime_type=mime_type,
                        caption=caption,
                        keywords=keywords,
                        file_name=file_name
                    )
                    logger.info(f"Successfully stored metadata for {file_name}")

            except Exception as e:
                logger.error(f"Error processing channel message: {e}")

        # Add this function near other command handlers
        @client.on(events.NewMessage(pattern='/migrate'))
        async def migrate_command(event):
            if event.sender_id not in AUTHORIZED_USER_IDS:
                await event.reply("You are not authorized to use this command.")
                return
                
            try:
                progress_msg = await event.reply("Starting filename migration...")
                conn = await AsyncPostgresConnection().__aenter__()
                
                # Get all files
                rows = await conn.fetch('SELECT id, file_name FROM files')
                total = len(rows)
                updated = 0
                last_update = 0
                
                for row in rows:
                    try:
                        old_name = row['file_name']
                        if not old_name:
                            continue
                            
                        new_name = format_filename(old_name)
                        
                        if old_name != new_name:
                            await conn.execute(
                                'UPDATE files SET file_name = $1 WHERE id = $2',
                                new_name, row['id']
                            )
                            updated += 1
                            
                            # Show sample of changes every 50 files
                            if updated % 50 == 0 and updated != last_update:
                                try:
                                    await progress_msg.edit(
                                        f"Migration in progress...\n"
                                        f"Updated: {updated}/{total} files\n"
                                        f"Example: {old_name} → {new_name}\n"
                                        f"Please wait..."
                                    )
                                    last_update = updated
                                    await asyncio.sleep(2)
                                except Exception as e:
                                    logger.error(f"Error updating progress: {e}")
                                    pass
                    
                    except Exception as e:
                        logger.error(f"Error processing file {row['id']}: {e}")
                        continue
                
                # Final update
                try:
                    final_message = (
                        "✅ Filename migration completed!\n\n"
                        f"📊 Total files processed: {total}\n"
                        f"🔄 Files updated: {updated}\n\n"
                        "All filenames now use dots instead of spaces"
                    )
                    await progress_msg.edit(final_message)
                except:
                    await event.respond(final_message)
                    
            except Exception as e:
                error_msg = f"Migration error: {str(e)}"
                logger.error(error_msg)
                await event.respond(error_msg)
            finally:
                if conn:
                    await conn.close()

        await client.run_until_disconnected()
    except Exception as e:
        logger.error(f"Critical error in main: {str(e)}", exc_info=True)
        raise

# Add telegram-bot-api handlers
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Use telegram-bot-api for basic message
    if not await is_user_in_channel(client, update.effective_user.id):
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Join Channel", url=CHANNEL_INVITE_LINK)]
        ])
        await update.message.reply_text(
            "⚠️ Welcome! You must join our channel first!\n\n"
            "1. Click the button below to join\n"
            "2. After joining, come back and try again",
            reply_markup=keyboard
        )
        return

    # Use Telethon only for file operations when needed
    if len(context.args) > 0:
        token = context.args[0]
        # ...existing file handling code...
    else:
        await update.message.reply_text('Hantar movies apa yang anda mahu.')

async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.lower().strip()
    # ...existing search logic but use telegram-bot-api for buttons...
    keyboard = []
    for result in video_results:
        # Convert Telethon buttons to telegram-bot-api buttons
        keyboard.append([InlineKeyboardButton(
            text=display_name,
            url=website_link
        )])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(header, reply_markup=reply_markup)

# Add this function to handle startup
async def start():
    try:
        # Initialize event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Initialize clients
        await setup_clients()
        
        # Initialize bot handlers
        application.add_handler(CommandHandler("start", start_command))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_command))
        
        # Run application
        async with application:
            await application.run_polling(allowed_updates=Update.ALL_TYPES)
            
    except Exception as e:
        logger.error(f"Error in start(): {e}")
        raise

if __name__ == "__main__":
    try:
        # Delete session file if exists
        session_file = 'bot.session'
        if os.path.exists(session_file):
            os.remove(session_file)
            logger.info(f"Deleted session file: {session_file}")
        
        # Create and set event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Run everything in the same loop
        loop.run_until_complete(start())
        loop.run_forever()
        
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {str(e)}", exc_info=True)
        raise
    finally:
        loop.stop()
        loop.close()

