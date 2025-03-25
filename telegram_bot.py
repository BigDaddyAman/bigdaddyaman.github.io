import logging
from telethon import TelegramClient, events, Button, errors
from telethon.tl.types import Document, DocumentAttributeFilename, InputPeerUser, InputPeerChannel, ChannelParticipantsSearch
from telethon.errors.rpcerrorlist import UserIsBlockedError, FloodWaitError, UserDeactivatedError
from telethon.sessions import MemorySession
from telethon.tl.functions.channels import GetParticipantRequest
from telethon.tl.functions.bots import SetBotCommandsRequest
from telethon.tl.types import BotCommand
from fastapi import FastAPI, Request
import aiohttp
import uuid
import re
import math
import urllib.parse
from datetime import datetime, timedelta
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

# Load environment variables and configure logging
load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', datefmt='%H:%M:%S')
logger = logging.getLogger(__name__)

# Initialize settings and client
_client = None
app = FastAPI()

# Bot settings
api_id = int(os.getenv('API_ID'))
api_hash = os.getenv('API_HASH')
bot_token = os.getenv('BOT_TOKEN')
WEBHOOK_PATH = f"/webhook/{bot_token}"
WEBHOOK_HOST = os.getenv('WEBHOOK_HOST', 'https://worker-production-0a82.up.railway.app')
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"
PORT = int(os.getenv('PORT', 8000))

# Constants
VIDEO_EXTENSIONS = ['.mp4', '.mkv', '.webm', '.ts', '.mov', '.avi', '.flv', '.wmv', '.m4v', '.mpeg', '.mpg', '.3gp', '.3g2']
AUTHORIZED_USER_IDS = [7951420571, 1509468839]
REQUIRED_CHANNEL = -1001457047091
CHANNEL_INVITE_LINK = "https://t.me/+EdVjRJbcJUBmYWJl"
BOT_USERNAME = "@Kakifilemv1Bot"

# Client management functions
async def get_client():
    """Get the current client instance"""
    global _client
    if not _client:
        _client = await initialize_client()
    return _client

async def initialize_client():
    """Initialize and return the Telegram client"""
    global _client
    if not _client:
        _client = TelegramClient(
            MemorySession(),
            api_id,
            api_hash,
            system_version="4.16.30-vxCUSTOM",
            device_model="Railway Server"
        )
        await _client.connect()
        await _client.start(bot_token=bot_token)
    return _client

# Utility functions
def format_filename(filename: str) -> str:
    """Format filename consistently when storing or displaying"""
    if not filename:
        return filename

    # First extract any years from the filename
    years = re.findall(r'[\[\(\{]?((?:19|20)\d{2})[\]\}\)]?', filename)
    
    # Create clean version without any brackets
    clean = re.sub(r'[\[\(\{].*?[\]\}\)]', '.', filename)
    
    # Clean up dots
    clean = re.sub(r'[^a-zA-Z0-9.]', '.', clean)
    clean = re.sub(r'\.+', '.', clean)
    
    # If we found a year, make sure it's included in correct format
    clean = clean.strip('.')
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
        # Final cleanup of multiple dots
        clean = '.'.join(parts)
    
    # Final cleanup of multiple dots
    clean = re.sub(r'\.+', '.', clean)
    clean = clean.strip('.')
    return clean

def format_caption(caption: str) -> str:
    """Format caption with dots instead of spaces and remove special characters"""
    if not caption:
        return caption

    # Remove "Credit" line if exists
    caption = re.sub(r'\nCredit.*', '', caption)
        
    # First extract any years from the caption
    years = re.findall(r'[\[\(\{]?((?:19|20)\d{2})[\]\}\)]?', caption)
    
    # Replace special characters with dots, but keep brackets/parentheses temporarily
    clean = re.sub(r'[^a-zA-Z0-9\s\(\)\[\]\{\}]', '.', caption)
    
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

