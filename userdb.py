import logging
import asyncpg
from datetime import datetime
from typing import List, Optional
from dotenv import load_dotenv
import os

load_dotenv()
logger = logging.getLogger(__name__)

async def init_user_db():
    conn = None
    try:
        conn = await asyncpg.connect(
            database=os.getenv('PGDATABASE'),
            user=os.getenv('PGUSER'),
            password=os.getenv('PGPASSWORD'),
            host=os.getenv('PGHOST'),
            port=os.getenv('PGPORT')
        )
        
        # Create users table with access_hash
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                access_hash BIGINT,
                joined_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        logger.info("User database initialized successfully")
    except Exception as e:
        logger.error(f"Error initializing user database: {e}")
        raise
    finally:
        if conn:
            await conn.close()

async def add_user(user_id: int, username: str = None, first_name: str = None, last_name: str = None, access_hash: int = None) -> bool:
    conn = None
    try:
        conn = await asyncpg.connect(
            database=os.getenv('PGDATABASE'),
            user=os.getenv('PGUSER'),
            password=os.getenv('PGPASSWORD'),
            host=os.getenv('PGHOST'),
            port=os.getenv('PGPORT')
        )
        
        await conn.execute('''
            INSERT INTO users (user_id, username, first_name, last_name, access_hash)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (user_id) 
            DO UPDATE SET 
                username = EXCLUDED.username,
                first_name = EXCLUDED.first_name,
                last_name = EXCLUDED.last_name,
                access_hash = EXCLUDED.access_hash,
                last_active = CURRENT_TIMESTAMP
        ''', user_id, username, first_name, last_name, access_hash)
        return True
    except Exception as e:
        logger.error(f"Error adding user: {e}")
        return False
    finally:
        if conn:
            await conn.close()

async def get_all_users() -> List[dict]:
    conn = None
    try:
        conn = await asyncpg.connect(
            database=os.getenv('PGDATABASE'),
            user=os.getenv('PGUSER'),
            password=os.getenv('PGPASSWORD'),
            host=os.getenv('PGHOST'),
            port=os.getenv('PGPORT')
        )
        
        users = await conn.fetch('SELECT * FROM users ORDER BY joined_date DESC')
        return [dict(user) for user in users]
    except Exception as e:
        logger.error(f"Error getting users: {e}")
        return []
    finally:
        if conn:
            await conn.close()

async def get_user_count() -> int:
    conn = None
    try:
        conn = await asyncpg.connect(
            database=os.getenv('PGDATABASE'),
            user=os.getenv('PGUSER'),
            password=os.getenv('PGPASSWORD'),
            host=os.getenv('PGHOST'),
            port=os.getenv('PGPORT')
        )
        
        return await conn.fetchval('SELECT COUNT(*) FROM users')
    except Exception as e:
        logger.error(f"Error getting user count: {e}")
        return 0
    finally:
        if conn:
            await conn.close()

async def update_user_activity(user_id: int):
    conn = None
    try:
        conn = await asyncpg.connect(
            database=os.getenv('PGDATABASE'),
            user=os.getenv('PGUSER'),
            password=os.getenv('PGPASSWORD'),
            host=os.getenv('PGHOST'),
            port=os.getenv('PGPORT')
        )
        
        await conn.execute('''
            UPDATE users 
            SET last_active = CURRENT_TIMESTAMP 
            WHERE user_id = $1
        ''', user_id)
    except Exception as e:
        logger.error(f"Error updating user activity: {e}")
    finally:
        if conn:
            await conn.close()

async def get_active_users_count() -> int:
    conn = None
    try:
        conn = await asyncpg.connect(
            database=os.getenv('PGDATABASE'),
            user=os.getenv('PGUSER'),
            password=os.getenv('PGPASSWORD'),
            host=os.getenv('PGHOST'),
            port=os.getenv('PGPORT')
        )
        
        # Count users active in the last 24 hours
        query = '''
            SELECT COUNT(*) 
            FROM users 
            WHERE last_active >= NOW() - INTERVAL '24 hours'
        '''
        return await conn.fetchval(query)
    except Exception as e:
        logger.error(f"Error getting active users count: {e}")
        return 0
    finally:
        if conn:
            await conn.close()
