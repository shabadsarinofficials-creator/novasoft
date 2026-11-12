# BizSuite Cloud MySQL Setup (Render + Aiven)

This package adds a hosted MySQL connection path while preserving local SQLite for local development. Never place database credentials inside the Electron app or commit them to Git.

## 1. Push the project to a private GitHub repository

1. Create a new **private** GitHub repository.
2. Upload/push the contents of this project folder to the repository root. Keep `render.yaml` at the root.
3. Do not upload `backend/bizsuite.db`, `.env`, `.jwt.secret`, `jwt.secret`, uploaded files, or any credentials. The included `.gitignore` excludes the local database and secrets.

## 2. Get the Aiven MySQL connection URL and CA certificate

In Aiven, open the running MySQL service and copy its connection URL. It should contain the hostname, port, database name, username and password. Treat this URL as a password.

Download the service's CA certificate from the Aiven connection/SSL section (often named `ca.pem`). On Windows PowerShell, convert the file to one-line Base64. Replace the example path with the actual certificate path:

```powershell
[Convert]::ToBase64String([IO.File]::ReadAllBytes("$HOME\Downloads\ca.pem"))
```

Copy the single-line output privately; do not paste it into public code or chat.

## 3. Deploy to Render

1. Sign in to Render and choose **New + → Blueprint** (or create a Web Service from the repository).
2. Connect the repository containing `render.yaml`.
3. Set the environment variables when prompted:
   - `DATABASE_URL`: the Aiven MySQL connection URL.
   - `MYSQL_SSL_CA_BASE64`: the Base64 CA certificate string from step 2.
   - `JWT_SECRET`: use Render's generated value or a unique random secret of at least 32 characters.
   - `ADMIN_EMAIL`: the email address for the initial BizSuite Admin account.
   - `ADMIN_PASSWORD`: a unique password of 12-72 UTF-8 bytes. Save it securely.
4. Deploy. Wait for the service to report Live.
5. Test `https://YOUR-SERVICE.onrender.com/openapi.json` in a browser. It should display the API schema. Do not share your secret environment values.

The first successful start creates the tables and initial Admin account in MySQL. Keep the same `JWT_SECRET` after deployment; changing it invalidates existing login tokens.

## 4. Point desktop apps to the hosted API

Open each installed BizSuite app's server configuration and enter the Render HTTPS base URL, for example `https://bizsuite-api.onrender.com` (use your actual service URL). Do not add `/openapi.json` or a trailing endpoint path. Sign in with the Admin credentials created in Render. Configure the Manager and Employee apps to use the same URL.

## Important limitations before real company use

- Render's free web service may sleep when idle and take time to wake up. Free hosting is best for a prototype, not uptime-critical operations.
- The current task attachments and employee submission files are saved to the backend's local `uploads` directory. A free host's filesystem may be ephemeral, so files can disappear after redeploy/restart. Task metadata is stored in MySQL, but file uploads need durable object storage or a persistent disk before relying on them.
- The existing local SQLite database is not automatically migrated to MySQL. The first cloud start creates a fresh database. Migrate existing users/tasks separately before using the cloud version; do not delete your old local database.
- The existing automatic backup endpoint supports SQLite only. Set up database-provider backups/exports for MySQL and test restoring them.
- Never expose MySQL directly to desktop apps. Apps must call the HTTPS API only.
- Restrict Aiven access according to its network/access-control settings, use SSL, and keep credentials private.
