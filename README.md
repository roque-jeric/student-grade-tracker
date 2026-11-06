# Student Grade Tracker — Secured Version

Branded for Aldermere College, a fictional institution. Its name lives at the top of `templates/_ui.html`.

5 roles, one Final grading period, secured per hardening requirements. Fresh DB with bcrypt hashes.

## Roles (17 users seeded, password pass123 hashed with bcrypt+salt)
| Username | Role |
|----------|------|
| teacher1 | teacher |
| student1 to student12 | student |
| academic_admin1 | academic_admin |
| registrar1 | registrar |
| it_admin1 | it_admin |
| it_admin2 | it_admin |

`it_admin2` is a second IT admin, so one admin can unlock the other if an account gets locked.

Single period: `Final` (open/locked/archived). The grades on record are final grades; the registrar locks them all at once.

## Security Fixes Applied
- Password hashing + salting with bcrypt (`init_db.py`, `app.py` login + admin reset). No plaintext storage.
- Strong random secret key (`secrets.token_hex(32)`), `HttpOnly=True`, `SameSite=Lax`, 30-min session. `Secure=False` for localhost demo only.
- Parameterized SQL (`?`) everywhere + input validation (username 3-32 alnum, subject 1-50, grade 0-100 int, ids >0).
- Students only own records: `?student_id` mismatch returns 403 (`dashboard`, `view_grades`, `transcript`).
- Generic errors to users, details in `app.log` (private). `debug=False`.
- Strict server-side role verification: `current_user()` reloads DB each request + `@require_role` on teacher/admin/registrar/it_admin functions.
- Account lock: 5 fails -> locked (applies to all roles including it_admin).
- XSS fix: removed `| safe` from all templates (autoescape).
- CSRF: every POST form carries a per-session token, checked with `secrets.compare_digest`; a missing or wrong token is refused with 400.
- Only the registrar can produce a certified transcript; teachers and the academic admin get a working copy.
- Password reset length (8 to 128) is enforced on the server.
- A correction can be approved or rejected only while it is pending.

## Setup
```powershell
pip install -r requirements.txt
python init_db.py   # new install only: this deletes database.db and recreates it
python app.py
# http://127.0.0.1:5001
```

To upgrade an existing `database.db` without losing anything, run `python migrate_db.py` once instead of `init_db.py`. It saves a copy to `database.db.bak`, then adds the profile columns and the sample class. The names, student numbers and programmes in `sample_data.py` are invented.

## Settings to replace
- IT office phone, email, building and hours (`IT_OFFICE` at the top of `templates/_ui.html`) are sample details.
- The pass mark is `PASS_MARK = 75` in `app.py`.

## Demo Flows
1. **Lockout:** student1 wrong 5x -> locked -> either IT admin (`it_admin1` or `it_admin2`) unlocks it
2. **Forgot password:** Login -> Forgot password? -> IT office phone, email and room. Either IT admin finds the student by name or number and resets it
3. **Teacher roster:** teacher1 lands on all students. Click a student to see their grades per course
4. **Teacher Add:** on a student, Add grade 95 ok, 999 rejected 400, `'; DROP` rejected 400
5. **Correction:** teacher Correct on a course -> pending -> academic_admin Approve stays on /dashboard
6. **IDOR blocked:** student1 `/dashboard?student_id=3` -> 403, `/students/3` -> 403
7. **SQLi blocked:** `' OR '1'='1' -- ` -> Invalid, no Dashboard
8. **Registrar Lock:** Final grades locked -> Add grade is hidden and a direct post is refused on the student page
9. **Transcript:** registrar `/transcript?student_id=2` certified table (no cert number). Teachers print a grade sheet (`/grade-sheet`) instead
10. **IT Admin:** dashboard role cards -> **View accounts** -> unlock/reset (reset needs 8+ chars, bcrypt hashed)
11. **Admin recovery:** lock `it_admin1` with 5 wrong passwords -> log in as `it_admin2` -> Accounts -> IT admins -> unlock `it_admin1`

## Project Structure
```
app.py (secured), schema.sql, init_db.py (bcrypt), migrate_db.py, sample_data.py, database.db
templates/base (masthead and tabs), auth_base (login layout), _ui (macros, college and IT office details)
templates/login, forgot_password, students (teacher roster), student_detail (grades per course), grade_sheet (teacher's class record), dashboard (role home), accounts (IT admin role pages), view_grades, approvals, transcript
static/style.css, static/app.js (menu, dialogs, roster search and sort, print), static/fonts (self-hosted Source Sans 3 and EB Garamond, OFL licences)
static/img (Rembrandt, A Scholar in His Study, c. 1652, Art Institute of Chicago, CC0)
requirements.txt, app.log (private errors)
```
