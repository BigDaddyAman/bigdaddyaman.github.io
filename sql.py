import os
import psycopg2
from psycopg2 import sql
from dotenv import load_dotenv
import tkinter as tk
from tkinter import messagebox, Listbox, Scrollbar, END, simpledialog, filedialog
import subprocess

# Load environment variables from .env file
load_dotenv()

# Get database credentials from environment variables
DB_NAME = os.getenv('PGDATABASE')
DB_USER = os.getenv('PGUSER')
DB_PASSWORD = os.getenv('PGPASSWORD')
DB_HOST = os.getenv('PGHOST')
DB_PORT = os.getenv('PGPORT')

# Connect to PostgreSQL database
def connect_db():
    return psycopg2.connect(
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        host=DB_HOST,
        port=DB_PORT
    )

# Function to fetch and display files
def fetch_files():
    conn = connect_db()
    cur = conn.cursor()
    cur.execute("SELECT id, file_name FROM files ORDER BY id;")
    rows = cur.fetchall()
    listbox_files.delete(0, END)
    for row in rows:
        listbox_files.insert(END, row)
    conn.close()

# Function to delete selected file
def delete_file():
    selected = listbox_files.curselection()
    if not selected:
        messagebox.showwarning("Delete", "No file selected.")
        return
    file_id = listbox_files.get(selected[0])[0]
    conn = connect_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM files WHERE id = %s;", (file_id,))
    conn.commit()
    conn.close()
    fetch_files()

# Function to edit selected file name
def edit_file():
    selected = listbox_files.curselection()
    if not selected:
        messagebox.showwarning("Edit", "No file selected.")
        return
    file_id, current_name = listbox_files.get(selected[0])
    new_name = simpledialog.askstring("Edit File Name", "Enter new file name:", initialvalue=current_name)
    if new_name:
        conn = connect_db()
        cur = conn.cursor()
        cur.execute("UPDATE files SET file_name = %s WHERE id = %s;", (new_name, file_id))
        conn.commit()
        conn.close()
        fetch_files()

# Function to copy selected file details to clipboard
def copy_file():
    selected = listbox_files.curselection()
    if not selected:
        messagebox.showwarning("Copy", "No file selected.")
        return
    file_details = listbox_files.get(selected[0])
    root.clipboard_clear()
    root.clipboard_append(file_details)
    messagebox.showinfo("Copy", "File details copied to clipboard.")

# Function to search files by keyword
def search_files():
    keyword = entry_search.get()
    if not keyword:
        messagebox.showwarning("Search", "No keyword entered.")
        return
    conn = connect_db()
    cur = conn.cursor()
    cur.execute("SELECT id, file_name FROM files WHERE to_tsvector('english', keywords) @@ to_tsquery('english', %s);", (keyword,))
    rows = cur.fetchall()
    listbox_files.delete(0, END)
    for row in rows:
        listbox_files.insert(END, row)
    conn.close()

# Function to backup files table using pg_dump
def backup_files():
    backup_path = filedialog.asksaveasfilename(defaultextension=".sql", filetypes=[("SQL files", "*.sql")])
    if backup_path:
        cmd = f"pg_dump -U {DB_USER} -h {DB_HOST} -p {DB_PORT} -t files -f {backup_path} {DB_NAME}"
        env = os.environ.copy()
        env["PGPASSWORD"] = DB_PASSWORD
        subprocess.run(cmd, shell=True, env=env)
        messagebox.showinfo("Backup", f"Files table backed up to {backup_path}")

# Create main window
root = tk.Tk()
root.title("File Manager")

# Create UI elements
frame = tk.Frame(root)
frame.pack(padx=20, pady=20)

label_search = tk.Label(frame, text="Search Files:", font=('Arial', 14))
label_search.grid(row=0, column=0, padx=10, pady=10)

entry_search = tk.Entry(frame, font=('Arial', 14), width=30)
entry_search.grid(row=0, column=1, padx=10, pady=10)

button_search = tk.Button(frame, text="Search", command=search_files, font=('Arial', 14))
button_search.grid(row=0, column=2, padx=10, pady=10)

listbox_files = Listbox(frame, width=70, height=20, font=('Arial', 12))
listbox_files.grid(row=1, column=0, columnspan=4, padx=10, pady=10)

scrollbar_files = Scrollbar(frame, orient=tk.VERTICAL, command=listbox_files.yview)
scrollbar_files.grid(row=1, column=4, sticky='ns')
listbox_files.config(yscrollcommand=scrollbar_files.set)

button_delete = tk.Button(frame, text="Delete", command=delete_file, font=('Arial', 14))
button_delete.grid(row=2, column=0, padx=10, pady=10)

button_edit = tk.Button(frame, text="Edit", command=edit_file, font=('Arial', 14))
button_edit.grid(row=2, column=1, padx=10, pady=10)

button_copy = tk.Button(frame, text="Copy", command=copy_file, font=('Arial', 14))
button_copy.grid(row=2, column=2, padx=10, pady=10)

button_backup = tk.Button(frame, text="Backup", command=backup_files, font=('Arial', 14))
button_backup.grid(row=2, column=3, padx=10, pady=10)

# Initialize list of files
fetch_files()

# Run the GUI loop
root.mainloop()
