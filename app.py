from flask import Flask, request, redirect, session, render_template, g
import sqlite3
import os
import re
import secrets
import logging
import datetime
from functools import wraps
import bcrypt

app = Flask(__name__)

app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))

app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SECURE'] = False
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['PERMANENT_SESSION_LIFETIME'] = 1800

DATABASE = os.path.join(os.path.dirname(__file__), "database.db")

logging.basicConfig(
    filename=os.path.join(os.path.dirname(__file__), "app.log"),
    level=logging.ERROR,
    format="%(asctime)s %(levelname)s %(message)s",
)

VALID_ROLES = ('student', 'teacher', 'academic_admin', 'registrar', 'it_admin')
MAX_FAILED_ATTEMPTS = 5
USERNAME_RE = re.compile(r'^[A-Za-z0-9_]{3,32}$')
SUBJECT_RE = re.compile(r'^[A-Za-z0-9 .\-]{1,50}$')
PASS_MARK = 75

GRADES_SELECT = (
    "SELECT grades.id, grades.student_id, grades.subject, grades.grade, "
    "COALESCE(entered.full_name, grades.updated_by) AS updated_by, "
    "COALESCE(student.full_name, student.username) AS student_name, student.student_no "
    "FROM grades JOIN users student ON grades.student_id = student.id "
    "LEFT JOIN users entered ON entered.username = grades.updated_by"
)
STUDENTS_SELECT = (
    "SELECT id, username, COALESCE(full_name, username) AS full_name, student_no, program, year_level "
    "FROM users WHERE role='student'"
)


def csrf_token():
    """The session's form token. Every POST form carries it in a hidden field."""
    token = session.get("csrf_token")
    if not token:
        token = session["csrf_token"] = secrets.token_urlsafe(32)
    return token


app.jinja_env.globals["csrf_token"] = csrf_token


@app.before_request
def check_csrf():
    if request.method != "POST":
        return None
    sent = request.form.get("csrf_token", "")
    expected = session.get("csrf_token", "")
    if not expected or not sent or not secrets.compare_digest(sent, expected):
        logging.error(f"csrf rejected path={request.path} user={session.get('username')}")
        return "This form has expired. Go back, reload the page and try again.", 400
    return None


def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db


@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()


@app.context_processor
def shell_context():
    if "user_id" not in session:
        return {"pass_mark": PASS_MARK}
    try:
        db = get_db()
        shell_user = db.execute("SELECT full_name FROM users WHERE id=?", (session["user_id"],)).fetchone()
        period = db.execute("SELECT * FROM grading_periods LIMIT 1").fetchone()
        pending = db.execute("SELECT COUNT(*) FROM grade_change_requests WHERE status='pending'").fetchone()[0]
    except Exception as e:
        logging.error(f"shell context failed err={e}")
        return {"pass_mark": PASS_MARK}
    return {
        "pass_mark": PASS_MARK,
        "shell_period": period,
        "shell_pending": pending,
        "shell_name": (shell_user["full_name"] if shell_user else None) or session.get("username"),
    }


def audit(user_id, action, details):
    try:
        db = get_db()
        db.execute(
            "INSERT INTO audit_logs (user_id, action, details) VALUES (?, ?, ?)",
            (user_id, action, details),
        )
        db.commit()
    except Exception as e:
        logging.error(f"audit failed action={action} err={e}")


def valid_username(s):
    return bool(s and USERNAME_RE.match(s))


def valid_subject(s):
    return bool(s and SUBJECT_RE.match(s))


def valid_grade(s):
    try:
        v = int(s)
        return 0 <= v <= 100
    except (TypeError, ValueError):
        return False


def valid_id(s):
    try:
        return int(s) > 0
    except (TypeError, ValueError):
        return False


def current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    try:
        if not valid_id(uid):
            session.clear()
            return None
        db = get_db()
        user = db.execute("SELECT * FROM users WHERE id=?", (int(uid),)).fetchone()
        if not user:
            session.clear()
            return None
        if user["is_locked"]:
            session.clear()
            return None

        if session.get("username") != user["username"] or session.get("role") != user["role"]:
            session.clear()
            return None
        return user
    except Exception as e:
        logging.error(f"current_user failed uid={uid} err={e}")
        return None


