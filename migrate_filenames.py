import asyncio
import asyncpg
from dotenv import load_dotenv
import os
import re
import json
from datetime import datetime

load_dotenv()

def format_filename(filename: str) -> str:
    """Format filename consistently for display and storage"""
    if not filename:
        return filename
    # Remove special characters and brackets with their contents
    formatted = re.sub(r'\([^)]*\)', '', filename)  # Remove (anything)
    formatted = re.sub(r'\[[^]]*\]', '', formatted)  # Remove [anything]
    formatted = re.sub(r'\{[^}]*\}', '', formatted)  # Remove special characters except dots and alphanumeric
    formatted = re.sub(r'[^a-zA-Z0-9.]', '.', formatted)
    # Convert multiple dots to single dot
    formatted = re.sub(r'\.+', '.', formatted)
    # Remove leading/trailing dots
    formatted = formatted.strip('.')
    return formatted

async def backup_and_migrate():
    conn = await asyncpg.connect(
        database=os.getenv('PGDATABASE'),
        user=os.getenv('PGUSER'),
        password=os.getenv('PGPASSWORD'),
        host=os.getenv('PGHOST'),
        port=os.getenv('PGPORT')
    )
    
    try:
        # First create backup
        print("Creating backup...")
        rows = await conn.fetch('SELECT * FROM files')
        backup_data = [dict(row) for row in rows]
        
        # Save backup
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_file = f'files_backup_{timestamp}.json'
        with open(backup_file, 'w', encoding='utf-8') as f:
            json.dump(backup_data, f, default=str)
        print(f"Backup saved to {backup_file}")
        
        # Perform migration
        print("\nStarting migration with updated filename format...")
        count = 0
        total = len(rows)
        
        for idx, row in enumerate(rows):
            old_name = row['file_name']
            if not old_name:
                continue
                
            new_name = format_filename(old_name)
            
            if old_name != new_name:
                await conn.execute(
                    'UPDATE files SET file_name = $1 WHERE id = $2',
                    new_name, row['id']
                )
                count += 1
                if count % 100 == 0:
                    print(f"Progress: {idx+1}/{total} files processed, {count} updated")
                    print(f"Sample: {old_name} -> {new_name}")
        
        print(f"\nMigration complete. {count} files updated.")
        print(f"Backup saved to: {backup_file}")

        print("\nStarting final filename format migration...")
        for idx, row in enumerate(rows):
            old_name = row['file_name']
            if not old_name:
                continue
                
            new_name = format_filename(old_name)
            
            if old_name != new_name:
                await conn.execute(
                    'UPDATE files SET file_name = $1 WHERE id = $2',
                    new_name, row['id']
                )
                count += 1
                if count % 100 == 0:
                    print(f"Progress: {idx+1}/{total} files processed")
                    print(f"Example: {old_name} -> {new_name}")
        
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(backup_and_migrate())
