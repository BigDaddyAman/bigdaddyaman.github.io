import logging
import psycopg2
import asyncio
import re
import math
from telethon import TelegramClient, events, Button
from telethon.tl.types import Document, DocumentAttributeFilename
import uuid
import base64
import time
import threading
from Report import start_flask_app  # Import the Flask app starter function

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levellevel)s - %(message)s')
logger = logging.getLogger(__name__)

# Your API ID, hash, and bot token obtained from https://my.telegram.org and BotFather
api_id = 24492108  # Your new API ID
api_hash = '82342323c63f78f9b0bc7a3ecd7c2509'  # Your new API hash
bot_token = '7303681517:AAFQg_QXYScFJNeub-Cp8qmB7IIUNn_9E5M'  # Your new bot token

client = TelegramClient('bot', api_id, api_hash).start(bot_token=bot_token)

# Connect to PostgreSQL database with retry mechanism
def connect_to_db():
    retries = 5
    while retries > 0:
        try:
            conn = psycopg2.connect(
                dbname='Kakifilem',
                user='postgres',
                password='Amanfiy77',
                host='localhost',
                port='5432'
            )
            return conn
        except psycopg2.OperationalError as e:
            logger.error(f"Database connection failed: {e}")
            retries -= 1
            time.sleep(5)
    raise Exception("Failed to connect to the database after multiple retries")

conn = connect_to_db()
c = conn.cursor()

# Ensure the table to store file metadata exists
c.execute('''CREATE TABLE IF NOT EXISTS files
             (id TEXT PRIMARY KEY, access_hash TEXT, file_reference BYTEA, mime_type TEXT, caption TEXT, keywords TEXT, file_name TEXT)''')
conn.commit()

# Connect to verification database with retry mechanism
conn_verification = connect_to_db()
c_verification = conn_verification.cursor()

# Ensure the table to store tokens exists
c_verification.execute('''CREATE TABLE IF NOT EXISTS tokens
             (token TEXT PRIMARY KEY, file_id TEXT)''')
conn_verification.commit()

VIDEO_EXTENSIONS = ['.mp4', '.mkv', '.webm', '.ts', '.mov', '.avi', '.flv', '.wmv', '.m4v', '.mpeg', '.mpg', '.3gp', '.3g2']

def store_video_metadata(id, access_hash, file_reference, mime_type, caption, keywords, file_name):
    cursor = conn.cursor()
    cursor.execute('''INSERT INTO files (id, access_hash, file_reference, mime_type, caption, keywords, file_name)
                      VALUES (%s, %s, %s, %s, %s, %s, %s)''',
                   (id, access_hash, file_reference, mime_type, caption, keywords, file_name))
    conn.commit()

def generate_and_store_token(file_id):
    token = str(uuid.uuid4())  # Generate a unique token
    encoded_token = base64.urlsafe_b64encode(token.encode()).decode()
    cursor_verification = conn_verification.cursor()
    cursor_verification.execute('INSERT INTO tokens (token, file_id) VALUES (%s, %s)', (encoded_token, file_id))
    conn_verification.commit()
    return encoded_token

# List of authorized user IDs
AUTHORIZED_USER_IDS = [7951420571, 1509468839]  # Replace with your user ID and future moderator IDs

def normalize_keyword(keyword):
    # Replace special characters with spaces, convert to lowercase, and trim whitespace
    keyword = re.sub(r'[\.\_\@\(\)\-]', ' ', keyword).lower()
    keyword = re.sub(r'\s+', ' ', keyword)  # Replace multiple spaces with a single space
    return keyword.strip()

def split_keywords(keyword):
    # Split the normalized keyword into individual words
    return keyword.split()

