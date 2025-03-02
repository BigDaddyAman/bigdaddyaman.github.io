import psycopg2
import logging
from dotenv import load_dotenv
import os

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def check_all_tokens():
    try:
        conn = psycopg2.connect(
            dbname=os.getenv('PGDATABASE'),
            user=os.getenv('PGUSER'),
            password=os.getenv('PGPASSWORD'),
            host=os.getenv('PGHOST'),
            port=os.getenv('PGPORT')
        )
        
        with conn.cursor() as cursor:
            cursor.execute("SELECT to_regclass('public.tokens');")
            table_exists = cursor.fetchone()[0]

            if not table_exists:
                logger.warning("The tokens table does not exist in the database.")
                return

            cursor.execute("SELECT token, file_id FROM tokens ORDER BY token")
            results = cursor.fetchall()

            if results:
                logger.info(f"Found {len(results)} tokens:")
                for token, file_id in results:
                    logger.info(f"Token: {token}, File ID: {file_id}")
            else:
                logger.info("No tokens found in database.")

    except psycopg2.Error as e:
        logger.error(f"Database error: {e}")
    except Exception as e:
        logger.error(f"Error: {e}")
    finally:
        if 'conn' in locals():
            conn.close()

if __name__ == "__main__":
    check_all_tokens()
