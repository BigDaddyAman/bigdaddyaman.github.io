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
from functools import lru_cache
from typing import Dict, Set
import time
from telethon.tl.functions.messages import SetBotCallbackAnswerRequest

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
BACKUP_CHANNEL_ID = -1002647276011  # Your backup channel ID
RESULTS_PER_PAGE = 10

# Cache for preventing duplicate messages
_message_cache: Dict[int, Set[str]] = {}
_cache_cleanup_time = 0

def is_duplicate_message(chat_id: int, text: str) -> bool:
    """Check if a message is a duplicate within 5 seconds"""
    global _message_cache, _cache_cleanup_time
    current_time = time.time()
    
    # Cleanup old cache entries every 30 seconds
    if current_time - _cache_cleanup_time > 30:
        _message_cache.clear()
        _cache_cleanup_time = current_time
    
    cache_key = f"{chat_id}:{text}"
    if chat_id not in _message_cache:
        _message_cache[chat_id] = {cache_key}
        return False
        
    if cache_key in _message_cache[chat_id]:
        return True
        
    _message_cache[chat_id].add(cache_key)
    return False

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
            
            # Process page change
            await process_page_change(event, text, page)
            
            # Answer callback query using Telethon's method
            try:
                await event(SetBotCallbackAnswerRequest(
                    query_id=int(event.query.id),
                    message="",
                    alert=False
                ))
            except Exception as e:
                logger.error(f"Error answering callback: {e}")
                
        elif data.startswith("current|"):
            # Answer current page callback
            try:
                await event(SetBotCallbackAnswerRequest(
                    query_id=int(event.query.id),
                    message=f"Current page {data.split('|')[1]}",
                    alert=True
                ))
            except Exception as e:
                logger.error(f"Error answering current page callback: {e}")
                
    except Exception as e:
        logger.error(f"Error in callback handler: {e}")

