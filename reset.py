import psycopg2
import logging
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def reset_databases():
    try:
        conn = psycopg2.connect(
            dbname=os.getenv('PGDATABASE'),
            user=os.getenv('PGUSER'),
            password=os.getenv('PGPASSWORD'),
            host=os.getenv('PGHOST'),
            port=os.getenv('PGPORT')
        )
        with conn.cursor() as cursor:
            cursor.execute('DROP TABLE IF EXISTS tokens')  # Drop tokens first due to foreign key
            cursor.execute('DROP TABLE IF EXISTS files')
            
            # Recreate tables
            cursor.execute('''CREATE TABLE files
                          (id TEXT PRIMARY KEY, access_hash TEXT, file_reference BYTEA, 
                           mime_type TEXT, caption TEXT, keywords TEXT, file_name TEXT)''')
            cursor.execute('''CREATE TABLE tokens
                          (token TEXT PRIMARY KEY, file_id TEXT UNIQUE, 
                           FOREIGN KEY (file_id) REFERENCES files(id))''')
        conn.commit()
        logger.info("Database reset completed successfully.")
    except Exception as e:
        logger.error(f"Error resetting databases: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    confirmation = input("This will reset all database tables. Are you sure? (y/N): ")
    if confirmation.lower() == 'y':
        reset_databases()
    else:
        logger.info("Reset cancelled.")
