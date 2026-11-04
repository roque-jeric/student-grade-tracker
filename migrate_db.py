"""Upgrades an existing database.db in place, keeping its users, grades and audit log.
Adds the profile columns and the sample class, after saving a copy to database.db.bak.
Unlike init_db.py, this never deletes anything. Safe to run more than once."""
import os
import shutil
import sqlite3

from sample_data import seed_people

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "database.db")
PROFILE_COLUMNS = {"full_name": "TEXT", "student_no": "TEXT", "program": "TEXT", "year_level": "INTEGER"}


def migrate(path=DB_PATH):
    shutil.copy2(path, path + ".bak")
    conn = sqlite3.connect(path)
    try:
        existing = {row[1] for row in conn.execute("PRAGMA table_info(users)")}
        for name, kind in PROFILE_COLUMNS.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE users ADD COLUMN {name} {kind}")
        seed_people(conn)
        # The grades on record are final grades, not a preliminary term.
        conn.execute("UPDATE grading_periods SET name='Final' WHERE name='Prelim'")
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    migrate()
    print(f"Migrated {DB_PATH}. The previous copy is at {DB_PATH}.bak")
