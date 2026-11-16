# UniClear — Digital University Student Clearance System

Flask + SQLite starter for the QR-code-enabled university student clearance project.

## Included in this first milestone
- Student registration and login/logout.
- Secure password hashing.
- Role-aware dashboards for student, officer, administrator, and verifier.
- Database models for departments, users, clearance requests, departmental clearance items, and audit logs.
- CLI commands to initialize the database and create the first administrator.
- Bootstrap-based responsive interface.

The actual clearance submission/review workflow, admin user management, PDF certificates, QR generation, and verification endpoint are subsequent milestones.

## Setup on Windows PowerShell

```powershell
cd path\to\qr_clearance_system
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
flask --app run.py init-db
flask --app run.py create-admin
python run.py
```

If activation is blocked in PowerShell, run:
```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

Open http://127.0.0.1:5000.

## First test
1. Sign in using the administrator account you created.
2. Log out and register a student account.
3. Sign in as the student and confirm the student dashboard appears.

## Development security
The default secret key is for local development only. Set a strong `SECRET_KEY` environment variable before deployment. Do not use Flask's development server in production.
