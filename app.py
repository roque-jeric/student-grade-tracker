from flask import Flask, request, redirect, session, render_template, g
import sqlite3
import os
import re
import secrets
import logging
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
    all_students = db.execute("SELECT id, username FROM users WHERE role='student'").fetchall()
    all_users = db.execute("SELECT id, username, role, is_locked, failed_attempts FROM users").fetchall()
    period = db.execute("SELECT * FROM grading_periods LIMIT 1").fetchone()
    pending_requests = db.execute(
        "SELECT grade_change_requests.*, grades.subject, grades.grade as old_grade, users.username as student_name "
        "FROM grade_change_requests JOIN grades ON grade_change_requests.grade_id = grades.id "
        "JOIN users ON grades.student_id = users.id WHERE grade_change_requests.status='pending'"
    ).fetchall()
    audit_logs = db.execute(
        "SELECT audit_logs.*, users.username FROM audit_logs LEFT JOIN users ON audit_logs.user_id = users.id "
        "ORDER BY audit_logs.id DESC LIMIT 20"
    ).fetchall()
    return all_students, all_users, period, pending_requests, audit_logs


def teacher_error(user, db, period, message="Invalid input.", log_label="teacher input"):
    try:
        all_students, all_users, dash_period, pending_requests, audit_logs = dashboard_data()
        grades = db.execute("SELECT grades.*, users.username as student_name FROM grades JOIN users ON grades.student_id = users.id").fetchall()
    except Exception as e:
        logging.error(f"{log_label} dashboard render failed err={e}")
        return "An error occurred. Please try again.", 500
    use_period = period if period is not None else dash_period
    return render_template("dashboard.html", role=user["role"], username=user["username"], grades=grades, students=all_students, all_users=all_users, period=use_period, pending_requests=pending_requests, audit_logs=audit_logs, error=message), 400


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
                return render_template("dashboard.html", role=role, username=username, grades=[], students=all_students, all_users=all_users, period=period, pending_requests=pending_requests, audit_logs=audit_logs, error="Invalid input.")
            try:
                grades = get_db().execute(
                    "SELECT grades.*, users.username as student_name FROM grades JOIN users ON grades.student_id = users.id WHERE student_id=?",
                    (int(student_id_param),),
                ).fetchall()
            except Exception as e:
                logging.error(f"teacher filter failed user={username} err={e}")
                return render_template("dashboard.html", role=role, username=username, grades=[], students=all_students, all_users=all_users, period=period, pending_requests=pending_requests, audit_logs=audit_logs, error="An error occurred. Please try again.")
        else:
            try:
                grades = get_db().execute("SELECT grades.*, users.username as student_name FROM grades JOIN users ON grades.student_id = users.id").fetchall()
            except Exception as e:
                logging.error(f"teacher list failed err={e}")
                return render_template("dashboard.html", role=role, username=username, grades=[], students=all_students, all_users=all_users, period=period, pending_requests=pending_requests, audit_logs=audit_logs, error="An error occurred. Please try again.")
        return render_template("dashboard.html", role=role, username=username, grades=grades, students=all_students, all_users=all_users, period=period, pending_requests=pending_requests, audit_logs=audit_logs)

    elif role == "academic_admin":
        if student_id_param:
            if not valid_id(student_id_param):
                return render_template("dashboard.html", role=role, username=username, grades=[], students=all_students, all_users=all_users, period=period, pending_requests=pending_requests, audit_logs=audit_logs, error="Invalid input.")
            try:
                grades = get_db().execute(
                    "SELECT grades.*, users.username as student_name FROM grades JOIN users ON grades.student_id = users.id WHERE student_id=?",
                    (int(student_id_param),),
                ).fetchall()
            except Exception as e:
                logging.error(f"admin filter failed err={e}")
                return render_template("dashboard.html", role=role, username=username, grades=[], students=all_students, all_users=all_users, period=period, pending_requests=pending_requests, audit_logs=audit_logs, error="An error occurred. Please try again.")
        else:
            grades = get_db().execute("SELECT grades.*, users.username as student_name FROM grades JOIN users ON grades.student_id = users.id").fetchall()
        return render_template("dashboard.html", role=role, username=username, grades=grades, students=all_students, all_users=all_users, period=period, pending_requests=pending_requests, audit_logs=audit_logs)

    elif role == "registrar":
        if student_id_param:
            if not valid_id(student_id_param):
                return render_template("dashboard.html", role=role, username=username, grades=[], students=all_students, all_users=all_users, period=period, pending_requests=pending_requests, audit_logs=audit_logs, error="Invalid input.")
            try:
                grades = get_db().execute(
                    "SELECT grades.*, users.username as student_name FROM grades JOIN users ON grades.student_id = users.id WHERE student_id=?",
                    (int(student_id_param),),
                ).fetchall()
            except Exception as e:
                logging.error(f"registrar filter failed err={e}")
                return render_template("dashboard.html", role=role, username=username, grades=[], students=all_students, all_users=all_users, period=period, pending_requests=pending_requests, audit_logs=audit_logs, error="An error occurred. Please try again.")
        else:
            grades = get_db().execute("SELECT grades.*, users.username as student_name FROM grades JOIN users ON grades.student_id = users.id").fetchall()
        return render_template("dashboard.html", role=role, username=username, grades=grades, students=all_students, all_users=all_users, period=period, pending_requests=pending_requests, audit_logs=audit_logs)

    elif role == "it_admin":
        grades = get_db().execute("SELECT grades.*, users.username as student_name FROM grades JOIN users ON grades.student_id = users.id").fetchall()
        return render_template("dashboard.html", role=role, username=username, grades=grades, students=all_students, all_users=all_users, period=period, pending_requests=pending_requests, audit_logs=audit_logs)

    else:
        if student_id_param:
            if not valid_id(student_id_param) or int(student_id_param) != int(user_id):
                logging.error(f"student IDOR blocked user={username} tried={student_id_param}")
                return "Unauthorized", 403
        try:
            grades = get_db().execute(
                "SELECT grades.*, users.username as student_name FROM grades JOIN users ON grades.student_id = users.id WHERE student_id=?",
                (user_id,),
            ).fetchall()
        except Exception as e:
            logging.error(f"student list failed err={e}")
            return render_template("dashboard.html", role=role, username=username, grades=[], students=[], all_users=all_users, period=period, pending_requests=pending_requests, audit_logs=audit_logs, error="An error occurred. Please try again.")
        return render_template("dashboard.html", role=role, username=username, grades=grades, students=[], all_users=all_users, period=period, pending_requests=pending_requests, audit_logs=audit_logs)


