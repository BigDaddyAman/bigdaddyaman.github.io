import logging
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

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,  # Change to DEBUG to show more logs
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

# Your API ID, hash, and bot token
api_id = int(os.getenv('API_ID'))
api_hash = os.getenv('API_HASH')
bot_token = os.getenv('BOT_TOKEN')

client = TelegramClient('bot', api_id, api_hash).start(bot_token=bot_token)

VIDEO_EXTENSIONS = ['.mp4', '.mkv', '.webm', '.ts', '.mov', '.avi', '.flv', '.wmv', '.m4v', '.mpeg', '.mpg', '.3gp', '.3g2']

# List of authorized user IDs
AUTHORIZED_USER_IDS = [7951420571, 1509468839]  # Replace with your user ID and future moderator IDs

# Add this constant near the top with other constants
REQUIRED_CHANNEL = "@kakifilem"  # or "https://t.me/kakifilem"

def normalize_keyword(keyword):
    # Replace special characters with spaces, convert to lowercase, and trim whitespace
    keyword = re.sub(r'[\.\_\@\(\)\-]', ' ', keyword).lower()
    keyword = re.sub(r'\s+', ' ', keyword)  # Replace multiple spaces with a single space
    return keyword.strip()

def split_keywords(keyword):
    # Split the normalized keyword into individual words
    return keyword.split()

# Add this helper function before the main() function
async def is_user_in_channel(client, user_id):
    try:
        channel = await client.get_entity(REQUIRED_CHANNEL)
        # Only check if user can view messages instead of getting participants
        await client.get_permissions(channel, user_id)
        return True
    except Exception as e:
        logger.info(f"Channel membership check failed for user {user_id}")
        return False

# Add error handler for the client
@client.on(events.NewMessage)
async def error_handler(event):
    try:
        raise events.StopPropagation
    except Exception as e:
        logger.error(f"Uncaught error: {str(e)}", exc_info=True)

async def main():
    try:
        # Initialize database
        await init_db()
        await init_user_db()  # This creates the users table
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
                    [Button.url("Join Channel", f"https://t.me/kakifilem")]
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
                                    caption=formatted_caption
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

        # Modify the handle_messages function
        @client.on(events.NewMessage)
        async def handle_messages(event):
            if event.is_private:
                # Check channel membership first
                if not await is_user_in_channel(client, event.sender_id):
                    keyboard = [
                        [Button.url("Join Channel", f"https://t.me/kakifilem")]
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
                                file_name = attr.file_name
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
                            logger.debug(f"Ignoring command: {event.message.text}")
                            return

                        text = normalize_keyword(event.message.text.lower().strip())
                        keyword_list = split_keywords(text)
                        logger.debug(f"Received text message: {text}")

                        page = 1  # Default to first page
                        page_size = 10  # Number of results per page
                        offset = (page - 1) * page_size

                        db_results = await search_files(keyword_list, page_size, offset)
                        logger.debug(f"Database search results for keywords '{keyword_list}': {db_results}")

                        total_results = await count_search_results(keyword_list)
                        total_pages = math.ceil(total_results / page_size)

                        video_results = [result for result in db_results if any(result[2].lower().endswith(ext) for ext in VIDEO_EXTENSIONS)]
                        logger.debug(f"Filtered video results: {video_results}")

                        if video_results:
                            header = f"{total_results} Results for '{text}'"
                            buttons = []
                            for result in video_results:
                                id, caption, file_name, rank = result  # Unpack all 4 values
                                token = await store_token(str(id))
                                if token:
                                    import urllib.parse
                                    safe_video_name = urllib.parse.quote(file_name, safe='')
                                    safe_token = urllib.parse.quote(token, safe='')
                                    if await is_premium(event.sender_id):
                                        buttons.append([Button.inline(file_name or caption or "Unknown File", f"{id}|{page}")])
                                    else:
                                        website_link = f"https://bigdaddyaman.github.io?token={safe_token}&videoName={safe_video_name}"
                                        buttons.append([Button.url(file_name or caption or "Unknown File", website_link)])
                            
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
                            buttons.append([Button.inline("First Page", f"page|{text}|1"), Button.inline("Last Page", f"page|{total_pages}")])

                            await event.respond(header, buttons=buttons)
                        else:
                            logger.debug(f"No matching video files found for keyword '{text}'.")
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
                        await event.answer("Invalid page data")
                        return

                    _, keyword, page = parts
                    page = int(page)
                    page_size = 10
                    offset = (page - 1) * page_size

                    keyword_list = split_keywords(keyword)

                    db_results = await search_files(keyword_list, page_size, offset)
                    logger.debug(f"Database search results for keywords '{keyword_list}': {db_results}")

                    total_results = await count_search_results(keyword_list)
                    total_pages = math.ceil(total_results / page_size)

                    video_results = [result for result in db_results if any(result[2].lower().endswith(ext) for ext in VIDEO_EXTENSIONS)]
                    logger.debug(f"Filtered video results: {video_results}")

                    if video_results:
                        header = f"{total_results} Results for '{keyword}'"
                        buttons = []
                        for result in video_results:
                            id, caption, file_name, rank = result  # Unpack all 4 values
                            buttons.append([Button.inline(file_name or caption or "Unknown File", f"{id}|{page}")])
                        logger.debug(f"Generated buttons: {buttons}")

                        # Pagination Buttons
                        pagination_buttons = []
                        start_page = max(1, page - 2)
                        end_page = min(total_pages, start_page + 4)

                        for p in range(start_page, end_page + 1):
                            if p == page:
                                pagination_buttons.append(Button.inline(f"[{p}]", f"ignore|{keyword}|{p}"))
                            else:
                                pagination_buttons.append(Button.inline(str(p), f"page|{keyword}|{p}"))

                        if page > 1:
                            pagination_buttons.insert(0, Button.inline("Prev", f"page|{keyword}|{page - 1}"))
                        if page < total_pages:
                            pagination_buttons.append(Button.inline("Next", f"page|{keyword}|{page + 1}"))

                        buttons.append(pagination_buttons)
                        buttons.append([Button.inline("First Page", f"page|{keyword}|1"), Button.inline("Last Page", f"page|{total_pages}")])

                        await event.edit(header, buttons=buttons)
                    else:
                        await event.edit("No more results.")
                elif data.startswith("ignore|"):
                    pass  # Do nothing if the user clicks on the current page
                else:
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
                                caption=file_info['file_name'].replace(" ", ".").replace("@", "")
                            )
                            await progress_msg.delete()
                        except Exception as e:
                            logger.error(f"Error sending file to premium user: {e}")
                            await progress_msg.edit('⚠️ Failed to send file. Please try again or contact support.')
                    else:
                        # Free users get website link without additional prompt
                        token = await store_token(str(id))
                        if token:
                            video_name = file_info['file_name']
                            import urllib.parse
                            safe_video_name = urllib.parse.quote(video_name, safe='')
                            safe_token = urllib.parse.quote(token, safe='')
                            website_link = f"https://bigdaddyaman.github.io?token={safe_token}&videoName={safe_video_name}"
                            await event.answer(url=website_link)  # This will open the link directly
                        else:
                            await event.respond("Failed to generate download link.")

            except Exception as e:
                logger.error(f"Error in callback query handler: {e}")
                await event.respond('Failed to process your request.')

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

        await client.run_until_disconnected()
    except Exception as e:
        logger.error(f"Critical error in main: {str(e)}", exc_info=True)
        raise

if __name__ == "__main__":
    try:
        with client:
            client.loop.run_until_complete(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {str(e)}", exc_info=True)