def require_role(*roles):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if "user_id" not in session:
                return redirect("/login")
            user = current_user()
            if not user:
                return redirect("/login")
            if user["role"] not in roles:
                logging.error(f"authz denied user={user['username']} role={user['role']} need={roles} path={request.path}")
                return "Unauthorized", 403
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def dashboard_data():
    db = get_db()
    all_students = db.execute(STUDENTS_SELECT).fetchall()
    all_users = db.execute("SELECT id, username, role, is_locked, failed_attempts, full_name, student_no FROM users").fetchall()
    period = db.execute("SELECT * FROM grading_periods LIMIT 1").fetchone()
    pending_requests = db.execute(
        "SELECT grade_change_requests.*, grades.subject, grades.grade as old_grade, grades.student_id, COALESCE(users.full_name, users.username) as student_name "
        "FROM grade_change_requests JOIN grades ON grade_change_requests.grade_id = grades.id "
        "JOIN users ON grades.student_id = users.id WHERE grade_change_requests.status='pending'"
    ).fetchall()
    audit_logs = db.execute(
        "SELECT audit_logs.*, users.username FROM audit_logs LEFT JOIN users ON audit_logs.user_id = users.id "
        "ORDER BY audit_logs.id DESC LIMIT 20"
    ).fetchall()
    return all_students, all_users, period, pending_requests, audit_logs


def mean(values):
    return sum(values) / len(values) if values else None


def surname_key(name):
    return (name.split()[-1].lower(), name.lower())


def class_roster(db):
    """One row per student, in surname order, with the figures the teacher's screens show."""
    students = db.execute(STUDENTS_SELECT).fetchall()
    grades = db.execute(GRADES_SELECT).fetchall()
    waiting = db.execute(
        "SELECT grades.student_id, COUNT(*) AS n FROM grade_change_requests "
        "JOIN grades ON grade_change_requests.grade_id = grades.id "
        "WHERE grade_change_requests.status='pending' GROUP BY grades.student_id"
    ).fetchall()
    waiting = {row["student_id"]: row["n"] for row in waiting}

    roster = []
    for s in sorted(students, key=lambda row: surname_key(row["full_name"])):
        own = [g for g in grades if g["student_id"] == s["id"]]
        below = [g for g in own if g["grade"] < PASS_MARK]
        roster.append({
            "id": s["id"],
            "name": s["full_name"],
            "student_no": s["student_no"],
            "program": s["program"],
            "year_level": s["year_level"],
            "grades": own,
            "below": sorted(below, key=lambda g: g["grade"]),
            "average": mean([g["grade"] for g in own]),
            "waiting": waiting.get(s["id"], 0),
            "standing": "none" if not own else ("below" if below else "passing"),
        })
    return roster


def course_averages(db):
    subjects = {}
    for g in db.execute(GRADES_SELECT).fetchall():
        subjects.setdefault(g["subject"], []).append(g["grade"])
    return [
        {"subject": name, "average": mean(marks), "count": len(marks), "below": sum(1 for m in marks if m < PASS_MARK)}
        for name, marks in sorted(subjects.items())
    ]


def render_roster(error=None, status=200):
    db = get_db()
    roster = class_roster(db)
    all_marks = [g["grade"] for s in roster for g in s["grades"]]
    return render_template(
        "students.html",
        roster=roster,
        courses=course_averages(db),
        class_average=mean(all_marks),
        grade_count=len(all_marks),
        period=db.execute("SELECT * FROM grading_periods LIMIT 1").fetchone(),
        error=error,
    ), status


