import logging
import asyncpg
import time
import os
from dotenv import load_dotenv
import uuid
import base64
from typing import List, Tuple, Optional

# Load environment variables from .env file
load_dotenv()

logger = logging.getLogger(__name__)

async def connect_to_db():
    retries = 5
    while retries > 0:
        try:
            conn = await asyncpg.connect(
                database=os.getenv('PGDATABASE'),
                user=os.getenv('PGUSER'),
                password=os.getenv('PGPASSWORD'),
                host=os.getenv('PGHOST'),
                port=os.getenv('PGPORT')
            )
            return conn
        except Exception as e:
            logger.error(f"Database connection failed: {e}")
            retries -= 1
            time.sleep(1)
            if retries == 0:
                logger.critical("Failed to connect to the database after multiple retries")
                return None
    return None

async def init_db():
    conn = await connect_to_db()
    try:
        # Create tables with proper constraints
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS files (
                id TEXT PRIMARY KEY,
                access_hash TEXT,
                file_reference BYTEA,
                mime_type TEXT,
                caption TEXT,
                keywords TEXT,
                file_name TEXT
            )
        ''')
        
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS tokens (
                token TEXT PRIMARY KEY,
                file_id TEXT REFERENCES files(id),
                UNIQUE(file_id)
            )
        ''')

        # Create indexes
        await conn.execute('''
            CREATE INDEX IF NOT EXISTS idx_files_keywords 
            ON files USING gin(to_tsvector('english', keywords))
        ''')
        
        await conn.execute('''
            CREATE INDEX IF NOT EXISTS idx_tokens_file_id 
            ON tokens(file_id)
        ''')
    except Exception as e:
        logger.error(f"Error initializing database: {e}")
        raise
    finally:
        await conn.close()

async def store_file_metadata(id: str, access_hash: str, file_reference: bytes,
                            mime_type: str, caption: str, keywords: str, file_name: str):
    conn = await connect_to_db()
    if not conn:
        return None
    try:
        # Convert id and access_hash to strings if they're integers
        id_str = str(id)
        access_hash_str = str(access_hash)
        
        # Ensure caption and keywords are strings, not None
        safe_caption = str(caption) if caption is not None else ""
        safe_keywords = str(keywords) if keywords is not None else ""
        safe_file_name = str(file_name) if file_name is not None else ""
        
        # Clean the caption to remove unwanted patterns
        cleaned_caption = re.sub(r'\((.*?GB)\)', '', safe_caption).strip()  # Remove size in parentheses
        cleaned_caption = re.sub(r'IMDB\.Rating\.[0-9.]+', '', cleaned_caption)  # Remove IMDB rating
        cleaned_caption = re.sub(r'Genre\.[a-zA-Z.]+', '', cleaned_caption)  # Remove Genre
        cleaned_caption = re.sub(r'\.+', '.', cleaned_caption)  # Replace multiple dots with single dot
        cleaned_caption = cleaned_caption.strip('.')  # Remove leading/trailing dots
        
        await conn.execute('''
            INSERT INTO files 
            (id, access_hash, file_reference, mime_type, caption, keywords, file_name)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT (id) DO UPDATE SET
                access_hash = EXCLUDED.access_hash,
                file_reference = EXCLUDED.file_reference,
                mime_type = EXCLUDED.mime_type,
                caption = EXCLUDED.caption,
                keywords = EXCLUDED.keywords,
                file_name = EXCLUDED.file_name
        ''', id_str, access_hash_str, file_reference, mime_type, cleaned_caption, safe_keywords, safe_file_name)
        
    except Exception as e:
        logger.error(f"Error storing file metadata: {e}")
        return None
    finally:
        await conn.close()

class AsyncPostgresConnection:
    def __init__(self):
        self.conn = None

    async def __aenter__(self):
        self.conn = await connect_to_db()
        return self.conn

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.conn:
            await self.conn.close()

async def get_connection():
    return AsyncPostgresConnection()