async def send_search_results(event, text, video_results, page, total_pages, total_results, is_edit=False):
    """Helper function to send or edit search results with improved pagination"""
    try:
        # Prevent duplicate messages with more robust cache key
        cache_key = f"{event.chat_id}:{text}:{page}:{total_results}"
        if not is_edit and cache_key in _message_cache:
            return
        _message_cache[cache_key] = time.time()

        header = f"🎬 {total_results} Results for '{text}'"
        buttons = []

        # Create result buttons
        for result in video_results:
            id, caption, file_name, rank = result
            display_name = format_button_text(file_name or caption or "Unknown File")
            token = await store_token(str(id))
            if token:
                safe_video_name = urllib.parse.quote(file_name, safe='')
                safe_token = urllib.parse.quote(token, safe='')
                website_link = f"https://bigdaddyaman.github.io?token={safe_token}&videoName={safe_video_name}"
                buttons.append([Button.url(display_name, website_link)])

        # Add improved pagination with numbers and First/Last buttons
        if total_pages > 1:
            nav = []
            
            # First page button
            if page > 1:
                nav.append(Button.inline("« First", f"page|{text}|1"))

            # Previous page button
            if page > 1:
                nav.append(Button.inline("‹", f"page|{text}|{page-1}"))

            # Calculate page range for numbered buttons
            visible_pages = 5
            start_page = max(1, min(page - (visible_pages // 2), total_pages - visible_pages + 1))
            end_page = min(start_page + visible_pages - 1, total_pages)

            # Add numbered page buttons
            for p in range(start_page, end_page + 1):
                if p == page:
                    nav.append(Button.inline(f"[{p}]", f"current|{p}"))
                else:
                    nav.append(Button.inline(str(p), f"page|{text}|{p}"))

            # Next page button
            if page < total_pages:
                nav.append(Button.inline("›", f"page|{text}|{page+1}"))

            # Last page button
            if page < total_pages:
                nav.append(Button.inline("Last »", f"page|{text}|{total_pages}"))

            buttons.append(nav)

        # Send or edit message with retries
        max_retries = 3
        for attempt in range(max_retries):
            try:
                if is_edit:
                    await event.edit(header, buttons=buttons)
                else:
                    await event.respond(header, buttons=buttons)
                break
            except errors.MessageNotModifiedError:
                break
            except Exception as e:
                if attempt == max_retries - 1:
                    logger.error(f"Failed to send/edit message after {max_retries} attempts: {e}")
                else:
                    await asyncio.sleep(1)

    except Exception as e:
        logger.error(f"Error in send_search_results: {e}")

async def process_page_change(event, text, page):
    """Process page change requests"""
    try:
        page_size = 10
        offset = (page - 1) * page_size
        
        keyword_list = split_keywords(text)
        db_results = await search_files(keyword_list, page_size, offset)
        total_results = await count_search_results(keyword_list)
        total_pages = math.ceil(total_results / page_size)
        video_results = [result for result in db_results if any(result[2].lower().endswith(ext) for ext in VIDEO_EXTENSIONS)]
        
        if video_results:
            await send_search_results(event, text, video_results, page, total_pages, total_results, is_edit=True)
            
    except Exception as e:
        logger.error(f"Error processing page change: {e}")

async def handle_webhook_message(data: dict, client):
    """Handle webhook message updates"""
    try:
        chat = data.get('chat', {})
        chat_id = chat.get('id')
        chat_type = chat.get('type')
        
        if not chat_id or chat_type != 'private':
            return
            
        text = data.get('text', '')
        if not text or text.startswith('/'):
            return

        # Check for duplicate message
        if is_duplicate_message(chat_id, text):
            logger.info(f"Skipping duplicate webhook message: {text}")
            return

        # Process message normally
        if not await is_user_in_channel(client, chat_id):
            keyboard = [[Button.url("Join Channel", CHANNEL_INVITE_LINK)]]
            await client.send_message(
                chat_id,
                "⚠️ You must join our channel first to use this bot!\n\n"
                "1. Click the button below to join\n"
                "2. After joining, come back and try again",
                buttons=keyboard
            )
            return

        await update_user_activity(chat_id)
        
        # Handle text messages
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
        callback_data = data.get('data')
        if isinstance(callback_data, bytes):
            callback_data = callback_data.decode('utf-8')
            
        message = data.get('message', {})
        chat_id = message.get('chat', {}).get('id')
        message_id = message.get('message_id')
        
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
                
                # Use edit_message for pagination updates
                if video_results:
                    buttons = []
                    header = f"🎬 {total_results} Results for '{text}'"
                    
                    # Add result buttons
                    for result in video_results:
                        id, caption, file_name, rank = result
                        token = await store_token(str(id))
                        if token:
                            display_name = format_button_text(file_name or caption or "Unknown File")
                            safe_video_name = urllib.parse.quote(file_name or '', safe='')
                            safe_token = urllib.parse.quote(token, safe='')
                            website_link = f"https://bigdaddyaman.github.io?token={safe_token}&videoName={safe_video_name}"
                            buttons.append([Button.url(display_name, website_link)])
                    
                    # Add pagination buttons using the same format as send_search_results
                    if total_pages > 1:
                        nav = []
                        if page > 1:
                            nav.append(Button.inline("« First", f"page|{text}|1"))
                            nav.append(Button.inline("‹", f"page|{text}|{page-1}"))
                            
                        visible_pages = 5
                        start_page = max(1, min(page - (visible_pages // 2), total_pages - visible_pages + 1))
                        end_page = min(start_page + visible_pages - 1, total_pages)
                        
                        for p in range(start_page, end_page + 1):
                            if p == page:
                                nav.append(Button.inline(f"[{p}]", f"current|{p}"))
                            else:
                                nav.append(Button.inline(str(p), f"page|{text}|{p}"))
                                
                        if page < total_pages:
                            nav.append(Button.inline("›", f"page|{text}|{page+1}"))
                            nav.append(Button.inline("Last »", f"page|{text}|{total_pages}"))
                            
                        buttons.append(nav)
                    
                    # Use raw API method to edit message
                    try:
                        await client.edit_message(chat_id, message_id, header, buttons=buttons)
                    except Exception as e:
                        logger.error(f"Error editing message: {e}")
                        
    except Exception as e:
        logger.error(f"Webhook callback handler error: {e}")

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
    
    # Add broadcast command handler
    client.add_event_handler(
        lambda e: broadcast_command(e, client),
        events.NewMessage(pattern='/broadcast')
    )
    
    # Add renew command handler
    client.add_event_handler(
        lambda e: renew_command(e, client),
        events.NewMessage(pattern='/renew')
    )
    
    logger.info("Bot handlers set up successfully")

# Update the broadcast command
async def broadcast_command(event, client):
    """Handle broadcast command"""
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
        # ... rest of your existing broadcast code ...
        pass
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

# Update the renew command
async def renew_command(event, client):
    """Handle renew command"""
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

async def setup_backup_channel(client):
    """Set up backup channel monitoring"""
    try:
        channel = await client.get_entity(BACKUP_CHANNEL_ID)
        logger.info(f"Successfully connected to backup channel: {channel.title}")
        
        @client.on(events.NewMessage(chats=BACKUP_CHANNEL_ID))
        async def backup_channel_handler(event):
            try:
                if event.message.document:
                    # Process document
                    await handle_backup_document(event.message)
            except Exception as e:
                logger.error(f"Error in backup channel handler: {e}")
                
        logger.info("Backup channel handler set up successfully")
        return True
    except Exception as e:
        logger.error(f"Failed to set up backup channel: {e}")
        return False

# FastAPI endpoint
@app.post(WEBHOOK_PATH)
async def handle_webhook(request: Request):
    """Handle incoming webhook updates"""
    try:
        data = await request.json()
        client = await get_client()
        
        if 'message' in data:
            # Replace the direct message handler call with specific webhook message handler
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

# Update message cache cleanup
def cleanup_message_cache():
    """Clean up old message cache entries"""
    current_time = time.time()
    expired_keys = [k for k, v in _message_cache.items() if current_time - v > 30]
    for k in expired_keys:
        _message_cache.pop(k, None)