def render_student(student_id, error=None, status=200):
    db = get_db()
    roster = class_roster(db)
    position = next((i for i, s in enumerate(roster) if s["id"] == student_id), None)
    if position is None:
        return "Student not found", 404
    student = roster[position]
    corrections = db.execute(
        "SELECT grade_change_requests.grade_id, grade_change_requests.new_grade "
        "FROM grade_change_requests JOIN grades ON grade_change_requests.grade_id = grades.id "
        "WHERE grades.student_id=? AND grade_change_requests.status='pending' "
        "ORDER BY grade_change_requests.id",
        (student_id,),
    ).fetchall()
    known_subjects = db.execute("SELECT DISTINCT subject FROM grades ORDER BY subject").fetchall()
    return render_template(
        "student_detail.html",
        student=student,
        previous=roster[position - 1] if position > 0 else None,
        next_student=roster[position + 1] if position + 1 < len(roster) else None,
        position=position + 1,
        roster_size=len(roster),
        corrections={c["grade_id"]: c["new_grade"] for c in corrections},
        known_subjects=[row["subject"] for row in known_subjects],
        period=db.execute("SELECT * FROM grading_periods LIMIT 1").fetchone(),
        error=error,
    ), status


def teacher_error(message, log_label, student_id=None, status=400):
    """Shows the error on the student the teacher was working on, or on the class list."""
    try:
        if valid_id(student_id):
            target = get_db().execute("SELECT id FROM users WHERE id=? AND role='student'", (int(student_id),)).fetchone()
            if target:
                return render_student(target["id"], error=message, status=status)
        return render_roster(error=message, status=status)
    except Exception as e:
        logging.error(f"{log_label} render failed err={e}")
        return "An error occurred. Please try again.", 500


def grade_owner(db, grade_id):
    row = db.execute("SELECT student_id FROM grades WHERE id=?", (int(grade_id),)).fetchone()
    return row["student_id"] if row else None


@app.route("/")
def index():
    if "username" in session:
        return redirect("/dashboard")
    return redirect("/login")


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username = (request.form.get("username", "") or "").strip()
        password = request.form.get("password", "") or ""

        db = get_db()
        try:
            check_user = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        except Exception as e:
            logging.error(f"login lookup failed err={e}")
            return render_template("login.html", error="An error occurred. Please try again.")

        if check_user and check_user["is_locked"]:
            audit(check_user["id"], "LOGIN_FAILED_LOCKED", f"Attempt on locked account {username}")
            return render_template("login.html", error="Account locked, contact IT Admin")

        user = None
        if check_user:
            try:
                if bcrypt.checkpw(password.encode(), check_user["password"].encode()):
                    user = check_user
            except Exception as e:
                logging.error(f"bcrypt check failed err={e}")

        if user:
            try:
                db.execute("UPDATE users SET failed_attempts=0 WHERE id=?", (user["id"],))
                db.commit()
            except Exception as e:
                logging.error(f"reset fails failed err={e}")
            audit(user["id"], "LOGIN_SUCCESS", f"User {username} logged in")
            session.clear()
            session["csrf_token"] = secrets.token_urlsafe(32)
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["role"] = user["role"]
            session.permanent = True
            return redirect("/dashboard")
        else:
            if check_user:
                try:
                    db.execute("UPDATE users SET failed_attempts = failed_attempts + 1 WHERE id=?", (check_user["id"],))
                    db.commit()
                    updated = db.execute("SELECT failed_attempts FROM users WHERE id=?", (check_user["id"],)).fetchone()
                    if updated and updated["failed_attempts"] >= MAX_FAILED_ATTEMPTS:
                        db.execute("UPDATE users SET is_locked=1 WHERE id=?", (check_user["id"],))
                        db.commit()
                        audit(check_user["id"], "ACCOUNT_LOCKED", f"Account {username} locked after {MAX_FAILED_ATTEMPTS} fails")
                        return render_template("login.html", error="Account locked, contact IT Admin")
                    audit(check_user["id"], "LOGIN_FAILED", f"Failed attempt for {username}")
                except Exception as e:
                    logging.error(f"lockout update failed err={e}")
            error = "Invalid username or password"

    return render_template("login.html", error=error)


@app.route("/forgot-password")
def forgot_password():
    return render_template("forgot_password.html")


@app.route("/logout")
def logout():
    if "user_id" in session:
        audit(session.get("user_id"), "LOGOUT", f"User {session.get('username')} logged out")
    session.clear()
    return redirect("/login")


