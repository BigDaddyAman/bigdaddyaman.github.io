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
        id_str = str(id)
        access_hash_str = str(access_hash)
        
        # Normalize the filename before storing
        normalized_filename = normalize_filename(file_name)
        
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
        ''', id_str, access_hash_str, file_reference, mime_type, caption, keywords, normalized_filename)
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
        # Create phrase from original keywords
        original_phrase = ' '.join(keyword_list).lower()
        
        # Normalize the search phrase
        search_pattern = f"%{original_phrase}%"
        
        query = '''
            WITH ranked_results AS (
                SELECT 
                    id, 
                    caption, 
                    file_name,
                    CASE
                        -- Exact phrase match in filename
                        WHEN lower(file_name) LIKE $4 THEN 10.0
                        -- Exact phrase match in caption
                        WHEN lower(caption) LIKE $4 THEN 8.0
                        -- Partial match in filename
                        WHEN lower(file_name) LIKE ANY($5::text[]) THEN 6.0
                        -- Partial match in caption
                        WHEN lower(caption) LIKE ANY($5::text[]) THEN 4.0
                        -- Fallback to full-text search ranking
                        ELSE ts_rank_cd(to_tsvector('simple', coalesce(file_name, '') || ' ' || coalesce(caption, '')), 
                                      to_tsquery('simple', $1))
                    END as rank
                FROM files 
                WHERE 
                    lower(file_name) LIKE $4 
                    OR lower(caption) LIKE $4
                    OR lower(file_name) LIKE ANY($5::text[])
                    OR lower(caption) LIKE ANY($5::text[])
                    OR to_tsvector('simple', coalesce(file_name, '') || ' ' || coalesce(caption, '')) @@ to_tsquery('simple', $1)
            )
            SELECT id, caption, file_name, rank
            FROM ranked_results
            WHERE rank > 0.1
            ORDER BY rank DESC, file_name ASC
            LIMIT $2 OFFSET $3
        '''
        
        # Create patterns for partial matches
        partial_patterns = [f"%{kw.lower()}%" for kw in keyword_list]
        
        # Convert keyword list to tsquery format
        tsquery = ' & '.join(keyword_list)
        
        return await conn.fetch(
            query, 
            tsquery,  # $1
            page_size,  # $2 
            offset,  # $3
            search_pattern,  # $4
            partial_patterns,  # $5
        )
    except asyncpg.PostgresError as e:
        logger.error(f"Database error in search: {e}")
        return []
    finally:
        await conn.close()

# Modify count_search_results to use the GIN index
async def count_search_results(keyword_list: List[str]) -> int:
    conn = await connect_to_db()
    if not conn:
        return 0
    try:
        original_phrase = ' '.join(keyword_list).lower()
        search_pattern = f"%{original_phrase}%"
        partial_patterns = [f"%{kw.lower()}%" for kw in keyword_list]
        
        query = '''
            SELECT COUNT(*) 
            FROM files 
            WHERE 
                lower(file_name) LIKE $1 
                OR lower(caption) LIKE $1
                OR lower(file_name) LIKE ANY($2::text[])
                OR lower(caption) LIKE ANY($2::text[])
        '''
        return await conn.fetchval(query, search_pattern, partial_patterns)
    except asyncpg.PostgresError as e:
        logger.error(f"Database error in count: {e}")
        return 0
    finally:
        await conn.close()

# Add a new function to handle filename storage formatting
def normalize_filename(filename: str) -> str:
    """Normalize filename for consistent storage and searching"""
    if not filename:
        return filename
        
    # Remove common video suffixes
    clean = re.sub(r'\.(?:mp4|mkv|avi|mov|wmv|flv|webm)$', '', filename, flags=re.IGNORECASE)
    
    # Remove timestamp patterns
    clean = re.sub(r'video_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}_\d+', '', clean)
    
    # Clean up spaces and special characters
    clean = re.sub(r'[\s_]+', ' ', clean)
    clean = clean.strip()
    
    return clean
