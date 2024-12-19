import sqlite3
import os

# Function to reset the files.db and verification.db databases
def reset_databases():
    db_files = ['files.db', 'verification.db']
    
    for db_filename in db_files:
        if os.path.exists(db_filename):
            os.remove(db_filename)
            print(f"{db_filename} deleted.")

        conn = sqlite3.connect(db_filename)
        c = conn.cursor()
        
        if db_filename == 'files.db':
            c.execute('''CREATE TABLE IF NOT EXISTS files
                         (id TEXT PRIMARY KEY, access_hash TEXT, file_reference BLOB, mime_type TEXT, caption TEXT, keywords TEXT, file_name TEXT)''')
        elif db_filename == 'verification.db':
            c.execute('''CREATE TABLE IF NOT EXISTS tokens
                         (token TEXT PRIMARY KEY, file_id TEXT)''')
        
        conn.commit()
        conn.close()
        print(f"{db_filename} recreated with necessary tables.")

# Run the reset function
reset_databases()
