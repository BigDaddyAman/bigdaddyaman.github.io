import sqlite3
import uuid
import base64

# Ensure the databases and tables are created
def ensure_tables(db_filename):
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

# Function to generate and store a token
def generate_and_store_token(file_id):
    token = str(uuid.uuid4())  # Generate a unique token
    encoded_token = base64.urlsafe_b64encode(token.encode()).decode()
    conn = sqlite3.connect('verification.db')
    cursor = conn.cursor()
    cursor.execute('INSERT INTO tokens (token, file_id) VALUES (?, ?)', (encoded_token, file_id))
    conn.commit()
    conn.close()
    return encoded_token

# Example usage to ensure databases and generate a token
def main():
    # Ensure the databases and tables are created
    db_files = ['files.db', 'verification.db']
    for db_filename in db_files:
        ensure_tables(db_filename)

    # Generate and display a token
    file_id = 'file-id-of-your-video'  # Replace with actual file_id
    token = generate_and_store_token(file_id)
    print(f"Generated token: {token}")

if __name__ == "__main__":
    main()