# Main handler functions
async def is_user_in_channel(client, user_id):
    try:
        # First check if user is admin
        if user_id in AUTHORIZED_USER_IDS:
            logger.info(f"Admin user {user_id} detected, skipping channel check")
            return True

        # Try to get channel entity directly using ID
        try:
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
        return False

async def handle_start(event, client):
    """Handle /start command"""
    if not await is_user_in_channel(client, event.sender_id):
        keyboard = [[Button.url("Join Channel", CHANNEL_INVITE_LINK)]]
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
    await event.respond('Nak tengok movie apa hari ni? 🎥 Hanya taip tajuknya, dan saya akan carikan untuk anda!')

async def handle_messages(event, client):
    """Handle incoming messages"""
    if event.is_private:
        if not await is_user_in_channel(client, event.sender_id):
            keyboard = [[Button.url("Join Channel", CHANNEL_INVITE_LINK)]]
            await event.reply(
                "⚠️ You must join our channel first to use this bot!\n\n"
                "1. Click the button below to join\n"
                "2. After joining, come back and try again",
                buttons=keyboard
            )
            return

        await update_user_activity(event.sender_id)

        if event.message.text and not event.message.text.startswith('/'):
            try:
                text = normalize_keyword(event.message.text.lower().strip())
                keyword_list = split_keywords(text)
                page = 1
                page_size = 10
                offset = (page - 1) * page_size
                
                # Search and format results
                db_results = await search_files(keyword_list, page_size, offset)
                total_results = await count_search_results(keyword_list)
                total_pages = math.ceil(total_results / page_size)
                video_results = [result for result in db_results if any(result[2].lower().endswith(ext) for ext in VIDEO_EXTENSIONS)]
                
                if video_results:
                    await send_search_results(event, text, video_results, page, total_pages, total_results)
                else:
                    await event.reply('Movies yang anda cari belum ada boleh request di @Request67_bot.')
            except Exception as e:
                logger.error(f"Error handling text message: {e}")
                await event.reply('Failed to process your request.')

async def handle_callback_query(event, client):
    """Handle callback queries"""
    try:
        data = event.data.decode('utf-8')
        if data.startswith("page|"):
            parts = data.split("|")
            text = parts[1]
            page = int(parts[2])
            page_size = 10
            offset = (page - 1) * page_size
            
            keyword_list = split_keywords(text)
            db_results = await search_files(keyword_list, page_size, offset)
            total_results = await count_search_results(keyword_list)
            total_pages = math.ceil(total_results / page_size)
            video_results = [result for result in db_results if any(result[2].lower().endswith(ext) for ext in VIDEO_EXTENSIONS)]
            
            if video_results:
                await send_search_results(event, text, video_results, page, total_pages, total_results, is_edit=True)
            else:
                await event.answer("No more results")
        elif data.startswith("current|"):
            await event.answer(f"Current page {data.split('|')[1]}")
    except Exception as e:
        logger.error(f"Error in callback handler: {e}")
        await event.answer("Error processing request", alert=True)

async def send_search_results(event, text, video_results, page, total_pages, total_results, is_edit=False):
    """Helper function to send or edit search results"""
    header = f"{total_results} Results for '{text}'"
    # Create result buttons
    buttons = []
    for result in video_results:
        id, caption, file_name, rank = result
        display_name = format_button_text(file_name or caption or "Unknown File")
        token = await store_token(str(id))
        if token:
            safe_video_name = urllib.parse.quote(file_name, safe='')
            safe_token = urllib.parse.quote(token, safe='')
            website_link = f"https://bigdaddyaman.github.io?token={safe_token}&videoName={safe_video_name}"
            buttons.append([Button.url(display_name, website_link)])
    
    # Add pagination if needed
    if total_pages > 1:
        pagination = []
        if page > 1:
            pagination.append(Button.inline("⬅️ Prev", f"page|{text}|{page-1}"))
        pagination.append(Button.inline(f"Page {page}/{total_pages}", f"current|{page}"))
        if page < total_pages:
            pagination.append(Button.inline("Next ➡️", f"page|{text}|{page+1}"))
        buttons.append(pagination)
    
    # Send or edit message
    if is_edit:
        await event.edit(header, buttons=buttons)
    else:
        await event.respond(header, buttons=buttons)