async def main():
    await client.start()
    logger.info("Client created")

    @client.on(events.NewMessage(pattern='/start'))
    async def start(event):
        command_args = event.message.text.split()
        if len(command_args) > 1:
            token = command_args[1]
            try:
                decoded_token = base64.urlsafe_b64decode(token.encode()).decode()
                logger.debug(f"Decoded token: {decoded_token}")

                cursor_verification = conn_verification.cursor()
                cursor_verification.execute('SELECT file_id FROM tokens WHERE token=%s', (token,))
                result = cursor_verification.fetchone()
                logger.debug(f"Token verification result: {result}")

                if result:
                    file_id = result[0]

                    cursor_files = conn.cursor()
                    cursor_files.execute('SELECT id, access_hash, file_reference, mime_type, caption, file_name FROM files WHERE id=%s', (file_id,))
                    file_info = cursor_files.fetchone()

                    logger.debug(f"File fetch result: {file_info}")

                    if file_info:
                        id, access_hash, file_reference, mime_type, caption, file_name = file_info

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

    @client.on(events.NewMessage)
    async def handle_messages(event):
        if event.is_private:
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

                    id = document.id
                    access_hash = document.access_hash
                    file_reference = document.file_reference
                    mime_type = document.mime_type

                    logger.debug(f"Inserting file metadata: id={id}, access_hash={access_hash}, file_reference={file_reference}, mime_type={mime_type}, caption={caption}, keywords={keywords}, file_name={file_name}")
                    c.execute('''INSERT INTO files (id, access_hash, file_reference, mime_type, caption, keywords, file_name)
                                 VALUES (%s, %s, %s, %s, %s, %s, %s)
                                 ON CONFLICT (id) DO UPDATE SET
                                 access_hash = EXCLUDED.access_hash,
                                 file_reference = EXCLUDED.file_reference,
                                 mime_type = EXCLUDED.mime_type,
                                 caption = EXCLUDED.caption,
                                 keywords = EXCLUDED.keywords,
                                 file_name = EXCLUDED.file_name''',
                              (id, access_hash, file_reference, mime_type, caption, keywords, file_name))
                    conn.commit()
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

                    search_query = "SELECT id, caption, file_name FROM files WHERE "
                    search_query += " AND ".join(["keywords LIKE %s"] * len(keyword_list))
                    search_query += " LIMIT %s OFFSET %s"

                    search_params = [f'%{kw}%' for kw in keyword_list] + [page_size, offset]

                    c.execute(search_query, search_params)
                    db_results = c.fetchall()
                    logger.debug(f"Database search results for keywords '{keyword_list}': {db_results}")

                    c.execute("SELECT COUNT(*) FROM files WHERE " + " AND ".join(["keywords LIKE %s"] * len(keyword_list)), [f'%{kw}%' for kw in keyword_list])
                    total_results = c.fetchone()[0]
                    total_pages = math.ceil(total_results / page_size)

                    video_results = [result for result in db_results if any(result[2].lower().endswith(ext) for ext in VIDEO_EXTENSIONS)]
                    logger.debug(f"Filtered video results: {video_results}")

                    if video_results:
                        header = f"{total_results} Results for '{text}'"
                        buttons = [
                            [Button.inline(file_name or caption or "Unknown File", f"{id}|{page}")]
                            for id, caption, file_name in video_results
                        ]
                        logger.debug(f"Generated buttons: {buttons}")

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
            logger.debug(f"Callback query data: {data}")

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

                search_query = "SELECT id, caption, file_name FROM files WHERE "
                search_query += " AND ".join(["keywords LIKE %s"] * len(keyword_list))
                search_query += " LIMIT %s OFFSET %s"

                search_params = [f'%{kw}%' for kw in keyword_list] + [page_size, offset]

                c.execute(search_query, search_params)
                db_results = c.fetchall()
                logger.debug(f"Database search results for keywords '{keyword_list}': {db_results}")

                c.execute("SELECT COUNT(*) FROM files WHERE " + " AND ".join(["keywords LIKE %s"] * len(keyword_list)), [f'%{kw}%' for kw in keyword_list])
                total_results = c.fetchone()[0]
                total_pages = math.ceil(total_results / page_size)

                video_results = [result for result in db_results if any(result[2].lower().endswith(ext) for ext in VIDEO_EXTENSIONS)]
                logger.debug(f"Filtered video results: {video_results}")

                if video_results:
                    header = f"{total_results} Results for '{keyword}'"
                    buttons = [
                        [Button.inline(file_name or caption or "Unknown File", f"{id}|{page}")]
                        for id, caption, file_name in video_results
                    ]
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
                token = generate_and_store_token(id)
                if token:
                    cursor = conn.cursor()
                    cursor.execute('SELECT file_name FROM files WHERE id=%s', (id,))
                    result = cursor.fetchone()

                    if result:
                        import urllib.parse
                        video_name = result[0]
                        safe_video_name = urllib.parse.quote(video_name, safe='')
                        safe_token = urllib.parse.quote(token, safe='')
                        website_link = f"https://bigdaddyaman.github.io?token={safe_token}&videoName={safe_video_name}"
                        button = [Button.url("Klik di sini untuk muat turun", website_link)]
                        await event.respond("Klik di bawah untuk memuat turun fail anda:", buttons=button)
                    else:
                        logger.error("Failed to fetch video name.")
                        await event.respond("Failed to fetch video name.")
                else:
                    logger.error("Failed to generate download link.")
                    await event.respond("Failed to generate download link.")
        except Exception as e:
            logger.error(f"Error handling callback query: {e}")
            await event.respond('Failed to process your request.')

    @client.on(events.NewMessage(pattern='/listdb'))
    async def list_db(event):
        logger.debug("Executing /listdb command")
        c.execute("SELECT * FROM files")
        results = c.fetchall()
        logger.debug(f"Database entries: {results}")
        await event.reply(f"Database entries: {results}")

    # Start the Flask app in a separate thread
    threading.Thread(target=start_flask_app).start()

    await client.run_until_disconnected()

with client:
    client.loop.run_until_complete(main())