@app.route("/dashboard")
def dashboard():
    if "username" not in session:
        return redirect("/login")
    user = current_user()
    if not user:
        return redirect("/login")
    role = user["role"]
    username = user["username"]
    user_id = user["id"]

    try:
        all_students, all_users, period, pending_requests, audit_logs = dashboard_data()
    except Exception as e:
        logging.error(f"dashboard data failed user={username} err={e}")
        return render_template("login.html", error="An error occurred. Please try again.")

    student_id_param = request.args.get("student_id")

    if role == "teacher":
        if student_id_param:
            if not valid_id(student_id_param):
                return teacher_error("Invalid input.", "teacher filter")
            return redirect(f"/students/{int(student_id_param)}")
        try:
            return render_roster()
        except Exception as e:
            logging.error(f"teacher roster failed user={username} err={e}")
            return "An error occurred. Please try again.", 500

    elif role == "academic_admin":
        if student_id_param:
            if not valid_id(student_id_param):
                return render_template("dashboard.html", role=role, username=username, grades=[], students=all_students, all_users=all_users, period=period, pending_requests=pending_requests, audit_logs=audit_logs, error="Invalid input.")
            try:
                grades = get_db().execute(
                    GRADES_SELECT + " WHERE grades.student_id=?",
                    (int(student_id_param),),
                ).fetchall()
            except Exception as e:
                logging.error(f"admin filter failed err={e}")
                return render_template("dashboard.html", role=role, username=username, grades=[], students=all_students, all_users=all_users, period=period, pending_requests=pending_requests, audit_logs=audit_logs, error="An error occurred. Please try again.")
        else:
            grades = get_db().execute(GRADES_SELECT).fetchall()
        return render_template("dashboard.html", role=role, username=username, grades=grades, students=all_students, all_users=all_users, period=period, pending_requests=pending_requests, audit_logs=audit_logs)

    elif role == "registrar":
        if student_id_param:
            if not valid_id(student_id_param):
                return render_template("dashboard.html", role=role, username=username, grades=[], students=all_students, all_users=all_users, period=period, pending_requests=pending_requests, audit_logs=audit_logs, error="Invalid input.")
            try:
                grades = get_db().execute(
                    GRADES_SELECT + " WHERE grades.student_id=?",
                    (int(student_id_param),),
                ).fetchall()
            except Exception as e:
                logging.error(f"registrar filter failed err={e}")
                return render_template("dashboard.html", role=role, username=username, grades=[], students=all_students, all_users=all_users, period=period, pending_requests=pending_requests, audit_logs=audit_logs, error="An error occurred. Please try again.")
        else:
            grades = get_db().execute(GRADES_SELECT).fetchall()
        return render_template("dashboard.html", role=role, username=username, grades=grades, students=all_students, all_users=all_users, period=period, pending_requests=pending_requests, audit_logs=audit_logs)

    elif role == "it_admin":
        grades = get_db().execute(GRADES_SELECT).fetchall()
        return render_template("dashboard.html", role=role, username=username, grades=grades, students=all_students, all_users=all_users, period=period, pending_requests=pending_requests, audit_logs=audit_logs)

    else:
        if student_id_param:
            if not valid_id(student_id_param) or int(student_id_param) != int(user_id):
                logging.error(f"student IDOR blocked user={username} tried={student_id_param}")
                return "Unauthorized", 403
        try:
            grades = get_db().execute(
                GRADES_SELECT + " WHERE grades.student_id=?",
                (user_id,),
            ).fetchall()
        except Exception as e:
            logging.error(f"student list failed err={e}")
            return render_template("dashboard.html", role=role, username=username, grades=[], students=[], all_users=all_users, period=period, pending_requests=pending_requests, audit_logs=audit_logs, error="An error occurred. Please try again.")
        return render_template("dashboard.html", role=role, username=username, grades=grades, students=[], all_users=all_users, period=period, pending_requests=pending_requests, audit_logs=audit_logs)


@app.route("/students/<int:student_id>")
@require_role("teacher")
def student_detail(student_id):
    try:
        return render_student(student_id)
    except Exception as e:
        logging.error(f"student detail failed id={student_id} err={e}")
        return "An error occurred. Please try again.", 500


