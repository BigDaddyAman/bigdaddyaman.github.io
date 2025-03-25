import logging
import asyncpg
import time
import os
from dotenv import load_dotenv
import uuid
import base64
from typing import List, Tuple, Optional
from functools import lru_cache
from redis_cache import redis_cache

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
        
        # Add additional indexes for faster searches
        await conn.execute('''
            CREATE INDEX IF NOT EXISTS idx_files_file_name_lower 
            ON files (lower(file_name));
        ''')
        
        await conn.execute('''
            CREATE INDEX IF NOT EXISTS idx_files_caption_lower 
            ON files (lower(caption));
        ''')
        
        # Add index for full text search
        await conn.execute('''
            CREATE INDEX IF NOT EXISTS idx_files_full_text 
            ON files USING gin(to_tsvector('english', coalesce(file_name, '') || ' ' || coalesce(caption, '')));
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

# Add this cache decorator to search_files
@lru_cache(maxsize=100)
def cache_key(keyword_list_str: str, page_size: int, offset: int) -> str:
    return f"{keyword_list_str}:{page_size}:{offset}"

# Update search function to be more efficient
async def search_files(keyword_list: List[str], page_size: int, offset: int):
    """Search files with improved performance and Redis caching"""
    # Create cache key
    cache_key = f"search:{','.join(sorted(keyword_list))}:{page_size}:{offset}"
    
    # Try to get from cache first
    cached_results = await redis_cache.get(cache_key)
    if cached_results:
        return cached_results
    
    conn = await connect_to_db()
    if not conn:
        return []
        
    try:
        # Simplified and fixed search query
        query = """
            SELECT 
                id, 
                caption, 
                file_name,
                ts_rank_cd(
                    setweight(to_tsvector('english', coalesce(file_name, '')), 'A') ||
                    setweight(to_tsvector('english', coalesce(caption, '')), 'B'),
                    plainto_tsquery('english', $1)
                ) as rank
            FROM files 
            WHERE 
                to_tsvector('english', coalesce(file_name, '') || ' ' || coalesce(caption, '')) @@ 
                plainto_tsquery('english', $1)
                OR LOWER(file_name) LIKE LOWER($2)
                OR LOWER(caption) LIKE LOWER($2)
            ORDER BY rank DESC, file_name ASC
            LIMIT $3 OFFSET $4
        """
        
        search_pattern = f"%{' '.join(keyword_list)}%"
        results = await conn.fetch(
            query,
            ' '.join(keyword_list),
            search_pattern,
            page_size,
            offset
        )
        
        # Convert results to list of tuples for JSON serialization
        results_list = [(r['id'], r['caption'], r['file_name'], float(r['rank'])) for r in results]
        
        # Cache the results
        await redis_cache.set(cache_key, results_list, 3600)  # Cache for 1 hour
        
        return results_list
        
    except Exception as e:
        logger.error(f"Search error: {e}")
        return []
    finally:
        await conn.close()

# Modify count_search_results to use the GIN index
async def count_search_results(keyword_list: List[str]) -> int:
    """Count search results with Redis caching"""
    cache_key = f"count:{','.join(sorted(keyword_list))}"
    
    # Try to get from cache first
    cached_count = await redis_cache.get(cache_key)
    if cached_count is not None:
        return cached_count
        
    conn = await connect_to_db()
    if not conn:
        return 0
        
    try:
        query = """
            SELECT COUNT(*) 
            FROM files 
            WHERE 
                to_tsvector('english', coalesce(file_name, '') || ' ' || coalesce(caption, '')) @@ 
                plainto_tsquery('english', $1)
                OR LOWER(file_name) LIKE LOWER($2)
                OR LOWER(caption) LIKE LOWER($2)
        """
        
        search_pattern = f"%{' '.join(keyword_list)}%"
        count = await conn.fetchval(query, ' '.join(keyword_list), search_pattern)
        
        # Cache the count
        await redis_cache.set(cache_key, count, 3600)  # Cache for 1 hour
        
        return count
    except Exception as e:
        logger.error(f"Count error: {e}")
        return 0
    finally:
        await conn.close()