@app.route("/add_grade", methods=["POST"])
@require_role("teacher")
def add_grade():
    user = current_user()
    db = get_db()
    period = db.execute("SELECT * FROM grading_periods LIMIT 1").fetchone()
    if period and period["status"] != "open":
        try:
            all_students, all_users, _, pending_requests, audit_logs = dashboard_data()
            grades = db.execute("SELECT grades.*, users.username as student_name FROM grades JOIN users ON grades.student_id = users.id").fetchall()
        except Exception as e:
            logging.error(f"locked dashboard render failed err={e}")
            return "An error occurred. Please try again.", 500
        return render_template("dashboard.html", role=user["role"], username=user["username"], grades=grades, students=all_students, all_users=all_users, period=period, pending_requests=pending_requests, audit_logs=audit_logs, error=f"Grading period {period['status']}, cannot add grades")

    student_id = (request.form.get("student_id", "") or "").strip()
    subject = (request.form.get("subject", "") or "").strip()
    grade = (request.form.get("grade", "") or "").strip()

    if not valid_id(student_id) or not valid_subject(subject) or not valid_grade(grade):
        return teacher_error(user, db, period, "Invalid input.", "add_grade validation")

    try:
        target = db.execute("SELECT id FROM users WHERE id=? AND role='student'", (int(student_id),)).fetchone()
        if not target:
            return teacher_error(user, db, period, "Invalid input.", "add_grade unknown student")
        db.execute(
            "INSERT INTO grades (student_id, subject, grade, updated_by) VALUES (?, ?, ?, ?)",
            (int(student_id), subject, int(grade), user["username"]),
        )
        db.commit()
        audit(user["id"], "GRADE_ADD", f"Added grade {grade} for student {student_id} subject {subject}")
    except Exception as e:
        logging.error(f"add_grade failed user={user['username']} err={e}")
        return "An error occurred. Please try again.", 500

    return redirect("/dashboard")


