# BizSuite by NovaSoft

Complete business management platform — **one process, one URL**.

**Stack:** Python · FastAPI · PostgreSQL · SQLAlchemy 2 · Alembic · HTML/CSS/JS  
**Deploy:** Render (built-in uvicorn — no separate Node/nginx server)

The FastAPI app serves **both** the REST API and the HTML frontend from the same service.

---

## Features

| Module | Capability |
|--------|------------|
| **Auth** | Login, JWT, password change/reset, role-based access |
| **Roles** | Administrator · Manager · Employee (enforced on backend) |
| **Dashboard** | Live stats from the database |
| **Tasks** | Full lifecycle, priorities, assignees, comments, filters |
| **Projects** | Members, managers, status tracking |
| **Team** | Directory, create/deactivate users (admin) |
| **Chat** | Direct conversations, message history |
| **Announcements** | Workspace / role-targeted posts |
| **Files** | Upload/download with type & size validation |
| **Audit** | Action log for admins |
| **Settings** | Workspace configuration |
| **Migration** | Safe legacy DB inspection & import tooling |

---

## Deploy on Render (recommended)

### Option A — Blueprint (easiest)

1. Push this folder to a **GitHub** repo.
2. Render → **New** → **Blueprint** → select the repo.
3. Render reads `render.yaml` and creates:
   - **Web service** `bizsuite` (Python, runs `bash start.sh`)
   - **PostgreSQL** `bizsuite-db`
4. Set **ADMIN_PASSWORD** when prompted (do not leave the default).
5. Deploy. Open the service URL → login.

`start.sh` runs migrations, then starts the **built-in** uvicorn server.  
No extra frontend host. Health check: `/health`.

### Option B — Manual Web Service

1. **New → Web Service** from your GitHub repo.
2. **Runtime:** Python 3  
3. **Build command:** `pip install -r requirements.txt`  
4. **Start command:** `bash start.sh`  
5. **Health check path:** `/health`  
6. Create **PostgreSQL** and link it (sets `DATABASE_URL`).  
7. Env vars:

| Key | Value |
|-----|--------|
| `SECRET_KEY` | long random string (or auto-generate) |
| `ADMIN_EMAIL` | your admin email |
| `ADMIN_PASSWORD` | strong password |
| `APP_ENV` | `production` |
| `CORS_ORIGINS` | `*` |

Root directory = repo root (where `start.sh` and `backend/` live).

---

## How the “built-in server” works

```
Browser  →  https://your-app.onrender.com
                │
                ├── /api/*          REST API (FastAPI)
                ├── /health         Health check
                ├── /login          HTML login
                ├── /dashboard      HTML app shell
                ├── /pages/*        HTML modules
                └── /static/*       CSS + JS
```

One **uvicorn** process (started by `start.sh`) handles everything.  
You do **not** need nginx, Node, or a second Render service.

---

## Local quick start

```bash
cd BizSuite
python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env
# Edit DATABASE_URL, SECRET_KEY, ADMIN_*

# Need a local PostgreSQL database named bizsuite
alembic upgrade head
# Or use the same entrypoint as Render:
bash start.sh
# Default: http://127.0.0.1:8000
```

API docs: `/docs` · Health: `/health`

Default admin is created on first start **only if no admin exists**.

---

## Legacy data recovery

If an old BizSuite database still exists:

```bash
export LEGACY_DATABASE_URL=postgresql://...   # read-only source
export DATABASE_URL=postgresql://...          # new target (different DB)

python scripts/inspect_legacy_db.py
alembic upgrade head
python scripts/migrate_legacy.py
python scripts/verify_migration.py
```

Source is never modified. Review `migration_report_*.json` before going live.

---

## Project structure

```
BizSuite/
├── start.sh             # Render entrypoint (migrate + uvicorn)
├── render.yaml          # Blueprint: web + Postgres
├── Procfile             # web: bash start.sh
├── runtime.txt          # Python 3.12
├── requirements.txt
├── alembic.ini
├── backend/             # FastAPI app, models, routes, migrations
├── frontend/            # HTML + CSS + JS (served by FastAPI)
├── scripts/             # legacy inspect / migrate / verify
└── uploads/             # local file storage
```

---

## Notes

- **Free Render** services sleep when idle; first request after sleep can take ~30–60s.
- **Disk is ephemeral** on free web services. For permanent uploads, add a Render **persistent disk** mounted at `uploads`, or use S3-compatible storage later.
- Change the bootstrap admin password immediately after first login.
- Never commit a real `.env` file.
