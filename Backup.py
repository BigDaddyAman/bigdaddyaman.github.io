import shutil
import os
from datetime import datetime

# Define the source and backup directories
source_dir = './'
backup_dir = './backups'

# Ensure the backup directory exists
os.makedirs(backup_dir, exist_ok=True)

# Define the current time for versioning the backup
current_time = datetime.now().strftime('%Y%m%d%H%M%S')

# Backup files.db
source_files_db = os.path.join(source_dir, 'files.db')
backup_files_db = os.path.join(backup_dir, f'files_backup_{current_time}.db')
shutil.copy2(source_files_db, backup_files_db)
print(f"Backed up files.db to {backup_files_db}")

# Backup verification.db
source_verification_db = os.path.join(source_dir, 'verification.db')
backup_verification_db = os.path.join(backup_dir, f'verification_backup_{current_time}.db')
shutil.copy2(source_verification_db, backup_verification_db)
print(f"Backed up verification.db to {backup_verification_db}")