@app.route("/request-correction", methods=["POST"])
@require_role("teacher")
def request_correction():
    user = current_user()
    db = get_db()
    grade_id = (request.form.get("grade_id", "") or "").strip()
    new_grade = (request.form.get("new_grade", "") or "").strip()

    if not valid_id(grade_id) or not valid_grade(new_grade):
        return teacher_error(user, db, None, "Invalid input.", "request-correction validation")

    try:
        exists = db.execute("SELECT id FROM grades WHERE id=?", (int(grade_id),)).fetchone()
        if not exists:
            return teacher_error(user, db, None, "Invalid input.", "request-correction unknown grade")
        db.execute(
            "INSERT INTO grade_change_requests (grade_id, new_grade, requested_by, status) VALUES (?, ?, ?, 'pending')",
            (int(grade_id), int(new_grade), user["username"]),
        )
        db.commit()
        audit(user["id"], "GRADE_CORRECTION_REQUEST", f"Requested correction grade_id {grade_id} -> {new_grade}")
    except Exception as e:
        logging.error(f"request-correction failed err={e}")
        return "An error occurred. Please try again.", 500

    return redirect("/dashboard")


@app.route("/update_grade", methods=["POST"])
@require_role("teacher")
def update_grade():
    user = current_user()
    db = get_db()
    grade_id = (request.form.get("grade_id", "") or "").strip()
    subject = (request.form.get("subject", "") or "").strip()
    new_grade = (request.form.get("grade", "") or "").strip()

    if not valid_id(grade_id) or not valid_grade(new_grade):
        return teacher_error(user, db, None, "Invalid input.", "update_grade validation")
    if subject and not valid_subject(subject):
        return teacher_error(user, db, None, "Invalid input.", "update_grade validation")

    try:
        exists = db.execute("SELECT id FROM grades WHERE id=?", (int(grade_id),)).fetchone()
        if not exists:
            return teacher_error(user, db, None, "Invalid input.", "update_grade unknown grade")
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

    return redirect("/dashboard")


@app.route("/approvals", methods=["GET"])
@require_role("academic_admin")
def approvals():
    try:
        db = get_db()
        reqs = db.execute(
            "SELECT grade_change_requests.*, grades.subject, grades.grade as old_grade, grades.student_id, users.username as student_name "
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
                "SELECT grades.*, users.username as student_name FROM grades JOIN users ON grades.student_id = users.id WHERE student_id=?",
                (user["id"],),
            ).fetchall()
            return render_template("transcript.html", grades=grades, student_id=user["id"], period=period, certified=False)

        if user["role"] not in ("registrar", "academic_admin", "teacher"):
            return "Unauthorized", 403

        student_id = (request.args.get("student_id", "") or "").strip()
        if student_id:
            if not valid_id(student_id):
                return "Invalid input.", 400
            grades = db.execute(
                "SELECT grades.*, users.username as student_name FROM grades JOIN users ON grades.student_id = users.id WHERE student_id=?",
                (int(student_id),),
            ).fetchall()
            audit(user["id"], "TRANSCRIPT_GENERATE", f"Transcript for student {student_id} period {period['name']}")
            return render_template("transcript.html", grades=grades, student_id=student_id, period=period, certified=True)
        grades = db.execute("SELECT grades.*, users.username as student_name FROM grades JOIN users ON grades.student_id = users.id").fetchall()
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
    if not valid_id(user_id) or len(new_password) > 128:
        return "Invalid input. Password must be below 128 chars.", 400
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
                "SELECT grades.*, users.username as student_name FROM grades JOIN users ON grades.student_id = users.id WHERE student_id=?",
                (int(student_id),),
            ).fetchall()
        else:
            grades = db.execute(
                "SELECT grades.*, users.username as student_name FROM grades JOIN users ON grades.student_id = users.id WHERE student_id=?",
                (user["id"],),
            ).fetchall()
    except Exception as e:
        logging.error(f"view_grades failed err={e}")
        return "An error occurred. Please try again.", 500

    return render_template("view_grades.html", grades=grades, student_id=student_id)


if __name__ == "__main__":
    app.run(debug=False, host="127.0.0.1", port=5001)
