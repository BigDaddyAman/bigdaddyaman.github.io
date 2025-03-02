import os
import logging
from datetime import datetime
import subprocess
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def create_backup():
    try:
        # Define the backup directory
        backup_dir = os.path.join(os.path.dirname(__file__), 'backups')
        os.makedirs(backup_dir, exist_ok=True)

        # Get database credentials from environment
        db_name = os.getenv('PGDATABASE')
        db_user = os.getenv('PGUSER')
        db_host = os.getenv('PGHOST')

        # Create timestamp
        current_time = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        # Backup files database
        backup_path = os.path.join(backup_dir, f'database_backup_{current_time}.sql')
        
        # Run pg_dump with password from environment variable
        env = os.environ.copy()
        env['PGPASSWORD'] = os.getenv('PGPASSWORD')
        
        result = subprocess.run([
            'pg_dump',
            '-h', db_host,
            '-U', db_user,
            '-d', db_name,
            '-f', backup_path
        ], env=env, capture_output=True, text=True)

        if result.returncode == 0:
            logger.info(f"Backup created successfully at: {backup_path}")
        else:
            logger.error(f"Backup failed: {result.stderr}")

    except Exception as e:
        logger.error(f"Backup error: {e}")

if __name__ == "__main__":
    create_backup()
