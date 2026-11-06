"""Sample people and grades for the demo. Every name, student number and programme here is invented."""
import bcrypt

SAMPLE_PASSWORD = "pass123"

# username: (full name, student number, programme, year level)
PROFILES = {
    "teacher1": ("Prof. Elena Marsh", None, None, None),
    "academic_admin1": ("Dr. Samuel Okafor", None, None, None),
    "registrar1": ("Grace Lindqvist", None, None, None),
    "it_admin1": ("Rafael Domingo", None, None, None),
    "it_admin2": ("Nadia Flores", None, None, None),
    "student1": ("Maya Santos", "2024-01482", "BS Computer Science", 2),
    "student2": ("Daniel Reyes", "2024-01507", "BS Information Technology", 2),
}

# username: (full name, student number, programme, year level, {subject: grade})
ROSTER = {
    "student3": ("Ana Villanueva", "2024-01533", "BS Computer Science", 2,
                 {"Math": 91, "Science": 89, "English": 94, "Programming": 96}),
    "student4": ("Joshua Lim", "2024-01541", "BS Computer Science", 2,
                 {"Math": 68, "Science": 74, "English": 81, "Programming": 77}),
    "student5": ("Priya Nair", "2024-01566", "BS Information Technology", 2,
                 {"Math": 88, "History": 90, "English": 85, "Programming": 92}),
    "student6": ("Marco Bautista", "2024-01578", "BS Information Technology", 2,
                 {"Math": 76, "History": 80, "English": 79}),
    "student7": ("Hannah Cruz", "2024-01592", "BS Computer Science", 2,
                 {"Math": 83, "Science": 87, "English": 90, "Programming": 84}),
    "student8": ("Luis Mendoza", "2024-01610", "BS Information Technology", 2,
                 {"Math": 72, "History": 79, "English": 75, "Programming": 81}),
    "student9": ("Sofia Aquino", "2024-01634", "BS Computer Science", 2,
                 {"Math": 97, "Science": 93, "English": 91, "Programming": 98}),
    "student10": ("Noah Tan", "2024-01651", "BS Computer Science", 2, {}),
    "student11": ("Bea Ramos", "2024-01669", "BS Information Technology", 2,
                  {"Math": 84, "History": 86, "English": 88, "Programming": 79}),
    "student12": ("Ethan Dela Cruz", "2024-01688", "BS Computer Science", 2,
                  {"Math": 79, "Science": 65, "English": 77, "Programming": 83}),
}


def seed_people(conn, teacher="teacher1"):
    """Fills in profiles, adds the sample class, and ensures a second IT admin exists.
    Safe to run twice: existing rows are left alone."""
    for username, (full_name, student_no, program, year_level) in PROFILES.items():
        conn.execute(
            "UPDATE users SET full_name=COALESCE(full_name, ?), student_no=COALESCE(student_no, ?), "
            "program=COALESCE(program, ?), year_level=COALESCE(year_level, ?) WHERE username=?",
            (full_name, student_no, program, year_level, username),
        )

    # A second IT admin so one admin can unlock the other if an account locks.
    if not conn.execute("SELECT 1 FROM users WHERE username=?", ("it_admin2",)).fetchone():
        hashed = bcrypt.hashpw(SAMPLE_PASSWORD.encode(), bcrypt.gensalt()).decode()
        conn.execute(
            "INSERT INTO users (username, password, role, full_name) VALUES (?, ?, ?, ?)",
            ("it_admin2", hashed, "it_admin", PROFILES["it_admin2"][0]),
        )

    for username, (full_name, student_no, program, year_level, grades) in ROSTER.items():
        if conn.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
            continue
        hashed = bcrypt.hashpw(SAMPLE_PASSWORD.encode(), bcrypt.gensalt()).decode()
        student_id = conn.execute(
            "INSERT INTO users (username, password, role, full_name, student_no, program, year_level) "
            "VALUES (?, ?, 'student', ?, ?, ?, ?)",
            (username, hashed, full_name, student_no, program, year_level),
        ).lastrowid
        for subject, grade in grades.items():
            conn.execute(
                "INSERT INTO grades (student_id, subject, grade, updated_by) VALUES (?, ?, ?, ?)",
                (student_id, subject, grade, teacher),
            )
