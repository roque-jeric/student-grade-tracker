import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "database.db")
SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")

if os.path.exists(DB_PATH):
    os.remove(DB_PATH)
    print(f"Removed existing {DB_PATH}")

conn = sqlite3.connect(DB_PATH)
with open(SCHEMA_PATH, "r") as f:
    conn.executescript(f.read())

users = [
    ("teacher1", "pass123", "teacher"),
    ("student1", "pass123", "student"),
    ("student2", "pass123", "student"),
]

for username, password, role in users:
    conn.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)", (username, password, role))

cur = conn.execute("SELECT id, username FROM users WHERE role='student'")
student_map = {row[1]: row[0] for row in cur.fetchall()}

grades = [
    (student_map["student1"], "Math", 92, "teacher1"),
    (student_map["student1"], "Science", 85, "teacher1"),
    (student_map["student2"], "Math", 78, "teacher1"),
    (student_map["student2"], "History", 88, "teacher1"),
]

for student_id, subject, grade, updated_by in grades:
    conn.execute("INSERT INTO grades (student_id, subject, grade, updated_by) VALUES (?, ?, ?, ?)",
                 (student_id, subject, grade, updated_by))

conn.commit()
conn.close()
print(f"Database initialized at {DB_PATH}")
print("Seeded users:")
for u in users:
    print(f"  {u[0]} / {u[1]} / {u[2]}")