async def handle_webhook_message(data: dict, client):
    """Handle webhook message updates"""
    try:
        # Extract chat info from the message data
        chat = data.get('chat', {})
        chat_id = chat.get('id')
        chat_type = chat.get('type')
        
        if not chat_id or chat_type != 'private':
            logger.info(f"Skipping non-private chat: {chat_type}")
            return
            
        # Extract user info
        from_user = data.get('from', {})
        user_id = from_user.get('id')
        if not user_id:
            logger.warning("No user ID found in message")
            return

        # Check channel membership
        if not await is_user_in_channel(client, user_id):
            keyboard = [[Button.url("Join Channel", CHANNEL_INVITE_LINK)]]
            await client.send_message(
                chat_id,
                "⚠️ You must join our channel first to use this bot!\n\n"
                "1. Click the button below to join\n"
                "2. After joining, come back and try again",
                buttons=keyboard
            )
            return

        await update_user_activity(user_id)
        
        # Handle text messages
        text = data.get('text', '')
        if text and not text.startswith('/'):
            try:
                normalized_text = normalize_keyword(text.lower().strip())
                keyword_list = split_keywords(normalized_text)
                page = 1
                page_size = 10
                
                total_results = await count_search_results(keyword_list)
                if total_results > 0:
                    total_pages = math.ceil(total_results / page_size)
                    offset = (page - 1) * page_size
                    
                    db_results = await search_files(keyword_list, page_size, offset)
                    video_results = [r for r in db_results if any(r[2].lower().endswith(ext) for ext in VIDEO_EXTENSIONS)]
                    
                    if video_results:
                        buttons = []
                        header = f"🎬 {total_results} Results for '{text}'"
                        
                        # Create result buttons
                        for result in video_results:
                            id, caption, file_name, rank = result
                            token = await store_token(str(id))
                            if token:
                                display_name = format_button_text(file_name or caption or "Unknown File")
                                safe_video_name = urllib.parse.quote(file_name or '', safe='')
                                safe_token = urllib.parse.quote(token, safe='')
                                website_link = f"https://bigdaddyaman.github.io?token={safe_token}&videoName={safe_video_name}"
                                buttons.append([Button.url(display_name, website_link)])
                        
                        # Add pagination if needed
                        if total_pages > 1:
                            nav = []
                            nav.append(Button.inline("1️⃣", f"page|{normalized_text}|1"))
                            if page > 1:
                                nav.append(Button.inline("⬅️", f"page|{normalized_text}|{page-1}"))
                            nav.append(Button.inline(f"{page}/{total_pages}", f"current|{page}"))
                            if page < total_pages:
                                nav.append(Button.inline("➡️", f"page|{normalized_text}|{page+1}"))
                            nav.append(Button.inline(f"{total_pages}️⃣", f"page|{normalized_text}|{total_pages}"))
                            buttons.append(nav)
                        
                        await client.send_message(chat_id, header, buttons=buttons)
                        return
                
                await client.send_message(chat_id, 'Movies yang anda cari belum ada boleh request di @Request67_bot.')
                
            except Exception as e:
                logger.error(f"Search error: {e}")
                await client.send_message(chat_id, 'Failed to process your request.')
                
    except Exception as e:
        logger.error(f"Webhook message handler error: {e}")

