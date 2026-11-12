# BizSuite

BizSuite is a local-first company workspace with an Admin desktop window, a role-aware Manager/Employee workspace, a FastAPI backend, and one shared SQLite database. The backend can use PostgreSQL through `DATABASE_URL` when deployed.

## Included features

- Admin, manager, and employee sign-in using hashed passwords and expiring JWT sessions.
- Managers assign tasks with priorities and deadlines, attach reference files and links, send direct messages/team announcements/meeting notices, request message acknowledgements, manage employee accounts, and review submissions.
- The Task Center includes task search and filters, deadline/overdue indicators, status updates, per-task comments, task history, URL/ZIP submissions, version history, feedback, approval, and resubmission.
- Employees see their own assignments, submit project URLs or ZIP files, update status, acknowledge requested messages, and receive task/message notifications.
- Calendar and reports summarize deadlines, meetings, task status, overdue work, and employee workload. Admin can search company data, export task reports, and download a backup ZIP containing the SQLite database and uploaded work files.
- Admin has read-only work/message oversight; work assignment and message APIs are manager-only. Role permissions are enforced by the backend, not only by the interface.
- People: create, search, paginate, deactivate, remove, change a role, and reset passwords.
- Roles and resource access grants, optionally restricted by allowed IP/CIDR networks.
- Data: create and delete JSON records in each resource. Authorized employees can read records through the Employee app; the API checks the role and network on every request.
- Import employees from CSV, TSV, XLSX/XLS, or JSON with column mapping, duplicate checks, preview, and a one-time password CSV export.
- Audit log for important admin operations and access-denied events.
- A launcher that creates a Python virtual environment, installs dependencies, creates a JWT secret, prompts for the first admin credentials, and starts the API plus both desktop apps.

## Windows development quick start

1. Install **Python 3.12** from <https://www.python.org/downloads/> and enable **Add Python to PATH**.
2. Install **Node.js LTS** from <https://nodejs.org/>. Close and reopen the terminal after installation.
3. Extract this entire folder somewhere writable.
4. For development only, double-click `run.bat`. The first run needs an internet connection to install Python and Electron dependencies. It asks for the initial admin email and password.
5. Sign into **BizSuite Admin**. Under **Roles & Access**, create a resource such as `Sales`, and grant the `employee` role access. Under **Data**, add JSON records. Create a `manager` role account under **People** (or change an existing account role to `manager`). Sign into **BizSuite Workspace** with that account to assign work and send messages. Employees sign into the same workspace to receive tasks and submit work. The Admin **Work overview** is read-only.

`run.bat` is a development launcher and keeps the API in a minimized console window. For installed day-to-day desktop use and multi-PC setup, follow `DESKTOP_INSTALL_AND_UPDATES.txt`. The shared server stores its database at `backend\bizsuite.db` and secret at `backend\jwt.secret`.

## Run the API separately (development)

From the `backend` folder, create a virtual environment and install dependencies:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
$env:ADMIN_EMAIL = "admin@example.com"
$env:ADMIN_PASSWORD = "Use-A-Strong-Password"
$env:JWT_SECRET = (python -c "import secrets; print(secrets.token_hex(32))")
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

Then, in another terminal, install and start either desktop UI:

```powershell
cd admin-app
npm install
npm start
```

For the employee UI, use `employee-app` instead. API documentation is available at <http://127.0.0.1:8000/docs> while the backend is running.

## Data and permissions model

A **resource** represents a dataset or feature. A **grant** connects a role to a resource. Blank CIDRs allow access from any client IP; otherwise use comma-separated ranges such as `192.168.1.0/24`. Access is enforced in the API, not just hidden in the desktop UI. The Manager/Employee workspace refreshes assigned tasks, messages, notifications, calendar entries, and reports from the API. Managers can upload task attachments and employees can submit ZIP archives (up to 50 MB) or project URLs. Task discussions are saved in the same database and visible only to the manager workspace and the employee assigned to that task. The API blocks unauthorized task changes and prevents Admin from using manager-only task creation or messaging endpoints. The Employee app rechecks its resource list when Home / Refresh access is selected, and the API blocks revoked access immediately. The **Data** tab stores each record as a JSON object. This provides working starter data storage; it does not automatically connect to an external database, payroll system, or arbitrary spreadsheet.

For PostgreSQL, set a URL such as `postgresql+psycopg://user:password@host:5432/bizsuite` in `DATABASE_URL` before starting the backend. Back up the database and secret before upgrading or moving an installation.

## Security and production notes