@app.route("/add_grade", methods=["POST"])
@require_role("teacher")
def add_grade():
    user = current_user()
    db = get_db()
    period = db.execute("SELECT * FROM grading_periods LIMIT 1").fetchone()
    student_id = (request.form.get("student_id", "") or "").strip()
    subject = (request.form.get("subject", "") or "").strip()
    grade = (request.form.get("grade", "") or "").strip()

    if period and period["status"] != "open":
        return teacher_error(f"Grading period {period['status']}, cannot add grades", "add_grade locked", student_id, 200)

    if not valid_id(student_id) or not valid_subject(subject) or not valid_grade(grade):
        return teacher_error("Invalid input.", "add_grade validation", student_id)

    try:
        target = db.execute("SELECT id FROM users WHERE id=? AND role='student'", (int(student_id),)).fetchone()
        if not target:
            return teacher_error("Invalid input.", "add_grade unknown student")
        db.execute(
            "INSERT INTO grades (student_id, subject, grade, updated_by) VALUES (?, ?, ?, ?)",
            (int(student_id), subject, int(grade), user["username"]),
        )
        db.commit()
        audit(user["id"], "GRADE_ADD", f"Added grade {grade} for student {student_id} subject {subject}")
    except Exception as e:
        logging.error(f"add_grade failed user={user['username']} err={e}")
        return "An error occurred. Please try again.", 500

    return redirect(f"/students/{int(student_id)}")


@app.route("/request-correction", methods=["POST"])
@require_role("teacher")
def request_correction():
    user = current_user()
    db = get_db()
    grade_id = (request.form.get("grade_id", "") or "").strip()
    new_grade = (request.form.get("new_grade", "") or "").strip()

    owner = grade_owner(db, grade_id) if valid_id(grade_id) else None
    if not valid_id(grade_id) or not valid_grade(new_grade):
        return teacher_error("Invalid input.", "request-correction validation", owner)

    try:
        if owner is None:
            return teacher_error("Invalid input.", "request-correction unknown grade")
        db.execute(
            "INSERT INTO grade_change_requests (grade_id, new_grade, requested_by, status) VALUES (?, ?, ?, 'pending')",
            (int(grade_id), int(new_grade), user["username"]),
        )
        db.commit()
        audit(user["id"], "GRADE_CORRECTION_REQUEST", f"Requested correction grade_id {grade_id} -> {new_grade}")
    except Exception as e:
        logging.error(f"request-correction failed err={e}")
        return "An error occurred. Please try again.", 500

    return redirect(f"/students/{owner}")


@app.route("/update_grade", methods=["POST"])
@require_role("teacher")
def update_grade():
    user = current_user()
    db = get_db()
    grade_id = (request.form.get("grade_id", "") or "").strip()
    subject = (request.form.get("subject", "") or "").strip()
    new_grade = (request.form.get("grade", "") or "").strip()

    owner = grade_owner(db, grade_id) if valid_id(grade_id) else None
    if not valid_id(grade_id) or not valid_grade(new_grade):
        return teacher_error("Invalid input.", "update_grade validation", owner)
    if subject and not valid_subject(subject):
        return teacher_error("Invalid input.", "update_grade validation", owner)

    try:
        if owner is None:
            return teacher_error("Invalid input.", "update_grade unknown grade")
        db.execute(
            "INSERT INTO grade_change_requests (grade_id, new_grade, requested_by, status) VALUES (?, ?, ?, 'pending')",
            (int(grade_id), int(new_grade), user["username"]),
        )
        if subject:
            db.execute("UPDATE grades SET subject=? WHERE id=?", (subject, int(grade_id)))
        db.commit()
        audit(user["id"], "GRADE_CORRECTION_REQUEST", f"Update request grade_id {grade_id} -> {new_grade} subject {subject}")
    except Exception as e:
        logging.error(f"update_grade failed err={e}")
        return "An error occurred. Please try again.", 500

    return redirect(f"/students/{owner}")


@app.route("/approvals", methods=["GET"])
@require_role("academic_admin")
def approvals():
    try:
        db = get_db()
        reqs = db.execute(
            "SELECT grade_change_requests.*, grades.subject, grades.grade as old_grade, grades.student_id, COALESCE(users.full_name, users.username) as student_name "
            "FROM grade_change_requests JOIN grades ON grade_change_requests.grade_id = grades.id "
            "JOIN users ON grades.student_id = users.id WHERE grade_change_requests.status='pending'"
        ).fetchall()
    except Exception as e:
        logging.error(f"approvals list failed err={e}")
        return "An error occurred. Please try again.", 500
    return render_template("approvals.html", requests=reqs)


