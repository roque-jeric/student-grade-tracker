DROP TABLE IF EXISTS audit_logs;
DROP TABLE IF EXISTS grade_change_requests;
DROP TABLE IF EXISTS grading_periods;
DROP TABLE IF EXISTS grades;
DROP TABLE IF EXISTS users;

CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('student','teacher','academic_admin','registrar','it_admin')),
    is_locked BOOLEAN DEFAULT 0,
    failed_attempts INTEGER DEFAULT 0,
    full_name TEXT,
    student_no TEXT,
    program TEXT,
    year_level INTEGER
);

CREATE TABLE grades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL,
    subject TEXT NOT NULL,
    grade INTEGER NOT NULL,
    updated_by TEXT NOT NULL,
    FOREIGN KEY (student_id) REFERENCES users(id)
);

CREATE TABLE grading_periods (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    status TEXT DEFAULT 'open'
);

CREATE TABLE grade_change_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    grade_id INTEGER NOT NULL,
    new_grade INTEGER NOT NULL,
    requested_by TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    reviewed_by TEXT,
    FOREIGN KEY (grade_id) REFERENCES grades(id)
);

CREATE TABLE audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    user_id INTEGER,
    action TEXT,
    details TEXT
);
