import psycopg2
import uuid
import base64
import os
from dotenv import load_dotenv
import logging

# Load environment variables
load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def ensure_tables():
    try:
        conn = psycopg2.connect(
            dbname=os.getenv('PGDATABASE'),
            user=os.getenv('PGUSER'),
            password=os.getenv('PGPASSWORD'),
            host=os.getenv('PGHOST'),
            port=os.getenv('PGPORT')
        )
        with conn.cursor() as cursor:
            cursor.execute('''CREATE TABLE IF NOT EXISTS files
                          (id TEXT PRIMARY KEY, access_hash TEXT, file_reference BYTEA, 
                           mime_type TEXT, caption TEXT, keywords TEXT, file_name TEXT)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS tokens
                          (token TEXT PRIMARY KEY, file_id TEXT)''')
        conn.commit()
        logger.info("Database tables verified.")
    except Exception as e:
        logger.error(f"Error ensuring tables: {e}")
    finally:
        conn.close()

def generate_and_store_token(file_id):
    try:
        token = str(uuid.uuid4())
        encoded_token = base64.urlsafe_b64encode(token.encode()).decode()
        conn = psycopg2.connect(
            dbname=os.getenv('PGDATABASE'),
            user=os.getenv('PGUSER'),
            password=os.getenv('PGPASSWORD'),
            host=os.getenv('PGHOST'),
            port=os.getenv('PGPORT')
        )
        with conn.cursor() as cursor:
            cursor.execute('''
                INSERT INTO tokens (token, file_id) 
                VALUES (%s, %s)
                ON CONFLICT (token) DO NOTHING
                RETURNING token
            ''', (encoded_token, file_id))
            conn.commit()
            result = cursor.fetchone()
            return result[0] if result else None
    except Exception as e:
        logger.error(f"Error generating token: {e}")
        return None
    finally:
        conn.close()

def main():
    ensure_tables()
    file_id = input("Enter file ID to generate token: ")
    token = generate_and_store_token(file_id)
    if token:
        logger.info(f"Generated token: {token}")
    else:
        logger.error("Failed to generate token")

if __name__ == "__main__":
    main()