@app.route("/approvals/<int:req_id>/approve", methods=["POST"])
@require_role("academic_admin")
def approve(req_id):
    user = current_user()
    if not valid_id(req_id):
        return "Invalid input.", 400
    try:
        db = get_db()
        req = db.execute("SELECT * FROM grade_change_requests WHERE id=?", (int(req_id),)).fetchone()
        if not req:
            return "Request not found", 404
        if req["status"] != "pending":
            return "This correction has already been decided.", 400
        if not valid_grade(req["new_grade"]):
            logging.error(f"approve invalid stored grade req={req_id}")
            return "Invalid input.", 400
        db.execute("UPDATE grades SET grade=? WHERE id=?", (int(req["new_grade"]), int(req["grade_id"])))
        db.execute("UPDATE grade_change_requests SET status='approved', reviewed_by=? WHERE id=?", (user["username"], int(req_id)))
        db.commit()
        audit(user["id"], "GRADE_APPROVED", f"Approved request {req_id} grade {req['grade_id']} -> {req['new_grade']}")
    except Exception as e:
        logging.error(f"approve failed req={req_id} err={e}")
        return "An error occurred. Please try again.", 500
    return redirect("/dashboard")


@app.route("/approvals/<int:req_id>/reject", methods=["POST"])
@require_role("academic_admin")
def reject(req_id):
    user = current_user()
    if not valid_id(req_id):
        return "Invalid input.", 400
    try:
        db = get_db()
        req = db.execute("SELECT status FROM grade_change_requests WHERE id=?", (int(req_id),)).fetchone()
        if not req:
            return "Request not found", 404
        if req["status"] != "pending":
            return "This correction has already been decided.", 400
        db.execute("UPDATE grade_change_requests SET status='rejected', reviewed_by=? WHERE id=?", (user["username"], int(req_id)))
        db.commit()
        audit(user["id"], "GRADE_REJECTED", f"Rejected request {req_id}")
    except Exception as e:
        logging.error(f"reject failed err={e}")
        return "An error occurred. Please try again.", 500
    return redirect("/dashboard")


@app.route("/periods/lock", methods=["POST"])
@require_role("registrar")
def period_lock():
    user = current_user()
    try:
        db = get_db()
        period = db.execute("SELECT * FROM grading_periods LIMIT 1").fetchone()
        if not period:
            return "Invalid input.", 400
        new_status = "locked" if period["status"] == "open" else "open"
        if period["status"] == "locked":
            new_status = "archived" if request.form.get("archive") else "open"
        elif period["status"] == "archived":
            new_status = "open"
        if new_status not in ("open", "locked", "archived"):
            return "Invalid input.", 400
        db.execute("UPDATE grading_periods SET status=? WHERE id=?", (new_status, period["id"]))
        db.commit()
        audit(user["id"], "PERIOD_LOCK", f"Period {period['name']} -> {new_status}")
    except Exception as e:
        logging.error(f"period lock failed err={e}")
        return "An error occurred. Please try again.", 500
    return redirect("/dashboard")


@app.route("/grade-sheet")
@require_role("teacher")
def grade_sheet():
    """The teacher's document: every student against every course, to print for the registrar."""
    try:
        db = get_db()
        roster = class_roster(db)
        courses = course_averages(db)
        matrix = {}
        for s in roster:
            row = {}
            for g in sorted(s["grades"], key=lambda g: g["id"]):
                row[g["subject"]] = g["grade"]   # the latest entry for a course wins
            matrix[s["id"]] = row
        all_marks = [g["grade"] for s in roster for g in s["grades"]]
        return render_template(
            "grade_sheet.html",
            roster=roster,
            courses=courses,
            subjects=[c["subject"] for c in courses],
            matrix=matrix,
            class_average=mean(all_marks),
            prepared=datetime.date.today().strftime("%d %B %Y").lstrip("0"),
        )
    except Exception as e:
        logging.error(f"grade sheet failed err={e}")
        return "An error occurred. Please try again.", 500


