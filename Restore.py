import shutil
import os

# Define the backup and source directories
backup_dir = './backups'
source_dir = './'

# Restore files.db
backup_files_db = os.path.join(backup_dir, 'files_backup_<timestamp>.db')  # Use the correct timestamped backup file
source_files_db = os.path.join(source_dir, 'files.db')
shutil.copy2(backup_files_db, source_files_db)
print(f"Restored files.db from {backup_files_db}")

# Restore verification.db
backup_verification_db = os.path.join(backup_dir, 'verification_backup_<timestamp>.db')  # Use the correct timestamped backup file
source_verification_db = os.path.join(source_dir, 'verification.db')
shutil.copy2(backup_verification_db, source_verification_db)
print(f"Restored verification.db from {backup_verification_db}")