async def handle_webhook_callback(data: dict, client):
    """Handle webhook callback queries"""
    try:
        query_id = data.get('id')
        message = data.get('message', {})
        chat_id = message.get('chat', {}).get('id')
        message_id = message.get('message_id')
        
        callback_data = data.get('data', '')
        if isinstance(callback_data, bytes):
            callback_data = callback_data.decode('utf-8')
            
        if not all([query_id, chat_id, message_id, callback_data]):
            return
            
        if callback_data.startswith("page|"):
            parts = callback_data.split("|")
            if len(parts) != 3:
                return
                
            text = parts[1]
            try:
                page = int(parts[2])
            except ValueError:
                return
                
            page_size = 10
            offset = (page - 1) * page_size
            
            keyword_list = split_keywords(text)
            total_results = await count_search_results(keyword_list)
            
            if total_results > 0:
                total_pages = math.ceil(total_results / page_size)
                db_results = await search_files(keyword_list, page_size, offset)
                video_results = [r for r in db_results if any(r[2].lower().endswith(ext) for ext in VIDEO_EXTENSIONS)]
                
                if video_results:
                    buttons = []
                    header = f"🎬 {total_results} Results for '{text}'"
                    
                    # Result buttons
                    for result in video_results:
                        id, caption, file_name, rank = result
                        token = await store_token(str(id))
                        if token:
                            display_name = format_button_text(file_name or caption or "Unknown File")
                            safe_video_name = urllib.parse.quote(file_name or '', safe='')
                            safe_token = urllib.parse.quote(token, safe='')
                            website_link = f"https://bigdaddyaman.github.io?token={safe_token}&videoName={safe_video_name}"
                            buttons.append([Button.url(display_name, website_link)])
                    
                    # Pagination
                    if total_pages > 1:
                        nav = []
                        nav.append(Button.inline("1️⃣", f"page|{text}|1"))
                        if page > 1:
                            nav.append(Button.inline("⬅️", f"page|{text}|{page-1}"))
                        nav.append(Button.inline(f"{page}/{total_pages}", f"current|{page}"))
                        if page < total_pages:
                            nav.append(Button.inline("➡️", f"page|{text}|{page+1}"))
                        nav.append(Button.inline(f"{total_pages}️⃣", f"page|{text}|{total_pages}"))
                        buttons.append(nav)
                        
                    await client.edit_message(chat_id, message_id, header, buttons=buttons)
                    await client.answer_callback_query(query_id)
                    return
                    
            await client.answer_callback_query(query_id, "No more results", show_alert=True)
            
        elif callback_data.startswith("current|"):
            page = callback_data.split("|")[1]
            await client.answer_callback_query(query_id, f"Current page {page}", show_alert=True)
            
    except Exception as e:
        logger.error(f"Webhook callback handler error: {e}")
        if query_id:
            await client.answer_callback_query(query_id, "Error processing request", show_alert=True)

# Bot setup functions
async def setup_webhook():
    """Set up webhook for the bot"""
    try:
        async with aiohttp.ClientSession() as session:
            # Delete existing webhook
            async with session.get(f'https://api.telegram.org/bot{bot_token}/deleteWebhook') as resp:
                await resp.json()

            # Set new webhook
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

async def setup_bot_handlers(client):
    """Set up all bot event handlers"""
    logger.info("Setting up bot handlers...")
    
    # Register handlers with proper references
    client.add_event_handler(
        lambda e: handle_start(e, client),
        events.NewMessage(pattern='/start')
    )
    
    client.add_event_handler(
        lambda e: handle_messages(e, client),
        events.NewMessage
    )
    
    client.add_event_handler(
        lambda e: handle_callback_query(e, client),
        events.CallbackQuery
    )
    
    logger.info("Bot handlers set up successfully")

# FastAPI endpoint
@app.post(WEBHOOK_PATH)
async def handle_webhook(request: Request):
    """Handle incoming webhook updates"""
    try:
        data = await request.json()
        client = await get_client()
        
        if 'message' in data:
            await handle_webhook_message(data['message'], client)
        elif 'callback_query' in data:
            await handle_webhook_callback(data['callback_query'], client)
            
        return {"ok": True}
    except Exception as e:
        logger.error(f"Error handling webhook: {e}")
        return {"ok": False, "error": str(e)}

# Export needed functions and variables
__all__ = [
    'initialize_client',
    'setup_bot_handlers',
    'setup_webhook',
    'get_client',
    'WEBHOOK_PATH',
    'handle_messages',
    'handle_callback_query',
    'PORT'
]

