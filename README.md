# Student Grade Tracker — Secured Version

5 roles, Prelim single period, secured per hardening requirements. Fresh DB with bcrypt hashes.

## Roles (6 users seeded, password pass123 hashed with bcrypt+salt)
| Username | Role |
|----------|------|
| teacher1 | teacher |
| student1 | student |
| student2 | student |
| academic_admin1 | academic_admin |
| registrar1 | registrar |
| it_admin1 | it_admin |

Single period: `Prelim` (open/locked/archived) - registrar locks all grades at once.

## Security Fixes Applied
- Password hashing + salting with bcrypt (`init_db.py`, `app.py` login + admin reset). No plaintext storage.
- Strong random secret key (`secrets.token_hex(32)`), `HttpOnly=True`, `SameSite=Lax`, 30-min session. `Secure=False` for localhost demo only.
- Parameterized SQL (`?`) everywhere + input validation (username 3-32 alnum, subject 1-50, grade 0-100 int, ids >0).
- Students only own records: `?student_id` mismatch returns 403 (`dashboard`, `view_grades`, `transcript`).
- Generic errors to users, details in `app.log` (private). `debug=False`.
- Strict server-side role verification: `current_user()` reloads DB each request + `@require_role` on teacher/admin/registrar/it_admin functions.
- Account lock: 5 fails -> locked (applies to all roles including it_admin).
- XSS fix: removed `| safe` from all templates (autoescape).

## Setup
```powershell
pip install -r requirements.txt
python init_db.py
python app.py
# http://127.0.0.1:5001
```

## Demo Flows
1. **Lockout:** student1 wrong 5x -> locked -> it_admin1 dashboard Unlock
2. **Teacher Add:** teacher1 Add Grade 95 ok, 999 rejected 400, `'; DROP` rejected 400
3. **Correction:** teacher edit -> pending -> academic_admin Approve stays on /dashboard
4. **IDOR blocked:** student1 `/dashboard?student_id=3` -> 403
5. **SQLi blocked:** `' OR '1'='1' -- ` -> Invalid, no Dashboard
6. **Registrar Lock:** Prelim locked -> teacher Add stays on dashboard with error
7. **Transcript:** registrar `/transcript?student_id=2` certified table (no cert number)
8. **IT Admin:** dashboard unlock/reset (reset needs 8+ chars, bcrypt hashed)

## Project Structure
```
app.py (secured), schema.sql, init_db.py (bcrypt), database.db (fresh)
templates/login, dashboard (5 roles), view_grades, approvals, transcript
static/style.css (beginner plain), requirements.txt, app.log (private errors)
```