# Update store_token function
async def store_token(file_id: str) -> Optional[str]:
    async with await get_connection() as conn:
        if not conn:
            return None
            
        try:
            # First try to get existing token
            result = await conn.fetchrow('SELECT token FROM tokens WHERE file_id = $1', file_id)
            if result:
                return result['token']

            # If no existing token, create new one
            token = str(uuid.uuid4())
            encoded_token = base64.urlsafe_b64encode(token.encode()).decode()
            
            result = await conn.fetchrow('''
                INSERT INTO tokens (token, file_id)
                VALUES ($1, $2)
                RETURNING token
            ''', encoded_token, file_id)
            
            return result['token'] if result else None

        except asyncpg.PostgresError as e:
            logger.error(f"Database error storing token: {e}")
            return None

# Update get_file_by_token function
async def get_file_by_token(token: str) -> Optional[str]:
    async with await get_connection() as conn:
        if not conn:
            return None
        record = await conn.fetchrow('SELECT file_id FROM tokens WHERE token = $1', token)
        return record['file_id'] if record else None

# Update other functions to use the new connection manager
async def get_file_by_id(file_id: str) -> Optional[Tuple]:
    async with await get_connection() as conn:
        if not conn:
            return None
        try:
            record = await conn.fetchrow('''
                SELECT id, access_hash, file_reference, mime_type, caption, file_name 
                FROM files WHERE id = $1
            ''', file_id)
            return record
        except asyncpg.PostgresError as e:
            logger.error(f"Database error while fetching file: {e}")
            return None

# Modify search_files to prioritize exact matches and limit results
async def search_files(keyword_list: List[str], page_size: int, offset: int):
    conn = await connect_to_db()
    if not conn:
        return []
    try:
        # Join original search phrase
        original_phrase = ' '.join(keyword_list).lower()
        
        # Create normalized search patterns
        exact_pattern = f"%{original_phrase}%"
        words_pattern = ''.join(f"(?=.*{word})" for word in keyword_list)
        
        query = """
            WITH RankedResults AS (
                SELECT 
                    id, 
                    caption, 
                    file_name,
                    CASE 
                        WHEN LOWER(file_name) = LOWER($1) THEN 100  -- Exact full match
                        WHEN LOWER(file_name) LIKE LOWER($2) THEN 90  -- Contains exact phrase
                        WHEN LOWER(file_name) ~ ALL($3::text[]) THEN 80  -- Contains all words in any order
                        WHEN LOWER(caption) = LOWER($1) THEN 70  -- Exact caption match
                        WHEN LOWER(caption) LIKE LOWER($2) THEN 60  -- Caption contains phrase
                        WHEN LOWER(caption) ~ ALL($3::text[]) THEN 50  -- Caption contains all words
                        ELSE 0
                    END as relevance_score
                FROM files 
                WHERE 
                    LOWER(file_name) ~ $4
                    OR LOWER(caption) ~ $4
            )
            SELECT 
                id, 
                caption, 
                file_name,
                relevance_score
            FROM RankedResults 
            WHERE relevance_score > 0
            ORDER BY 
                relevance_score DESC,
                file_name ASC
            LIMIT $5 OFFSET $6
        """
        
        # Create word patterns
        word_patterns = [f"(?i){word}" for word in keyword_list]
        combined_pattern = f".*{original_phrase}.*"
        
        results = await conn.fetch(
            query,
            original_phrase,                    # $1: exact phrase
            exact_pattern,                      # $2: LIKE pattern
            word_patterns,                      # $3: array of word patterns
            combined_pattern,                   # $4: regex pattern
            page_size,                         # $5: limit
            offset                             # $6: offset
        )
        
        return results
    except Exception as e:
        logger.error(f"Search error: {e}")
        return []
    finally:
        await conn.close()

# Modify count_search_results to use the GIN index
async def count_search_results(keyword_list: List[str]) -> int:
    conn = await connect_to_db()
    if not conn:
        return 0
    try:
        # Join original search phrase
        original_phrase = ' '.join(keyword_list).lower()
        combined_pattern = f".*{original_phrase}.*"
        
        query = """
            SELECT COUNT(*) 
            FROM files 
            WHERE 
                LOWER(file_name) ~ $1
                OR LOWER(caption) ~ $1
        """
        
        count = await conn.fetchval(query, combined_pattern)
        return count
    except Exception as e:
        logger.error(f"Count error: {e}")
        return 0
    finally:
        await conn.close()
