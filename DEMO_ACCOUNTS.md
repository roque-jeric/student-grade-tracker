# Demo Accounts

Fictional demo accounts for **Aldermere College**. All 17 accounts are seeded from `init_db.py` / `sample_data.py` and use the password **`pass123`**. Passwords are bcrypt-hashed in `database.db`; no plaintext password is stored there.

> **Test data only.** These are not real credentials. If any account's password is changed via the IT Admin reset, `pass123` will no longer work for that account.

## Login details

| # | Username | Password | Role | Full name | Student no. |
|---|----------|----------|------|-----------|-------------|
| 1 | `teacher1` | `pass123` | teacher | Prof. Elena Marsh | — |
| 2 | `student1` | `pass123` | student | Maya Santos | 2024-01482 |
| 3 | `student2` | `pass123` | student | Daniel Reyes | 2024-01507 |
| 4 | `academic_admin1` | `pass123` | academic_admin | Dr. Samuel Okafor | — |
| 5 | `registrar1` | `pass123` | registrar | Grace Lindqvist | — |
| 6 | `it_admin1` | `pass123` | it_admin | Rafael Domingo | — |
| 7 | `it_admin2` | `pass123` | it_admin | Nadia Flores | — |
| 8 | `student3` | `pass123` | student | Ana Villanueva | 2024-01533 |
| 9 | `student4` | `pass123` | student | Joshua Lim | 2024-01541 |
| 10 | `student5` | `pass123` | student | Priya Nair | 2024-01566 |
| 11 | `student6` | `pass123` | student | Marco Bautista | 2024-01578 |
| 12 | `student7` | `pass123` | student | Hannah Cruz | 2024-01592 |
| 13 | `student8` | `pass123` | student | Luis Mendoza | 2024-01610 |
| 14 | `student9` | `pass123` | student | Sofia Aquino | 2024-01634 |
| 15 | `student10` | `pass123` | student | Noah Tan | 2024-01651 |
| 16 | `student11` | `pass123` | student | Bea Ramos | 2024-01669 |
| 17 | `student12` | `pass123` | student | Ethan Dela Cruz | 2024-01688 |

## Access summary

- **17 accounts total** (12 students, 1 teacher, 1 academic admin, 1 registrar, 2 IT admins).
- There is no registration page, so the account count is fixed at 17.
- All 17 were unlocked with `failed_attempts = 0` when this file was generated.
- Login is limited only by the lockout rule: **5 failed attempts locks the account** until either IT admin (`it_admin1` or `it_admin2`) unlocks it.
- Concurrent logins are not capped by the app — each browser gets its own 30-minute session cookie, so multiple accounts can be signed in at the same time.
- Either IT admin can reset a password from the dashboard; the new password must be 8–128 characters.
- The two IT admins are each other's recovery path: if one is locked, the other can unlock it.

## Roles and demo flows

| Account | What it can do |
|---------|----------------|
| `teacher1` | View the student roster, open student grades, add grades, request corrections, print the grade sheet |
| `student1`–`student12` | View only their own dashboard, grades, and transcript |
| `academic_admin1` | Approve or reject pending grade corrections |
| `registrar1` | Lock final grades, produce certified transcripts |
| `it_admin1` / `it_admin2` | Unlock locked accounts, reset passwords, and unlock each other |
