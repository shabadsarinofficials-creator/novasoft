# NovaSoft — Contact-to-buy software store

NovaSoft is a Flask website for showing software products and managing the catalogue from a private admin panel. Customers can preview a PDF or video, then contact you directly to arrange purchase. This version does not take online payments and contains no Razorpay integration.

## Start on Windows

1. Extract the ZIP to a normal folder.
2. Install Python 3.11 or newer and select **Add Python to PATH** during installation.
3. Double-click `run.bat`. It creates a virtual environment, installs dependencies, prepares local runtime configuration, and opens the admin setup/login page.
4. On first launch, create your admin username and a password of at least 12 characters in the browser. No admin username or password is stored in `.env`.
5. The default contact details are `9878654329` and `sarinshabadofficial@gmail.com`. They can be changed later in Admin → Edit contact details.

The first-time setup page is available only until the first admin account is created. After that, `/admin/setup` redirects to login.

## Products and previews

- In Admin → Add product, enter the name, description, category, version, and listed price.
- Upload a PDF or video (MP4, WEBM, MOV) in **Customer preview**. It is displayed inline on the public product page.
- You may also attach the actual software file or upload a folder packaged as ZIP. A preview alone is enough to create a product.
- Customers see email and phone contact options below the preview. The site does not process payments or automatically deliver paid software.
- Product edits allow replacing or removing a preview. Products can be published or unpublished.

## Settings and data

- Contact details are managed in the admin panel and stored in the local SQLite database.
- `.env` contains runtime-only settings such as the Flask session secret, database location and upload limit. Keep it private.
- The SQLite database is stored in `instance/novasoft.db`; uploaded content is stored in `storage/products/`.
- The application performs a small additive migration for preview fields when opening an existing database. Back up your project folder before upgrading.

## Troubleshooting

- If `run.bat` reports that Python is missing, install Python 3.11+ and reopen Command Prompt.
- If dependency installation fails, check your internet connection and run `run.bat` again.
- If an upload is rejected, use a supported PDF/video type and keep the total request under the configured `MAX_UPLOAD_MB` limit.
- `/health` returns a simple application status for local checks.

## Security notes

`run.bat` binds the development server to `127.0.0.1`, so it is local to this computer. Before publishing publicly, deploy with a production WSGI server and HTTPS, configure secure cookies, back up the database and uploaded files, and scan uploads. Never publish `.env`, the database, or admin credentials.
