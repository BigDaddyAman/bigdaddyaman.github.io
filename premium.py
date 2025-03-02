import logging
import asyncpg
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

async def init_premium_db():
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
            CREATE TABLE IF NOT EXISTS premium_users (
                user_id BIGINT PRIMARY KEY,
                expiry_date TIMESTAMP NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        logger.info("Premium database initialized successfully")
    except Exception as e:
        logger.error(f"Error initializing premium database: {e}")
        raise
    finally:
        if conn:
            await conn.close()

async def is_premium(user_id: int) -> bool:
    conn = None
    try:
        conn = await asyncpg.connect(
            database=os.getenv('PGDATABASE'),
            user=os.getenv('PGUSER'),
            password=os.getenv('PGPASSWORD'),
            host=os.getenv('PGHOST'),
            port=os.getenv('PGPORT')
        )
        
        result = await conn.fetchrow('''
            SELECT * FROM premium_users 
            WHERE user_id = $1 AND expiry_date > CURRENT_TIMESTAMP
        ''', user_id)
        
        return bool(result)
    except Exception as e:
        logger.error(f"Error checking premium status: {e}")
        return False
    finally:
        if conn:
            await conn.close()

async def add_or_renew_premium(user_id: int, days: int) -> bool:
    conn = None
    try:
        conn = await asyncpg.connect(
            database=os.getenv('PGDATABASE'),
            user=os.getenv('PGUSER'),
            password=os.getenv('PGPASSWORD'),
            host=os.getenv('PGHOST'),
            port=os.getenv('PGPORT')
        )
        
        # Calculate new expiry date
        expiry_date = datetime.now() + timedelta(days=days)
        
        await conn.execute('''
            INSERT INTO premium_users (user_id, expiry_date)
            VALUES ($1, $2)
            ON CONFLICT (user_id) DO UPDATE
            SET expiry_date = $2
        ''', user_id, expiry_date)
        
        return True
    except Exception as e:
        logger.error(f"Error adding/renewing premium: {e}")
        return False
    finally:
        if conn:
            await conn.close()

async def get_premium_status(user_id: int) -> dict:
    conn = None
    try:
        conn = await asyncpg.connect(
            database=os.getenv('PGDATABASE'),
            user=os.getenv('PGUSER'),
            password=os.getenv('PGPASSWORD'),
            host=os.getenv('PGHOST'),
            port=os.getenv('PGPORT')
        )
        
        result = await conn.fetchrow('''
            SELECT * FROM premium_users 
            WHERE user_id = $1
        ''', user_id)
        
        if result:
            expiry_date = result['expiry_date']
            is_active = expiry_date > datetime.now()
            days_left = (expiry_date - datetime.now()).days
            
            return {
                "is_premium": is_active,
                "expiry_date": expiry_date,
                "days_left": max(0, days_left)
            }
        
        return {
            "is_premium": False,
            "expiry_date": None,
            "days_left": 0
        }
    except Exception as e:
        logger.error(f"Error getting premium status: {e}")
        return None
    finally:
        if conn:
            await conn.close()
