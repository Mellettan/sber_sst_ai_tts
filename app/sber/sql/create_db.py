import os
import sqlite3

from loguru import logger

db_path = os.path.join(os.path.dirname(__file__), "..", "sber.db")
conn = sqlite3.connect(db_path)

cursor = conn.cursor()

create_table_query = """
CREATE TABLE IF NOT EXISTS tokens (
    name TEXT PRIMARY KEY,
    token TEXT NOT NULL,
    expires_at INTEGER NOT NULL
);
"""

cursor.executescript(create_table_query)

conn.commit()

conn.close()

logger.info("Database created successfully.")
