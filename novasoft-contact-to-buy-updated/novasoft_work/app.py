import hmac
import os
import secrets
import time
import zipfile
import threading
import shutil
from urllib.parse import urlsplit
from pathlib import PurePosixPath
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path

from dotenv import load_dotenv
from flask import (
    Flask, abort, flash, jsonify, redirect, render_template, request,
    session, url_for
)
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

app = Flask(__name__, instance_path=str(BASE_DIR / "instance"))
# Fail early rather than silently running with a missing or placeholder session secret.
_secret_key = os.getenv("FLASK_SECRET_KEY", "").strip()
if not _secret_key or _secret_key.lower().startswith("replace-with-"):
    raise RuntimeError("FLASK_SECRET_KEY is missing or still a placeholder. Run make_admin.py or set a strong secret in .env.")
app.config["SECRET_KEY"] = _secret_key
Path(app.instance_path).mkdir(parents=True, exist_ok=True)
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv(
    "DATABASE_URL", f"sqlite:///{(BASE_DIR / 'instance' / 'novasoft.db').as_posix()}"
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["MAX_CONTENT_LENGTH"] = int(os.getenv("MAX_UPLOAD_MB", "500")) * 1024 * 1024
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
_production = os.getenv("APP_ENV", "development").strip().lower() == "production"
app.config["SESSION_COOKIE_SECURE"] = os.getenv("COOKIE_SECURE", "true" if _production else "false").lower() == "true"
if _production and not app.config["SESSION_COOKIE_SECURE"]:
    raise RuntimeError("COOKIE_SECURE must be true in production when HTTPS is enabled.")

STORAGE_DIR = Path(os.getenv("STORAGE_DIR", str(BASE_DIR / "storage"))).resolve()
PRODUCT_DIR = STORAGE_DIR / "products"
PRODUCT_DIR.mkdir(parents=True, exist_ok=True)
ALLOWED_EXTENSIONS = {
    "zip", "7z", "rar", "pdf", "exe", "msi", "msix", "appx",
    "whl", "py", "txt", "md", "png", "jpg", "jpeg", "webp",
    "mp4", "webm", "mov", "mp3", "tar", "gz", "json", "csv", "docx", "xlsx", "pptx"
}
db = SQLAlchemy(app)


def utcnow():
    return datetime.now(timezone.utc)


class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    slug = db.Column(db.String(190), unique=True, nullable=False, index=True)
    description = db.Column(db.Text, nullable=False, default="")
    category = db.Column(db.String(80), nullable=False, default="Software")
    version = db.Column(db.String(40), nullable=False, default="1.0.0")
    price_paise = db.Column(db.Integer, nullable=False, default=0)
    compare_price_paise = db.Column(db.Integer, nullable=False, default=0)
    file_key = db.Column(db.String(255), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    image_url = db.Column(db.String(500), nullable=False, default="")
    published = db.Column(db.Boolean, nullable=False, default=True)
    preview_key = db.Column(db.String(255), nullable=False, default="")
    preview_filename = db.Column(db.String(255), nullable=False, default="")
    preview_type = db.Column(db.String(20), nullable=False, default="")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)



class AdminAccount(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)

class StoreSetting(db.Model):
    key = db.Column(db.String(80), primary_key=True)
    value = db.Column(db.String(500), nullable=False, default="")

def setting(key, fallback=""):
    row = db.session.get(StoreSetting, key)
    return row.value if row else fallback

def set_setting(key, value):
    row = db.session.get(StoreSetting, key)
    if row is None: db.session.add(StoreSetting(key=key, value=value))
    else: row.value = value

def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("is_admin"):
            return redirect(url_for("admin_login", next=request.path))
        return fn(*args, **kwargs)
    return wrapper


def csrf_token():
    token = session.get("_csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf"] = token
    return token


@app.context_processor
def inject_globals():
    return {
        "csrf_token": csrf_token,
        "store_name": os.getenv("STORE_NAME", "NovaSoft"),
        "contact_email": setting("contact_email", os.getenv("CONTACT_EMAIL", "sarinshabadofficial@gmail.com")).strip(),
        "contact_phone": setting("contact_phone", os.getenv("CONTACT_PHONE", "9878654329")).strip(),
    }


@app.before_request
def protect_posts():
    if request.method == "POST":
        submitted = request.form.get("_csrf") or request.headers.get("X-CSRF-Token")
        expected = session.get("_csrf", "")
        if not submitted or not expected or not hmac.compare_digest(submitted, expected):
            abort(400, description="Invalid or missing CSRF token. Refresh the page and try again.")


# Lightweight process-local throttling. Configure a shared proxy/Redis limiter for multi-worker production.
_RATE_LIMITS = {}
_RATE_LIMIT_LOCK = threading.Lock()
_RATE_LIMIT_RULES = {
    "admin_login": (5, 15 * 60),       # 5 attempts per IP+username per 15 minutes
}


@app.before_request
def throttle_sensitive_routes():
    if request.method != "POST" or request.endpoint not in _RATE_LIMIT_RULES:
        return None
    limit, window = _RATE_LIMIT_RULES[request.endpoint]
    identity = request.remote_addr or "unknown"
    if request.endpoint == "admin_login":
        identity += ":" + request.form.get("username", "")[:100]
    key = (request.endpoint, identity)
    now = time.monotonic()
    with _RATE_LIMIT_LOCK:
        attempts = [stamp for stamp in _RATE_LIMITS.get(key, []) if now - stamp < window]
        if len(attempts) >= limit:
            retry_after = max(1, int(window - (now - attempts[0])))
            _RATE_LIMITS[key] = attempts
            response = (jsonify(error="Too many attempts. Please wait before trying again."), 429)
            response[0].headers["Retry-After"] = str(retry_after)
            return response
        attempts.append(now)
        _RATE_LIMITS[key] = attempts
        # Keep the in-memory structure bounded during long-running local deployments.
        if len(_RATE_LIMITS) > 5000:
            for old_key, stamps in list(_RATE_LIMITS.items()):
                kept = [stamp for stamp in stamps if now - stamp < window]
                if kept:
                    _RATE_LIMITS[old_key] = kept
                else:
                    _RATE_LIMITS.pop(old_key, None)
    return None


def safe_local_redirect_target(candidate):
    """Return a safe same-site path or None; reject absolute and protocol-relative URLs."""
    if not candidate or not candidate.startswith("/") or candidate.startswith("//") or "\\" in candidate:
        return None
    parsed = urlsplit(candidate)
    if parsed.scheme or parsed.netloc:
        return None
    return candidate


def money(paise):
    return f"₹{paise / 100:,.2f}"


app.jinja_env.filters["money"] = money


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def save_product_upload(files):
    """Save one allowed file, or package a browser-selected folder into a ZIP.

    Folder inputs should be named ``folder_files`` and use the HTML
    ``webkitdirectory`` attribute. Their relative paths are preserved safely.
    Returns (stored_key, customer_download_filename).
    """
    folder_uploads = [item for item in files.getlist("folder_files") if item and item.filename]
    single_upload = files.get("file")
    if folder_uploads and single_upload and single_upload.filename:
        raise ValueError("Choose either a single file/ZIP or a folder, not both.")
    if folder_uploads:
        if len(folder_uploads) > 10000:
            raise ValueError("The selected folder contains too many files (maximum 10,000).")
        archive_name = secure_filename(request.form.get("name", "software")) or "software"
        original = f"{archive_name}.zip"
        key = f"{secrets.token_hex(24)}.zip"
        archive_path = PRODUCT_DIR / key
        try:
            seen_paths = set()
            with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
                for item in folder_uploads:
                    # Browsers commonly provide relative paths for directory inputs.
                    raw_path = item.filename.replace("\\", "/")
                    parts = [part for part in PurePosixPath(raw_path).parts if part not in ("", ".", "..", "/")]
                    if not parts:
                        continue
                    safe_path = "/".join(secure_filename(part) or "file" for part in parts)
                    if safe_path in seen_paths:
                        raise ValueError("Two folder files have the same safe filename. Rename one and upload again.")
                    seen_paths.add(safe_path)
                    # Stream each file into the archive instead of loading the whole file into RAM.
                    with archive.open(safe_path, "w") as destination:
                        shutil.copyfileobj(item.stream, destination, length=1024 * 1024)
            if not zipfile.is_zipfile(archive_path):
                raise ValueError("Could not create a ZIP from that folder.")
            return key, original
        except Exception:
            archive_path.unlink(missing_ok=True)
            raise

    upload = files.get("file")
    if not upload or not upload.filename:
        raise ValueError("Choose a software file, ZIP archive, or folder from your computer.")
    original = secure_filename(upload.filename) or "download"
    if not allowed_file(original):
        raise ValueError("That file type is not allowed. ZIP archives are supported.")
    key = f"{secrets.token_hex(24)}{Path(original).suffix.lower()}"
    upload.save(PRODUCT_DIR / key)
    return key, original


def save_preview_upload(upload):
    if not upload or not upload.filename: return "", "", ""
    original = secure_filename(upload.filename) or "preview"
    ext = Path(original).suffix.lower()
    if ext not in {".pdf", ".mp4", ".webm", ".mov"}:
        raise ValueError("Preview must be a PDF or video file (PDF, MP4, WEBM, MOV).")
    key = f"preview-{secrets.token_hex(24)}{ext}"
    upload.save(PRODUCT_DIR / key)
    return key, original, ("pdf" if ext == ".pdf" else "video")

def unique_slug(name):
    base = "-".join("".join(c.lower() if c.isalnum() else " " for c in name).split())[:150] or "product"
    slug = base
    while Product.query.filter_by(slug=slug).first():
        slug = f"{base}-{secrets.token_hex(3)}"
    return slug


@app.get("/")
def home():
    products = Product.query.filter_by(published=True).order_by(Product.created_at.desc()).all()
    return render_template("home.html", products=products)


@app.get("/product/<slug>")
def product_detail(slug):
    product = Product.query.filter_by(slug=slug, published=True).first_or_404()
    return render_template("product.html", product=product)


@app.get("/preview/<int:product_id>")
def product_preview(product_id):
    from flask import send_from_directory
    product = Product.query.filter_by(id=product_id, published=True).first_or_404()
    if not product.preview_key: abort(404, description="No preview is available for this product.")
    response = send_from_directory(PRODUCT_DIR, product.preview_key, as_attachment=False, download_name=product.preview_filename)
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response

@app.route("/admin/setup", methods=["GET", "POST"])
def admin_setup():
    if AdminAccount.query.first(): return redirect(url_for("admin_login"))
    if request.method == "POST":
        username=request.form.get("username", "").strip(); password=request.form.get("password", ""); confirm=request.form.get("confirm_password", "")
        email=request.form.get("contact_email", "").strip(); phone=request.form.get("contact_phone", "").strip()
        if len(username)<3 or len(username)>100: flash("Username must be between 3 and 100 characters.", "error")
        elif len(password)<12: flash("Choose a password with at least 12 characters.", "error")
        elif not hmac.compare_digest(password,confirm): flash("The passwords do not match.", "error")
        elif "@" not in email or "." not in email.rsplit("@",1)[-1] or len(email)>254: flash("Enter a valid contact email address.", "error")
        elif not (7<=len("".join(c for c in phone if c.isdigit()))<=15): flash("Enter a valid contact phone number.", "error")
        else:
            db.session.add(AdminAccount(username=username,password_hash=generate_password_hash(password)))
            set_setting("contact_email",email); set_setting("contact_phone",phone); db.session.commit()
            session.clear(); session["is_admin"]=True; session["_csrf"]=secrets.token_urlsafe(32)
            flash("Admin account created successfully.", "success")
            return redirect(url_for("admin_dashboard"))
    return render_template("admin_setup.html")

@app.get("/health")
def health():
    return jsonify(status="ok", app="NovaSoft")


@app.get("/admin")
@admin_required
def admin_dashboard():
    products = Product.query.order_by(Product.created_at.desc()).all()
    return render_template("admin.html", products=products)


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if not AdminAccount.query.first(): return redirect(url_for("admin_setup"))
    if session.get("is_admin"):
        return redirect(url_for("admin_dashboard"))
    if request.method == "POST":
        account = AdminAccount.query.first()
        provided_user = request.form.get("username", "")
        provided_pass = request.form.get("password", "")
        if account and hmac.compare_digest(provided_user, account.username) and check_password_hash(account.password_hash, provided_pass):
            session.clear()
            session["is_admin"] = True
            session["_csrf"] = secrets.token_urlsafe(32)
            target = safe_local_redirect_target(request.args.get("next", ""))
            return redirect(target or url_for("admin_dashboard"))
        flash("Incorrect username or password.", "error")
    return render_template("admin_login.html")


@app.route("/admin/settings", methods=["GET", "POST"])
@admin_required
def admin_settings():
    if request.method == "POST":
        email=request.form.get("contact_email", "").strip(); phone=request.form.get("contact_phone", "").strip()
        if "@" not in email or "." not in email.rsplit("@",1)[-1] or len(email)>254: flash("Enter a valid contact email address.", "error")
        elif not (7<=len("".join(c for c in phone if c.isdigit()))<=15): flash("Enter a valid contact phone number.", "error")
        else:
            set_setting("contact_email",email); set_setting("contact_phone",phone); db.session.commit()
            flash("Contact settings saved.", "success"); return redirect(url_for("admin_settings"))
    return render_template("admin_settings.html")

@app.post("/admin/logout")
@admin_required
def admin_logout():
    session.clear()
    flash("You have been signed out.", "success")
    return redirect(url_for("home"))


@app.route("/admin/products/new", methods=["GET", "POST"])
@admin_required
def product_new():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip()
        category = request.form.get("category", "Software").strip()[:80]
        version = request.form.get("version", "1.0.0").strip()[:40]
        image_url = request.form.get("image_url", "").strip()[:500]
        try:
            price = round(float(request.form.get("price", "0")) * 100)
            compare = round(float(request.form.get("compare_price", "0") or 0) * 100)
        except (ValueError, OverflowError):
            flash("Enter valid prices.", "error")
            return render_template("product_form.html", product=None)
        if not name or not description:
            flash("Name and description are required.", "error")
        elif price < 0 or compare < 0 or price > 100_000_000_00 or compare > 100_000_000_00:
            flash("Price is outside the allowed range.", "error")
        else:
            try:
                preview_key, preview_filename, preview_type = save_preview_upload(request.files.get("preview_file"))
                upload = request.files.get("file")
                has_folder = any(item and item.filename for item in request.files.getlist("folder_files"))
                if (upload and upload.filename) or has_folder:
                    key, original = save_product_upload(request.files)
                elif preview_key:
                    key, original = preview_key, preview_filename
                else:
                    raise ValueError("Add a software file/folder or upload a PDF/video preview.")
            except ValueError as exc:
                flash(str(exc), "error")
                return render_template("product_form.html", product=None)
            except Exception:
                app.logger.exception("Product upload failed")
                flash("The upload could not be processed. Try a smaller folder or ZIP file.", "error")
                return render_template("product_form.html", product=None)
            product = Product(
                name=name[:160], slug=unique_slug(name), description=description,
                category=category or "Software", version=version or "1.0.0",
                price_paise=price, compare_price_paise=compare,
                file_key=key, original_filename=original, image_url=image_url,
                preview_key=preview_key, preview_filename=preview_filename, preview_type=preview_type,
                published=("published" in request.form),
            )
            db.session.add(product)
            db.session.commit()
            flash("Product uploaded successfully.", "success")
            return redirect(url_for("admin_dashboard"))
        return render_template("product_form.html", product=None)
    return render_template("product_form.html", product=None)


@app.route("/admin/products/<int:product_id>/edit", methods=["GET", "POST"])
@admin_required
def product_edit(product_id):
    product = Product.query.get_or_404(product_id)
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip()
        try:
            price = round(float(request.form.get("price", "0")) * 100)
            compare = round(float(request.form.get("compare_price", "0") or 0) * 100)
        except (ValueError, OverflowError):
            flash("Enter valid prices.", "error")
            return render_template("product_form.html", product=product)
        if (not name or not description or price < 0 or compare < 0
                or price > 100_000_000_00 or compare > 100_000_000_00):
            flash("Enter a name, description and valid non-negative prices.", "error")
            return render_template("product_form.html", product=product)
        product.name = name[:160]
        product.description = description
        product.category = request.form.get("category", "Software").strip()[:80] or "Software"
        product.version = request.form.get("version", "1.0.0").strip()[:40] or "1.0.0"
        product.price_paise = price
        product.compare_price_paise = compare
        product.image_url = request.form.get("image_url", "").strip()[:500]
        product.published = "published" in request.form
        has_folder_files = any(item and item.filename for item in request.files.getlist("folder_files"))
        upload = request.files.get("file")
        if has_folder_files or (upload and upload.filename):
            try:
                key, original = save_product_upload(request.files)
            except ValueError as exc:
                flash(str(exc), "error")
                return render_template("product_form.html", product=product)
            except Exception:
                app.logger.exception("Product replacement upload failed")
                flash("The upload could not be processed. Try a smaller folder or ZIP file.", "error")
                return render_template("product_form.html", product=product)
            product.file_key = key
            product.original_filename = original
            # Keep the previous file on disk as a safety measure.
        preview_upload = request.files.get("preview_file")
        if preview_upload and preview_upload.filename:
            try: preview_key, preview_filename, preview_type = save_preview_upload(preview_upload)
            except ValueError as exc:
                flash(str(exc), "error"); return render_template("product_form.html", product=product)
            product.preview_key=preview_key; product.preview_filename=preview_filename; product.preview_type=preview_type
        elif "remove_preview" in request.form:
            product.preview_key=""; product.preview_filename=""; product.preview_type=""
        db.session.commit()
        flash("Product updated.", "success")
        return redirect(url_for("admin_dashboard"))
    return render_template("product_form.html", product=product)


@app.post("/admin/products/<int:product_id>/delete")
@admin_required
def product_delete(product_id):
    product = Product.query.get_or_404(product_id)
    # Unpublish instead of deleting product data and uploaded files.
    product.published = False
    db.session.commit()
    flash("Product unpublished and removed from the storefront.", "success")
    return redirect(url_for("admin_dashboard"))


@app.errorhandler(413)
def upload_too_large(error):
    return render_template("error.html", error=type("UploadTooLarge", (), {"code": 413, "description": "The upload is larger than the configured limit. Choose a smaller file or increase MAX_UPLOAD_MB in the runtime configuration."})()), 413

@app.errorhandler(400)
@app.errorhandler(403)
@app.errorhandler(404)
@app.errorhandler(410)
def friendly_error(error):
    return render_template("error.html", error=error), error.code


with app.app_context():
    db.create_all()
    from sqlalchemy import inspect, text
    columns = {column["name"] for column in inspect(db.engine).get_columns("product")}
    with db.engine.begin() as connection:
        for name, declaration in (("preview_key", "VARCHAR(255) NOT NULL DEFAULT ''"), ("preview_filename", "VARCHAR(255) NOT NULL DEFAULT ''"), ("preview_type", "VARCHAR(20) NOT NULL DEFAULT ''")):
            if name not in columns: connection.execute(text(f"ALTER TABLE product ADD COLUMN {name} {declaration}"))

if __name__ == "__main__":
    # Local development only. Use a production WSGI server in deployment.
    app.run(host="127.0.0.1", port=int(os.getenv("PORT", "5000")), debug=False)
