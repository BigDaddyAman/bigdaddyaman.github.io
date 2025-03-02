import os
import logging
import subprocess
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def restore_backup(backup_file):
    if not os.path.exists(backup_file):
        logger.error(f"Backup file not found: {backup_file}")
        return False

    try:
        # Get database credentials from environment
        db_name = os.getenv('PGDATABASE')
        db_user = os.getenv('PGUSER')
        db_host = os.getenv('PGHOST')

        # Set up environment with password
        env = os.environ.copy()
        env['PGPASSWORD'] = os.getenv('PGPASSWORD')

        # Run psql to restore
        result = subprocess.run([
            'psql',
            '-h', db_host,
            '-U', db_user,
            '-d', db_name,
            '-f', backup_file
        ], env=env, capture_output=True, text=True)

        if result.returncode == 0:
            logger.info(f"Database restored successfully from: {backup_file}")
            return True
        else:
            logger.error(f"Restore failed: {result.stderr}")
            return False

    except Exception as e:
        logger.error(f"Restore error: {e}")
        return False

def main():
    backup_dir = os.path.join(os.path.dirname(__file__), 'backups')
    
    # List available backups
    backups = sorted([f for f in os.listdir(backup_dir) if f.endswith('.sql')])
    
    if not backups:
        logger.error("No backup files found")
        return

    logger.info("Available backups:")
    for i, backup in enumerate(backups):
        logger.info(f"{i+1}. {backup}")

    try:
        choice = int(input("Enter the number of the backup to restore: ")) - 1
        if 0 <= choice < len(backups):
            backup_file = os.path.join(backup_dir, backups[choice])
            restore_backup(backup_file)
        else:
            logger.error("Invalid selection")
    except ValueError:
        logger.error("Please enter a valid number")

if __name__ == "__main__":
    main()
