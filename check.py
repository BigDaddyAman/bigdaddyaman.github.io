import sqlite3

def check_all_tokens():
    # Connect to the verification.db database
    conn = sqlite3.connect('verification.db')
    cursor = conn.cursor()

    # Check if the tokens table exists
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tokens';")
    table_exists = cursor.fetchone()

    if not table_exists:
        print("The tokens table does not exist in the database.")
        return

    # Query all tokens in the tokens table
    cursor.execute("SELECT * FROM tokens")
    results = cursor.fetchall()

    if results:
        for row in results:
            print(f"Token: {row[0]}, File ID: {row[1]}")
    else:
        print("No tokens found.")

    # Close the database connection
    conn.close()

# Example usage
check_all_tokens()