This package is a runnable starter, not a security-audited production deployment. Before exposing it to a network or real employee data:

- Use HTTPS behind a correctly configured reverse proxy, restrict CORS to the intended frontend origins, and set a long random `JWT_SECRET`.
- Set `ADMIN_CIDRS` to restrict administrator requests when suitable; only enable `TRUST_PROXY=1` behind a trusted proxy that overwrites forwarding headers.
- Add a forced password change, password recovery policy, optional MFA/SSO, and centralized rate limiting if needed.
- Configure database backups, migrations (for example Alembic), logs, monitoring, and load tests. Rate limiting in this starter is process-local.
- Keep `backend\jwt.secret` and the database private. The temporary password CSV downloaded after an import contains credentials; deliver them securely and delete that file.

The `npm run build` commands in each desktop-app folder produce an Electron installer shell. A distributed installer still needs the backend packaged or deployed and its API URL configured for the target environment; the local development launcher is the ready-to-run path included here.

## Upgrading an existing BizSuite installation safely

1. Close both desktop windows and the minimized API window.
2. Copy the entire existing BizSuite folder as a backup.
3. Extract the new release to a separate folder. Do not extract over a running installation.
4. Copy the existing `backend\bizsuite.db` and `backend\jwt.secret` into the new release's `backend` folder. Do not copy old `main.py` or the old app HTML files over the new files.
5. Run the new `run.bat`. The API creates the new history, notification, acknowledgement, and submission-version tables and adds the new message fields to an existing SQLite database automatically.
6. Sign in and test with a dummy task and test employee before using real company work.

The Admin **Reports & backup** page can download a ZIP containing a consistent SQLite database snapshot and uploaded files. Store this archive securely; it contains company data. The current automatic backup endpoint supports SQLite, which is the default local installation.


## Professional desktop installers and shared sync

For Windows installers with a branded icon and desktop/Start Menu shortcuts, run `build-windows-installers.bat` on Windows with Node.js LTS installed. See `DESKTOP_INSTALL_AND_UPDATES.txt` for release and update-feed setup.

For multiple PCs to share tasks and submissions, host one API/database on a trusted office PC with `run-shared-server.bat`, then run `configure-server.bat` on each client and enter the server URL. The desktop apps poll the shared API for new task/message/notification data while visible. Do not expose the sample HTTP API directly to the public internet.


## Professional desktop v1.2.0

Packaged apps open from Windows shortcuts and taskbar icons; they do not need `run.bat` for everyday client use. The first launch opens a connection setup window, and later the server can be changed from **File → Configure server connection**. On the chosen host PC, complete `run-shared-server.bat` once, then run `install-server-autostart.bat` to register a hidden Windows logon task. See `DESKTOP_INSTALL_AND_UPDATES.txt` for the full steps. Work data synchronizes through the shared API. Automatic software-version delivery is separate and remains inactive until a real release feed is configured.


## Role-specific automatic setup (v1.3.0)

Use one of these launchers instead of the old `run.bat` for the normal desktop workflow:

- `run_admin.bat`: checks/prepares the Python backend, installs dependencies, performs first administrator setup if needed, starts the shared API in the background, registers server auto-start when possible, builds/installs BizSuite Admin, then opens it. This computer should be the shared-server host.
- `run_manager.bat`: builds/installs BizSuite Manager once, then opens the installed app. First launch asks for the shared server URL. Sign in with a Manager account.
- `run_employee.bat`: builds/installs BizSuite Employee once, then opens the installed app. First launch asks for the shared server URL. Sign in with an Employee account.

The Manager and Employee apps use separate desktop identities but the same backend and permission enforcement. On first use, the launchers download Node.js LTS if needed and a private Python 3.12 runtime if no Python 3.12 is installed. They run checks and keep logs in `backend\server.log` for the server. A working internet connection and enough disk space are needed for first setup. Do not extract a new version over a running folder. Keep `backend\bizsuite.db`, `backend\jwt.secret`, and `backend\uploads` when upgrading an existing company server.

The Electron installer build sets `signAndEditExecutable` to false to avoid the Windows `winCodeSign` symbolic-link extraction failure seen on some Windows configurations. Automatic software updates remain disabled until a real release feed is configured; shared task/message data synchronization works through the common API.


## Cloud hosting (Aiven MySQL + Render)

See `CLOUD_MYSQL_SETUP.md` for the cloud deployment procedure. The backend uses local SQLite by default for desktop/local development; hosted MySQL requires `DATABASE_URL` and `MYSQL_SSL_CA_BASE64` environment variables.
