from flask import Flask, request, redirect, session, render_template, g
import sqlite3
import os

app = Flask(__name__)

app.secret_key = '1234'

app.config['SESSION_COOKIE_HTTPONLY'] = False
app.config['SESSION_COOKIE_SECURE'] = False
app.config['PERMANENT_SESSION_LIFETIME'] = 31536000

DATABASE = os.path.join(os.path.dirname(__file__), "database.db")

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

@app.route("/")
def index():
    if 'username' in session:
        return redirect("/dashboard")
    return redirect("/login")

@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")

        db = get_db()
        query = f"SELECT * FROM users WHERE username = '{username}' AND password = '{password}'"
        try:
            user = db.execute(query).fetchone()
        except Exception as e:
            error = f"Database error: {e} | Query: {query}"
            return render_template("login.html", error=error)

        if user:
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role']
            session.permanent = True
            return redirect("/dashboard")
        else:
            error = "Invalid username or password"

    return render_template("login.html", error=error)

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

@app.route("/dashboard")
def dashboard():
    if 'username' not in session:
        return redirect("/login")

    db = get_db()
    role = session.get('role')
    username = session.get('username')
    user_id = session.get('user_id')

    all_students = db.execute("SELECT id, username FROM users WHERE role='student'").fetchall()

    student_id_param = request.args.get('student_id')

    if role == 'teacher':
        if student_id_param:
            query = f"SELECT grades.*, users.username as student_name FROM grades JOIN users ON grades.student_id = users.id WHERE student_id = {student_id_param}"
            try:
                grades = db.execute(query).fetchall()
            except Exception as e:
                grades = []
                error = f"Query error: {e}"
                return render_template("dashboard.html", role=role, username=username, grades=grades, students=all_students, error=error)
        else:
            grades = db.execute("SELECT grades.*, users.username as student_name FROM grades JOIN users ON grades.student_id = users.id").fetchall()
        return render_template("dashboard.html", role=role, username=username, grades=grades, students=all_students)

    else:
        if student_id_param:
            query = f"SELECT grades.*, users.username as student_name FROM grades JOIN users ON grades.student_id = users.id WHERE student_id = {student_id_param}"
            try:
                grades = db.execute(query).fetchall()
            except Exception as e:
                grades = []
                error = f"Query error: {e}"
                return render_template("dashboard.html", role=role, username=username, grades=grades, students=all_students, error=error)
        else:
            grades = db.execute("SELECT grades.*, users.username as student_name FROM grades JOIN users ON grades.student_id = users.id WHERE student_id = ?", (user_id,)).fetchall()
        return render_template("dashboard.html", role=role, username=username, grades=grades, students=all_students)

@app.route("/add_grade", methods=["POST"])
def add_grade():
    if 'username' not in session:
        return redirect("/login")

    if session.get('role') != 'teacher':
        return "Unauthorized: Only teachers can add grades", 403

    student_id = request.form.get("student_id", "")
    subject = request.form.get("subject", "")
    grade = request.form.get("grade", "")

    db = get_db()
    query = f"INSERT INTO grades (student_id, subject, grade, updated_by) VALUES ({student_id}, '{subject}', {grade}, '{session.get('username')}')"
    try:
        db.execute(query)
        db.commit()
    except Exception as e:
        return f"Error: {e} | Query: {query}", 500

    return redirect("/dashboard")

@app.route("/update_grade", methods=["POST"])
def update_grade():
    if 'username' not in session:
        return redirect("/login")

    if session.get('role') != 'teacher':
        return "Unauthorized: Only teachers can update grades", 403

    grade_id = request.form.get("grade_id", "")
    student_id = request.form.get("student_id", "")
    subject = request.form.get("subject", "")
    grade = request.form.get("grade", "")

    db = get_db()
    query = f"UPDATE grades SET student_id={student_id}, subject='{subject}', grade={grade}, updated_by='{session.get('username')}' WHERE id={grade_id}"
    try:
        db.execute(query)
        db.commit()
    except Exception as e:
        return f"Error: {e} | Query: {query}", 500

    return redirect("/dashboard")

@app.route("/view_grades")
def view_grades():
    if 'username' not in session:
        return redirect("/login")

    student_id = request.args.get("student_id", "")
    db = get_db()

    if student_id:
        query = f"SELECT grades.*, users.username as student_name FROM grades JOIN users ON grades.student_id = users.id WHERE student_id = {student_id}"
    else:
        query = f"SELECT grades.*, users.username as student_name FROM grades JOIN users ON grades.student_id = users.id WHERE student_id = {session.get('user_id')}"

    try:
        grades = db.execute(query).fetchall()
    except Exception as e:
        return f"Query error: {e} | Query: {query}", 500

    return render_template("view_grades.html", grades=grades, student_id=student_id)

if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5001)