@app.route("/transcript")
def transcript():
    if "username" not in session:
        return redirect("/login")
    user = current_user()
    if not user:
        return redirect("/login")
    try:
        db = get_db()
        period = db.execute("SELECT * FROM grading_periods LIMIT 1").fetchone()
        if user["role"] == "student":
            grades = db.execute(
                GRADES_SELECT + " WHERE grades.student_id=?",
                (user["id"],),
            ).fetchall()
            return render_template("transcript.html", grades=grades, student_id=user["id"], period=period, certified=False)

        if user["role"] not in ("registrar", "academic_admin", "teacher"):
            return "Unauthorized", 403

        student_id = (request.args.get("student_id", "") or "").strip()
        if user["role"] == "teacher" and not student_id:
            return redirect("/grade-sheet")
        if student_id:
            if not valid_id(student_id):
                return "Invalid input.", 400
            grades = db.execute(
                GRADES_SELECT + " WHERE grades.student_id=?",
                (int(student_id),),
            ).fetchall()
            certified = user["role"] == "registrar"
            if certified:
                audit(user["id"], "TRANSCRIPT_GENERATE", f"Transcript for student {student_id} period {period['name']}")
            return render_template("transcript.html", grades=grades, student_id=student_id, period=period, certified=certified, single=True)
        grades = db.execute(GRADES_SELECT).fetchall()
        return render_template("transcript.html", grades=grades, student_id=student_id, period=period, certified=False)
    except Exception as e:
        logging.error(f"transcript failed user={user['username']} err={e}")
        return "An error occurred. Please try again.", 500


@app.route("/admin/unlock", methods=["POST"])
@require_role("it_admin")
def admin_unlock():
    user = current_user()
    user_id = (request.form.get("user_id", "") or "").strip()
    if not valid_id(user_id):
        return "Invalid input.", 400
    try:
        db = get_db()
        db.execute("UPDATE users SET is_locked=0, failed_attempts=0 WHERE id=?", (int(user_id),))
        db.commit()
        audit(user["id"], "ACCOUNT_UNLOCK", f"Unlocked user {user_id}")
    except Exception as e:
        logging.error(f"unlock failed err={e}")
        return "An error occurred. Please try again.", 500
    return redirect("/dashboard")


@app.route("/admin/reset", methods=["POST"])
@require_role("it_admin")
def admin_reset():
    user = current_user()
    user_id = (request.form.get("user_id", "") or "").strip()
    new_password = request.form.get("new_password", "") or ""
    if not valid_id(user_id) or not 8 <= len(new_password) <= 128:
        return "Invalid input. Password must be 8 to 128 characters.", 400
    try:
        hashed = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
        db = get_db()
        db.execute("UPDATE users SET password=?, is_locked=0, failed_attempts=0 WHERE id=?", (hashed, int(user_id)))
        db.commit()
        audit(user["id"], "ADMIN_PASSWORD_RESET", f"Reset password for user {user_id}")
    except Exception as e:
        logging.error(f"admin reset failed err={e}")
        return "An error occurred. Please try again.", 500
    return redirect("/dashboard")


@app.route("/view_grades")
def view_grades():
    if "username" not in session:
        return redirect("/login")
    user = current_user()
    if not user:
        return redirect("/login")
    student_id = (request.args.get("student_id", "") or "").strip()
    try:
        db = get_db()
        if student_id:
            if not valid_id(student_id):
                return "Invalid input.", 400
            if user["role"] == "student" and int(student_id) != int(user["id"]):
                logging.error(f"view_grades IDOR blocked user={user['username']} tried={student_id}")
                return "Unauthorized", 403
            grades = db.execute(
                GRADES_SELECT + " WHERE grades.student_id=?",
                (int(student_id),),
            ).fetchall()
        else:
            grades = db.execute(
                GRADES_SELECT + " WHERE grades.student_id=?",
                (user["id"],),
            ).fetchall()
    except Exception as e:
        logging.error(f"view_grades failed err={e}")
        return "An error occurred. Please try again.", 500

    return render_template("view_grades.html", grades=grades, student_id=student_id)


if __name__ == "__main__":
    app.run(debug=False, host="127.0.0.1", port=5001)
