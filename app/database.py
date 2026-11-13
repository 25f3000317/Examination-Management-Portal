import sqlite3
from pathlib import Path
from flask import g

base_dir = Path(__file__).resolve().parent.parent
instance_dir = base_dir / "instance"
database_path = instance_dir / "emp.db"
instance_dir.mkdir(parents=True, exist_ok=True)

def get_db_connection():
    if 'db' not in g:
        g.db = sqlite3.connect(database_path)
        g.db.execute("PRAGMA foreign_keys = ON;")
        g.db.row_factory = sqlite3.Row
    return g.db

def close_db_connection(exception):
    db = g.pop("db", None)
    if db is not None:
        db.close()