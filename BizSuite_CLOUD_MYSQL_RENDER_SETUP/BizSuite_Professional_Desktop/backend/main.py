"""BizSuite backend: auth, RBAC + network rules, people, import, audit. Run: uvicorn main:app"""
import os, io, re, json, ipaddress, secrets, datetime as dt, sqlite3, zipfile, tempfile, shutil
import bcrypt, jwt, pandas as pd
from fastapi import FastAPI, Depends, HTTPException, Request, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import create_engine, String, ForeignKey, DateTime, Boolean, Text, LargeBinary, Integer, select, or_, delete
from sqlalchemy.dialects.mysql import LONGBLOB
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from fastapi.responses import JSONResponse, Response
import logging
log = logging.getLogger("bizsuite")
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, Session, sessionmaker

def configure_database():
    """Configure local SQLite or hosted MySQL/PostgreSQL using environment variables."""
    raw_url = os.getenv("DATABASE_URL", "sqlite:///bizsuite.db").strip()
    try:
        url = make_url(raw_url)
    except Exception as exc:
        raise RuntimeError("DATABASE_URL is invalid. Copy the connection URL from your database provider.") from exc

    connect_args = {}
    if url.drivername in ("mysql", "mysql+pymysql"):
        if url.drivername == "mysql":
            url = url.set(drivername="mysql+pymysql")
        # Aiven's connection URL often includes ssl-mode=REQUIRED, which PyMySQL does not
        # consume as a driver option. TLS is configured explicitly below.
        query = dict(url.query)
        query.pop("ssl-mode", None)
        query.pop("ssl_mode", None)
        url = url.set(query=query)
        ca_b64 = os.getenv("MYSQL_SSL_CA_BASE64", "").strip()
        if not ca_b64:
            raise RuntimeError("MYSQL_SSL_CA_BASE64 is required for hosted MySQL. Download your provider's CA certificate, base64-encode it, and set this environment variable.")
        import base64
        ca_path = os.path.join(tempfile.gettempdir(), "bizsuite-mysql-ca.pem")
        try:
            ca_bytes = base64.b64decode(ca_b64, validate=True)
            if b"BEGIN CERTIFICATE" not in ca_bytes:
                raise ValueError("CA certificate does not look like a PEM certificate")
            with open(ca_path, "wb") as ca_file:
                ca_file.write(ca_bytes)
        except Exception as exc:
            raise RuntimeError("MYSQL_SSL_CA_BASE64 is not valid base64-encoded PEM certificate data.") from exc
        connect_args = {"ssl": {"ca": ca_path}, "ssl_verify_cert": True, "ssl_verify_identity": True}
    elif url.drivername.startswith("postgres"):
        # Render/Postgres-compatible deployments can still use the existing psycopg driver.
        connect_args = {"sslmode": "require"} if os.getenv("DATABASE_SSL_REQUIRE", "").lower() == "true" else {}

    if url.drivername.startswith("sqlite"):
        return create_engine(url)
    return create_engine(url, pool_pre_ping=True, pool_recycle=280, pool_size=5, max_overflow=5, connect_args=connect_args)

engine = configure_database()

def load_jwt_secret():
    configured = os.getenv("JWT_SECRET")
    if configured:
        if len(configured) < 32:
            raise RuntimeError("JWT_SECRET must be at least 32 characters long.")
        return configured
    # Safe local default for direct development starts. The launcher supplies its own jwt.secret.
    path = os.path.join(os.path.dirname(__file__), ".jwt.secret")
    try:
        with open(path, "r", encoding="utf-8") as f:
            value = f.read().strip()
        if len(value) >= 32: return value
    except FileNotFoundError:
        pass
    value = secrets.token_hex(32)
    try:
        with open(path, "x", encoding="utf-8") as f: f.write(value)
    except FileExistsError:
        with open(path, "r", encoding="utf-8") as f: value = f.read().strip()
    if len(value) < 32: raise RuntimeError("Could not create a valid JWT secret file.")
    return value

SECRET = load_jwt_secret()
ADMIN_CIDRS = os.getenv("ADMIN_CIDRS", "")                      # e.g. "10.0.0.0/8,192.168.1.0/24"; empty = anywhere
SESSION_HOURS = 8
Session_ = sessionmaker(engine, expire_on_commit=False)
now = lambda: dt.datetime.now(dt.timezone.utc)

class Base(DeclarativeBase): pass
class Role(Base):
    __tablename__ = "roles"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    department: Mapped[str] = mapped_column(String(120), default="")
    pw_hash: Mapped[str] = mapped_column(String(100))
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)
class Resource(Base):          # a database, dataset or feature people can be given
    __tablename__ = "resources"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    description: Mapped[str] = mapped_column(String(400), default="")
class ResourceRecord(Base):
    """JSON record stored inside a resource/dataset."""
    __tablename__ = "resource_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    resource_id: Mapped[int] = mapped_column(ForeignKey("resources.id"), index=True)
    data_json: Mapped[str] = mapped_column(Text)
    created: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)

class Grant(Base):             # role -> resource, optionally limited to networks
    __tablename__ = "grants"
    id: Mapped[int] = mapped_column(primary_key=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"), index=True)
    resource_id: Mapped[int] = mapped_column(ForeignKey("resources.id"), index=True)
    cidrs: Mapped[str] = mapped_column(Text, default="")      # comma list; empty = any network
class WorkTask(Base):
    __tablename__ = "work_tasks"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(240))
    description: Mapped[str] = mapped_column(Text, default="")
    priority: Mapped[str] = mapped_column(String(20), default="normal")
    deadline: Mapped[str] = mapped_column(String(40), default="")
    status: Mapped[str] = mapped_column(String(30), default="assigned")
    assignee_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    manager_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    reference_url: Mapped[str] = mapped_column(String(2000), default="")
    attachment_name: Mapped[str] = mapped_column(String(255), default="")
    attachment_path: Mapped[str] = mapped_column(String(1000), default="")
    submission_url: Mapped[str] = mapped_column(String(2000), default="")
    submission_path: Mapped[str] = mapped_column(String(1000), default="")
    submission_name: Mapped[str] = mapped_column(String(255), default="")
    submission_note: Mapped[str] = mapped_column(Text, default="")
    feedback: Mapped[str] = mapped_column(Text, default="")
    created: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)
class WorkMessage(Base):
    __tablename__ = "work_messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    sender_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    recipient_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(240), default="Message")
    body: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(30), default="message")
    ack_required: Mapped[bool] = mapped_column(Boolean, default=False)
    meeting_at: Mapped[str] = mapped_column(String(40), default="")
    created: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)
class TaskComment(Base):
    __tablename__ = "task_comments"
    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("work_tasks.id"), index=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    body: Mapped[str] = mapped_column(Text)
    created: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)
class TaskHistory(Base):
    __tablename__ = "task_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("work_tasks.id"), index=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    action: Mapped[str] = mapped_column(String(80))
    detail: Mapped[str] = mapped_column(Text, default="")
    created: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
class SubmissionVersion(Base):
    __tablename__ = "submission_versions"
    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("work_tasks.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    version: Mapped[int] = mapped_column()
    submission_url: Mapped[str] = mapped_column(String(2000), default="")
    file_name: Mapped[str] = mapped_column(String(255), default="")
    file_path: Mapped[str] = mapped_column(String(1000), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    created: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)
class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(240))
    body: Mapped[str] = mapped_column(Text, default="")
    kind: Mapped[str] = mapped_column(String(40), default="update")
    task_id: Mapped[int | None] = mapped_column(ForeignKey("work_tasks.id"), nullable=True, index=True)
    message_id: Mapped[int | None] = mapped_column(ForeignKey("work_messages.id"), nullable=True, index=True)
    read_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
class MessageAcknowledgement(Base):
    __tablename__ = "message_acknowledgements"
    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("work_messages.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    acknowledged_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)

class Audit(Base):
    __tablename__ = "audit"
    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    actor: Mapped[str] = mapped_column(String(255)); action: Mapped[str] = mapped_column(String(80))
    detail: Mapped[str] = mapped_column(Text, default=""); ip: Mapped[str] = mapped_column(String(64), default="")

app = FastAPI(title="BizSuite API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])  # desktop apps; tighten if web-hosted

@app.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
def root(): return {"service": "BizSuite API", "status": "ok", "docs": "/docs"}

@app.exception_handler(SQLAlchemyError)
async def database_error(request: Request, exc: SQLAlchemyError):
    log.exception("Database error on %s %s", request.method, request.url.path)
    detail = "That change conflicts with other saved data." if isinstance(exc, IntegrityError) else "The database could not save this. Please try again."
    return JSONResponse(status_code=409 if isinstance(exc, IntegrityError) else 500, content={"detail": detail})

def db():
    with Session_() as s: yield s
def ip_of(r: Request): return (r.headers.get("x-forwarded-for", "").split(",")[0].strip() if os.getenv("TRUST_PROXY") else r.client.host)
def in_net(cidrs: str, ip: str):
    nets = [c.strip() for c in cidrs.split(",") if c.strip()]
    return not nets or any(ipaddress.ip_address(ip) in ipaddress.ip_network(n, strict=False) for n in nets)
def hash_pw(p): return bcrypt.hashpw(p.encode(), bcrypt.gensalt()).decode()
def audit(s, actor, action, detail, r): s.add(Audit(actor=actor, action=action, detail=detail, ip=ip_of(r))); s.commit()
def notify(s: Session, user_id: int, title: str, body: str = "", kind: str = "update", task_id: int | None = None, message_id: int | None = None):
    s.add(Notification(user_id=user_id, title=title[:240], body=body[:10000], kind=kind, task_id=task_id, message_id=message_id))
def history(s: Session, task_id: int, actor_id: int, action: str, detail: str = ""):
    s.add(TaskHistory(task_id=task_id, actor_id=actor_id, action=action[:80], detail=detail[:10000]))

def current(r: Request, s: Session = Depends(db)) -> User:
    tok = r.headers.get("authorization", "").removeprefix("Bearer ")
    try: uid = jwt.decode(tok, SECRET, algorithms=["HS256"])["sub"]
    except jwt.PyJWTError: raise HTTPException(401, "Session expired. Sign in again.")
    u = s.get(User, int(uid))
    if not u or not u.active: raise HTTPException(401, "Account disabled.")
    return u
def admin(r: Request, u: User = Depends(current), s: Session = Depends(db)) -> User:
    if s.get(Role, u.role_id).name != "admin": raise HTTPException(403, "Admin only.")
    if not in_net(ADMIN_CIDRS, ip_of(r)): raise HTTPException(403, "Admin panel is not available from this network.")
    return u

@app.on_event("startup")
def boot():
    Base.metadata.create_all(engine)   # use Alembic migrations in production (see README)
    # Small, backward-compatible SQLite migration for existing installations.
    try:
        columns = {c["name"] for c in __import__("sqlalchemy").inspect(engine).get_columns("work_messages")}
        with engine.begin() as conn:
            if "ack_required" not in columns:
                conn.execute(__import__("sqlalchemy").text("ALTER TABLE work_messages ADD COLUMN ack_required BOOLEAN NOT NULL DEFAULT FALSE"))
            if "meeting_at" not in columns:
                conn.execute(__import__("sqlalchemy").text("ALTER TABLE work_messages ADD COLUMN meeting_at VARCHAR(40) NOT NULL DEFAULT ''"))
    except Exception as exc:
        raise RuntimeError(f"Could not upgrade BizSuite database schema: {exc}") from exc
    with Session_() as s:
        admin_role = s.scalar(select(Role).where(Role.name == "admin"))
        employee_role = s.scalar(select(Role).where(Role.name == "employee"))
        manager_role = s.scalar(select(Role).where(Role.name == "manager"))
        if not admin_role: admin_role = Role(name="admin"); s.add(admin_role)
        if not employee_role: s.add(Role(name="employee"))
        if not manager_role: s.add(Role(name="manager"))
        s.flush()
        admin_user = s.scalar(select(User).join(Role, User.role_id == Role.id).where(Role.name == "admin"))
        if not admin_user:
            email = os.getenv("ADMIN_EMAIL", "").strip().lower()
            password = os.getenv("ADMIN_PASSWORD", "")
            if not EMAIL.match(email): raise RuntimeError("Set a valid ADMIN_EMAIL before first startup.")
            if len(password) < 12: raise RuntimeError("Set ADMIN_PASSWORD to at least 12 characters before first startup.")
            if len(password.encode("utf-8")) > 72: raise RuntimeError("ADMIN_PASSWORD must be 72 bytes or fewer.")
            if s.scalar(select(User).where(User.email == email)):
                raise RuntimeError("ADMIN_EMAIL is already assigned to a non-admin account.")
            s.add(User(email=email, name="Administrator", pw_hash=hash_pw(password), role_id=admin_role.id))
        s.commit()

# ---------- auth ----------
class Login(BaseModel): email: str; password: str
FAILS: dict = {}
@app.post("/auth/login")
def login(b: Login, r: Request, s: Session = Depends(db)):
    email = b.email.strip().lower()
    k = (email, ip_of(r)); n, t = FAILS.get(k, (0, now()))
    if n >= 5 and (now() - t).seconds < 300: raise HTTPException(429, "Too many attempts. Try again in 5 minutes.")
    u = s.scalar(select(User).where(User.email == email))
    valid_password = False
    if u and u.active and len(b.password.encode("utf-8")) <= 72:
        try: valid_password = bcrypt.checkpw(b.password.encode(), u.pw_hash.encode())
        except (ValueError, TypeError): valid_password = False
    if not valid_password:
        FAILS[k] = (n + 1, now()); audit(s, b.email, "login_failed", "", r); raise HTTPException(401, "Wrong email or password.")
    FAILS.pop(k, None); role = s.get(Role, u.role_id).name
    tok = jwt.encode({"sub": str(u.id), "exp": now() + dt.timedelta(hours=SESSION_HOURS)}, SECRET, "HS256")
    return {"token": tok, "name": u.name, "role": role}

# ---------- employee API: access decided HERE, per request, from role + network ----------
def allowed(s, u, ip):
    rows = s.execute(select(Resource, Grant).join(Grant, Grant.resource_id == Resource.id).where(Grant.role_id == u.role_id)).all()
    return [x for x, g in rows if in_net(g.cidrs, ip)]
@app.get("/me/resources")
def my_resources(r: Request, u: User = Depends(current), s: Session = Depends(db)):
    return [{"id": x.id, "name": x.name, "description": x.description} for x in allowed(s, u, ip_of(r))]
@app.get("/resources/{name}/data")
def resource_data(name: str, r: Request, u: User = Depends(current), s: Session = Depends(db)):
    resource = next((x for x in allowed(s, u, ip_of(r)) if x.name == name), None)
    if not resource:
        audit(s, u.email, "denied", name, r)
        raise HTTPException(403, "You don't have access to this from your current network.")
    records = s.scalars(select(ResourceRecord).where(ResourceRecord.resource_id == resource.id).order_by(ResourceRecord.id.desc()).limit(1000))
    return {"resource": resource.name, "rows": [{"record_id": x.id, "data": json.loads(x.data_json)} for x in records]}

class RecordIn(BaseModel):
    data: dict

@app.get("/admin/resources/{resource_id}/records")
def admin_records(resource_id: int, a=Depends(admin), s: Session = Depends(db)):
    if not s.get(Resource, resource_id): raise HTTPException(404, "Resource not found.")
    rows = s.scalars(select(ResourceRecord).where(ResourceRecord.resource_id == resource_id).order_by(ResourceRecord.id.desc()).limit(1000))
    return [{"id": x.id, "data": json.loads(x.data_json), "created": x.created.isoformat()} for x in rows]

@app.post("/admin/resources/{resource_id}/records")
def add_record(resource_id: int, b: RecordIn, r: Request, a=Depends(admin), s: Session = Depends(db)):
    if not s.get(Resource, resource_id): raise HTTPException(404, "Resource not found.")
    if not b.data: raise HTTPException(422, "Record must be a non-empty JSON object.")
    row = ResourceRecord(resource_id=resource_id, data_json=json.dumps(b.data, ensure_ascii=False))
    s.add(row); s.commit(); s.refresh(row)
    audit(s, a.email, "record_add", f"resource={resource_id}; record={row.id}", r)
    return {"id": row.id, "data": b.data, "created": row.created.isoformat()}

@app.delete("/admin/resources/{resource_id}/records/{record_id}")
def delete_record(resource_id: int, record_id: int, r: Request, a=Depends(admin), s: Session = Depends(db)):
    row = s.scalar(select(ResourceRecord).where(ResourceRecord.id == record_id, ResourceRecord.resource_id == resource_id))
    if not row: raise HTTPException(404, "Record not found.")
    s.delete(row); s.commit(); audit(s, a.email, "record_delete", f"resource={resource_id}; record={record_id}", r)
    return {"ok": True}

# ---------- admin: people ----------
class NewUser(BaseModel): email: str; name: str; department: str = ""; role_id: int; password: str | None = None
class EditUser(BaseModel): email: str | None = None; name: str | None = None; department: str | None = None; role_id: int | None = None; active: bool | None = None; password: str | None = None
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
@app.get("/admin/users")
def users(q: str = "", page: int = 0, size: int = 50, a=Depends(admin), s: Session = Depends(db)):
    page = max(0, min(page, 100000)); size = max(1, min(size, 200))
    st = select(User).order_by(User.name).offset(page * size).limit(size)
    if q: st = st.where(or_(User.name.ilike(f"%{q}%"), User.email.ilike(f"%{q}%"), User.department.ilike(f"%{q}%")))
    return [{"id": u.id, "email": u.email, "name": u.name, "department": u.department, "role_id": u.role_id, "active": u.active, "created": u.created.isoformat() if u.created else ""} for u in s.scalars(st)]
@app.post("/admin/users")
def add_user(b: NewUser, r: Request, a=Depends(admin), s: Session = Depends(db)):
    b.email = b.email.strip().lower()
    if not EMAIL.match(b.email): raise HTTPException(422, "Invalid email.")
    if not b.name.strip(): raise HTTPException(422, "Name is required.")
    if not s.get(Role, b.role_id): raise HTTPException(422, "Choose a valid role.")
    if s.scalar(select(User).where(User.email == b.email)): raise HTTPException(409, "Email already exists.")
    pw = b.password or secrets.token_urlsafe(9)
    if len(pw.encode("utf-8")) > 72: raise HTTPException(422, "Password must be 72 bytes or fewer.")
    s.add(User(email=b.email.lower(), name=b.name, department=b.department, role_id=b.role_id, pw_hash=hash_pw(pw))); s.commit()
    audit(s, a.email, "user_add", b.email, r); return {"temp_password": pw}
@app.post("/admin/users/{uid}/reset-password")
def reset_password(uid: int, r: Request, a=Depends(admin), s: Session = Depends(db)):
    u = s.get(User, uid)
    if not u: raise HTTPException(404, "Not found")
    pw = secrets.token_urlsafe(12)
    u.pw_hash = hash_pw(pw); s.commit()
    audit(s, a.email, "password_reset", u.email, r)
    return {"temp_password": pw}

@app.patch("/admin/users/{uid}")
def edit_user(uid: int, b: EditUser, r: Request, a=Depends(admin), s: Session = Depends(db)):
    u = s.get(User, uid)
    if not u: raise HTTPException(404, "Not found")
    changes = b.model_dump(exclude_none=True)
    if "role_id" in changes and not s.get(Role, changes["role_id"]): raise HTTPException(422, "Choose a valid role.")
    if "name" in changes:
        changes["name"] = changes["name"].strip()
        if not changes["name"]: raise HTTPException(422, "Name cannot be blank.")
    if "password" in changes and len(changes["password"].encode("utf-8")) > 72: raise HTTPException(422, "Password must be 72 bytes or fewer.")
    if "password" in changes and len(changes["password"]) < 8: raise HTTPException(422, "Password must be at least 8 characters.")
    if "email" in changes:
        changes["email"] = changes["email"].strip().lower()
        if not EMAIL.match(changes["email"]): raise HTTPException(422, "Invalid email.")
        other = s.scalar(select(User).where(User.email == changes["email"], User.id != u.id))
        if other: raise HTTPException(409, "Another person already uses that email.")
    if u.id == a.id and changes.get("active") is False: raise HTTPException(400, "You cannot deactivate your own account.")
    for k, v in changes.items():
        if k == "password": u.pw_hash = hash_pw(v)
        else: setattr(u, k, v)
    s.commit(); audit(s, a.email, "user_edit", f"{u.email} {b.model_dump(exclude={'password'}, exclude_none=True)}", r); return {"ok": True}
def purge_user(s: Session, u: User) -> list:
    """Delete a user AND everything that points at them (the database has foreign keys, so the
    user row cannot be removed while tasks, messages, comments, etc. still reference it).
    Returns uploaded file paths to delete after commit. Raises 409 if the user manages work for others."""
    uid = u.id
    role = s.get(Role, u.role_id)
    if s.scalar(select(WorkTask.id).where(WorkTask.manager_id == uid).limit(1)) is not None:
        raise HTTPException(409, "This person manages tasks assigned to others. Reassign or delete those tasks first, or deactivate the person instead.")
    if (role is None or role.name != "employee") and s.scalar(select(WorkMessage.id).where(WorkMessage.sender_id == uid).limit(1)) is not None:
        raise HTTPException(409, "This person has sent company messages. Deactivate them instead of deleting.")
    files = []
    task_ids = list(s.scalars(select(WorkTask.id).where(WorkTask.assignee_id == uid)))
    if task_ids:
        for t in s.scalars(select(WorkTask).where(WorkTask.id.in_(task_ids))): files += [t.attachment_path, t.submission_path]
        files += list(s.scalars(select(SubmissionVersion.file_path).where(SubmissionVersion.task_id.in_(task_ids))))
        for m in (Notification, SubmissionVersion, TaskHistory, TaskComment):
            s.execute(delete(m).where(m.task_id.in_(task_ids)))
        s.execute(delete(WorkTask).where(WorkTask.id.in_(task_ids)))
    msg_ids = list(s.scalars(select(WorkMessage.id).where(or_(WorkMessage.sender_id == uid, WorkMessage.recipient_id == uid))))
    if msg_ids:
        s.execute(delete(Notification).where(Notification.message_id.in_(msg_ids)))
        s.execute(delete(MessageAcknowledgement).where(MessageAcknowledgement.message_id.in_(msg_ids)))
        s.execute(delete(WorkMessage).where(WorkMessage.id.in_(msg_ids)))
    files += list(s.scalars(select(SubmissionVersion.file_path).where(SubmissionVersion.user_id == uid)))
    s.execute(delete(ChatMessage).where(or_(ChatMessage.sender_id == uid, ChatMessage.recipient_id == uid)))
    s.execute(delete(Notification).where(Notification.user_id == uid))
    s.execute(delete(MessageAcknowledgement).where(MessageAcknowledgement.user_id == uid))
    s.execute(delete(TaskComment).where(TaskComment.author_id == uid))
    s.execute(delete(TaskHistory).where(TaskHistory.actor_id == uid))
    s.execute(delete(SubmissionVersion).where(SubmissionVersion.user_id == uid))
    s.delete(u)
    s.flush()
    return files

@app.delete("/admin/users/{uid}")
def del_user(uid: int, r: Request, a=Depends(admin), s: Session = Depends(db)):
    u = s.get(User, uid)
    if not u or u.id == a.id: raise HTTPException(400, "Can't delete this user.")
    email = u.email
    files = purge_user(s, u)
    s.commit()
    for f in files:                       # remove uploaded files from disk (best effort)
        try:
            if f and os.path.isfile(f): os.remove(f)
        except OSError: pass
    audit(s, a.email, "user_delete", email, r); return {"ok": True}

# ---------- admin: roles, resources, grants (+ network rules) ----------
class Named(BaseModel): name: str; description: str = ""
class GrantIn(BaseModel): role_id: int; resource_id: int; cidrs: str = ""
@app.get("/admin/roles")
def roles(a=Depends(admin), s: Session = Depends(db)): return [{"id": x.id, "name": x.name} for x in s.scalars(select(Role))]
@app.post("/admin/roles")
def add_role(b: Named, r: Request, a=Depends(admin), s: Session = Depends(db)):
    name = b.name.strip()
    if not name: raise HTTPException(422, "Role name is required.")
    if s.scalar(select(Role).where(Role.name == name)): raise HTTPException(409, "Role already exists.")
    s.add(Role(name=name)); s.commit(); audit(s, a.email, "role_add", name, r); return {"ok": True}
@app.get("/admin/resources")
def resources(a=Depends(admin), s: Session = Depends(db)): return [{"id": x.id, "name": x.name, "description": x.description} for x in s.scalars(select(Resource))]
@app.post("/admin/resources")
def add_res(b: Named, r: Request, a=Depends(admin), s: Session = Depends(db)):
    name = b.name.strip()
    if not name: raise HTTPException(422, "Resource name is required.")
    if s.scalar(select(Resource).where(Resource.name == name)): raise HTTPException(409, "Resource already exists.")
    s.add(Resource(name=name, description=b.description.strip())); s.commit(); audit(s, a.email, "resource_add", name, r); return {"ok": True}
@app.get("/admin/grants")
def grants(a=Depends(admin), s: Session = Depends(db)): return [{"id": g.id, "role_id": g.role_id, "resource_id": g.resource_id, "cidrs": g.cidrs} for g in s.scalars(select(Grant))]
@app.put("/admin/grants")
def set_grant(b: GrantIn, r: Request, a=Depends(admin), s: Session = Depends(db)):
    if not s.get(Role, b.role_id): raise HTTPException(422, "Role not found.")
    if not s.get(Resource, b.resource_id): raise HTTPException(422, "Resource not found.")
    for c in filter(None, (x.strip() for x in b.cidrs.split(","))):
        try: ipaddress.ip_network(c, strict=False)
        except ValueError: raise HTTPException(422, f"'{c}' is not a valid IP range (example: 10.0.0.0/8).")
    g = s.scalar(select(Grant).where(Grant.role_id == b.role_id, Grant.resource_id == b.resource_id))
    if g: g.cidrs = b.cidrs
    else: s.add(Grant(**b.model_dump()))
    s.commit(); audit(s, a.email, "grant_set", str(b.model_dump()), r); return {"ok": True}
@app.delete("/admin/grants/{gid}")
def del_grant(gid: int, r: Request, a=Depends(admin), s: Session = Depends(db)):
    g = s.get(Grant, gid)
    if g: s.delete(g); s.commit()
    audit(s, a.email, "grant_remove", str(gid), r); return {"ok": True}
@app.get("/admin/audit")
def audit_log(limit: int = 200, a=Depends(admin), s: Session = Depends(db)):
    limit = max(1, min(limit, 1000))
    return [{"at": x.at.isoformat(), "actor": x.actor, "action": x.action, "detail": x.detail, "ip": x.ip} for x in s.scalars(select(Audit).order_by(Audit.id.desc()).limit(limit))]


# ---------- company work management: manager can direct work; admin is read-only oversight ----------
def role_name(s: Session, u: User) -> str:
    role = s.get(Role, u.role_id)
    return role.name.lower() if role else ""
def require_manager(r: Request, u: User = Depends(current), s: Session = Depends(db)) -> User:
    if role_name(s, u) != "manager": raise HTTPException(403, "Manager role required.")
    return u
def require_employee_or_manager(r: Request, u: User = Depends(current), s: Session = Depends(db)) -> User:
    if role_name(s, u) not in ("manager", "employee"): raise HTTPException(403, "This workspace is for managers and employees.")
    return u
def task_json(s: Session, t: WorkTask, viewer: User):
    assignee=s.get(User,t.assignee_id); manager=s.get(User,t.manager_id)
    return {"id":t.id,"title":t.title,"description":t.description,"priority":t.priority,"deadline":t.deadline,"status":t.status,
      "assignee_id":t.assignee_id,"assignee_name":assignee.name if assignee else "Unknown","assignee_email":assignee.email if assignee else "",
      "manager_id":t.manager_id,"manager_name":manager.name if manager else "Unknown","reference_url":t.reference_url,
      "attachment_name":t.attachment_name,"submission_url":t.submission_url,"submission_name":t.submission_name,
      "submission_note":t.submission_note,"feedback":t.feedback,"created":t.created.isoformat(),"updated":t.updated.isoformat()}
class TaskCreate(BaseModel):
    title: str; description: str = ""; assignee_id: int; priority: str = "normal"; deadline: str = ""; reference_url: str = ""
class TaskUpdate(BaseModel):
    title: str | None = None; description: str | None = None; deadline: str | None = None; priority: str | None = None; status: str | None = None; submission_url: str | None = None; submission_note: str | None = None; feedback: str | None = None; reference_url: str | None = None; assignee_id: int | None = None
class MessageCreate(BaseModel):
    title: str = "Message"; body: str; recipient_id: int | None = None; kind: str = "message"; require_ack: bool = False; meeting_at: str = ""
class TaskCommentCreate(BaseModel):
    body: str
@app.get("/work/people")
def work_people(r: Request, u: User = Depends(require_employee_or_manager), s: Session = Depends(db)):
    if role_name(s,u)=="manager":
        return [{"id":x.id,"name":x.name,"email":x.email,"department":x.department,"role":role_name(s,x),"active":x.active} for x in s.scalars(select(User).order_by(User.name)) if x.active and role_name(s,x)=="employee"]
    return [{"id":u.id,"name":u.name,"email":u.email,"department":u.department,"role":"employee","active":u.active}]
@app.post("/work/people")
def work_add_person(b: NewUser, r: Request, m: User = Depends(require_manager), s: Session = Depends(db)):
    email=b.email.strip().lower()
    if not EMAIL.match(email) or not b.name.strip(): raise HTTPException(422,"Enter a valid email and name.")
    if s.scalar(select(User).where(User.email==email)): raise HTTPException(409,"Email already exists.")
    er=s.scalar(select(Role).where(Role.name=="employee"))
    if not er: raise HTTPException(500,"Employee role is missing.")
    pw=b.password or secrets.token_urlsafe(9)
    if len(pw.encode())>72: raise HTTPException(422,"Password must be 72 bytes or fewer.")
    u=User(email=email,name=b.name.strip(),department=b.department.strip(),role_id=er.id,pw_hash=hash_pw(pw));s.add(u);s.commit();s.refresh(u)
    audit(s,m.email,"manager_employee_add",email,r)
    return {"id":u.id,"email":u.email,"name":u.name,"temp_password":pw}
@app.delete("/work/people/{uid}")
def work_remove_person(uid:int,r:Request,m:User=Depends(require_manager),s:Session=Depends(db)):
    u=s.get(User,uid)
    if not u or role_name(s,u)!="employee": raise HTTPException(404,"Employee not found.")
    u.active=False;s.commit();audit(s,m.email,"manager_employee_deactivate",u.email,r);return {"ok":True}
@app.get("/work/tasks")
def work_tasks(r:Request,u:User=Depends(require_employee_or_manager),s:Session=Depends(db)):
    if role_name(s,u)=="manager": rows=s.scalars(select(WorkTask).order_by(WorkTask.deadline,WorkTask.id.desc())).all()
    else: rows=s.scalars(select(WorkTask).where(WorkTask.assignee_id==u.id).order_by(WorkTask.deadline,WorkTask.id.desc())).all()
    return [task_json(s,t,u) for t in rows]

@app.get("/work/tasks/{tid}/comments")
def get_task_comments(tid:int, r:Request, u:User=Depends(current), s:Session=Depends(db)):
    t=s.get(WorkTask,tid)
    if not t: raise HTTPException(404,"Task not found.")
    if role_name(s,u)=="admin" and not in_net(ADMIN_CIDRS, ip_of(r)): raise HTTPException(403,"Admin panel is not available from this network.")
    if not can_view_task(s,u,t): raise HTTPException(403,"You cannot view this task discussion.")
    rows=s.scalars(select(TaskComment).where(TaskComment.task_id==tid).order_by(TaskComment.created,TaskComment.id)).all()
    return [{"id":c.id,"task_id":c.task_id,"author_id":c.author_id,"author":(s.get(User,c.author_id).name if s.get(User,c.author_id) else "Unknown"),"author_role":role_name(s,s.get(User,c.author_id)) if s.get(User,c.author_id) else "unknown","body":c.body,"created":c.created.isoformat()} for c in rows]

@app.post("/work/tasks/{tid}/comments")
def add_task_comment(tid:int,b:TaskCommentCreate,r:Request,u:User=Depends(require_employee_or_manager),s:Session=Depends(db)):
    t=s.get(WorkTask,tid)
    if not t: raise HTTPException(404,"Task not found.")
    if role_name(s,u)=="employee" and t.assignee_id!=u.id: raise HTTPException(403,"This task is not assigned to you.")
    text=b.body.strip()
    if not text: raise HTTPException(422,"Comment cannot be empty.")
    if len(text)>10000: raise HTTPException(422,"Comment is too long (10,000 characters maximum).")
    c=TaskComment(task_id=tid,author_id=u.id,body=text)
    s.add(c); t.updated=now(); history(s,tid,u.id,"comment_added",text[:500]); other_id=t.manager_id if u.id==t.assignee_id else t.assignee_id
    if other_id != u.id: notify(s,other_id,f"New comment on task #{tid}: {t.title}",text[:1000],"task_comment",tid)
    s.commit(); s.refresh(c)
    audit(s,u.email,"task_comment",f"task={tid}; comment={c.id}",r)
    return {"id":c.id,"task_id":c.task_id,"author_id":c.author_id,"author":u.name,"author_role":role_name(s,u),"body":c.body,"created":c.created.isoformat()}

@app.post("/work/tasks")
def create_task(b:TaskCreate,r:Request,m:User=Depends(require_manager),s:Session=Depends(db)):
    title=b.title.strip()
    if not title: raise HTTPException(422,"Task title is required.")
    if b.priority not in ("low","normal","high","critical"): raise HTTPException(422,"Invalid priority.")
    target=s.get(User,b.assignee_id)
    if not target or not target.active or role_name(s,target)!="employee": raise HTTPException(422,"Choose an active employee.")
    if b.reference_url and not re.match(r"^https?://",b.reference_url,re.I): raise HTTPException(422,"Reference URL must start with http:// or https://")
    t=WorkTask(title=title,description=b.description,assignee_id=target.id,manager_id=m.id,priority=b.priority,deadline=b.deadline,reference_url=b.reference_url)
    s.add(t);s.flush();history(s,t.id,m.id,"created",f"Assigned to {target.name}; priority={t.priority}; deadline={t.deadline or 'none'}");notify(s,target.id,f"New task assigned: {t.title}",t.description,"task_assigned",t.id);s.commit();s.refresh(t);audit(s,m.email,"task_assigned",f"task={t.id}; employee={target.email}",r)
    return task_json(s,t,m)
@app.patch("/work/tasks/{tid}")
def update_task(tid:int,b:TaskUpdate,r:Request,u:User=Depends(require_employee_or_manager),s:Session=Depends(db)):
    t=s.get(WorkTask,tid)
    if not t: raise HTTPException(404,"Task not found.")
    manager=role_name(s,u)=="manager"
    if not manager and t.assignee_id!=u.id: raise HTTPException(403,"This task is not assigned to you.")
    changes=b.model_dump(exclude_none=True)
    if manager and "priority" in changes and changes["priority"] not in ("low","normal","high","critical"): raise HTTPException(422,"Invalid priority.")
    if manager and "assignee_id" in changes:
        target=s.get(User,changes["assignee_id"])
        if not target or not target.active or role_name(s,target)!="employee": raise HTTPException(422,"Choose an active employee.")
    if manager and "reference_url" in changes and changes["reference_url"] and not re.match(r"^https?://",changes["reference_url"],re.I): raise HTTPException(422,"Reference URL must start with http:// or https://")
    if manager and "title" in changes:
        changes["title"]=changes["title"].strip()
        if not changes["title"]: raise HTTPException(422,"Task title cannot be blank.")
    if "status" in changes:
        allowed_status=("assigned","in_progress","submitted","needs_changes","approved","delayed")
        if changes["status"] not in allowed_status: raise HTTPException(422,"Invalid task status.")
        if not manager and changes["status"] not in ("in_progress","submitted","delayed"): raise HTTPException(403,"Employees can only update progress or submit work.")
    if not manager and "feedback" in changes: raise HTTPException(403,"Only a manager can provide review feedback.")
    if not manager and any(k not in ("status","submission_url","submission_note") for k in changes): raise HTTPException(403,"Not allowed.")
    if "submission_url" in changes and changes["submission_url"] and not re.match(r"^https?://",changes["submission_url"],re.I): raise HTTPException(422,"Submission URL must start with http:// or https://")
    old_status=t.status
    old_assignee=t.assignee_id
    if manager and changes.get("status")=="approved" and not (changes.get("submission_url",t.submission_url) or t.submission_path):
        raise HTTPException(422,"A task can only be approved after a project URL or ZIP submission exists.")
    if not manager and changes.get("status")=="submitted" and not (changes.get("submission_url",t.submission_url) or t.submission_path):
        raise HTTPException(422,"Submit a project URL or ZIP file before marking this task submitted.")
    for k,v in changes.items(): setattr(t,k,v)
    if manager and "assignee_id" in changes and changes["assignee_id"] != old_assignee:
        notify(s,changes["assignee_id"],f"Task assigned to you: {t.title}","A manager assigned or reassigned this task to you.","task_assigned",tid)
    if not manager and changes.get("status")=="submitted" and changes.get("submission_url"):
        last=s.scalar(select(SubmissionVersion).where(SubmissionVersion.task_id==tid).order_by(SubmissionVersion.version.desc()).limit(1))
        ver=(last.version+1) if last else 1
        s.add(SubmissionVersion(task_id=tid,user_id=u.id,version=ver,submission_url=changes["submission_url"],note=changes.get("submission_note",t.submission_note or "")))
        history(s,tid,u.id,"url_submitted",f"version={ver}; url={changes['submission_url']}")
        notify(s,t.manager_id,f"Submission ready for review: {t.title}","A project URL was submitted.","submission",tid)
    t.updated=now()
    if changes:
        history(s,tid,u.id,"updated",", ".join(f"{k}: {str(v)[:300]}" for k,v in changes.items()))
    if "status" in changes and changes["status"] != old_status:
        if manager: notify(s,t.assignee_id,f"Task status updated: {t.title}",f"Status: {changes['status']}","task_status",tid)
        elif t.manager_id != u.id: notify(s,t.manager_id,f"Employee updated task: {t.title}",f"Status: {changes['status']}","task_status",tid)
    if manager and ("feedback" in changes or changes.get("status") in ("needs_changes","approved")):
        notify(s,t.assignee_id,f"Review update: {t.title}",changes.get("feedback") or changes.get("status", ""),"task_review",tid)
    s.commit();s.refresh(t);audit(s,u.email,"task_update",f"task={tid}; fields={','.join(changes)}",r)
    return task_json(s,t,u)
@app.post("/work/tasks/{tid}/attachment")
def upload_task_attachment(tid:int,r:Request,file:UploadFile=File(...),m:User=Depends(require_manager),s:Session=Depends(db)):
    t=s.get(WorkTask,tid)
    if not t: raise HTTPException(404,"Task not found.")
    filename=os.path.basename(file.filename or "attachment")
    raw=file.file.read()
    if not raw or len(raw)>50*1024*1024: raise HTTPException(413,"Attachment must be non-empty and at most 50 MB.")
    root=os.path.join(os.path.dirname(__file__),"uploads");os.makedirs(root,exist_ok=True)
    path=os.path.join(root,f"task-{tid}-attachment-{secrets.token_hex(6)}-{filename}")
    with open(path,"wb") as f:f.write(raw)
    t.attachment_name=filename;t.attachment_path=path;t.updated=now();history(s,tid,m.id,"reference_file_added",filename);notify(s,t.assignee_id,f"Reference file added: {t.title}",filename,"task_attachment",tid);s.commit();audit(s,m.email,"task_attachment",f"task={tid}; file={filename}",r)
    return {"ok":True,"attachment_name":filename}
@app.get("/work/tasks/{tid}/attachment")
def download_task_attachment(tid:int,r:Request,u:User=Depends(current),s:Session=Depends(db)):
    from fastapi.responses import FileResponse
    t=s.get(WorkTask,tid)
    if not t: raise HTTPException(404,"Task not found.")
    if role_name(s,u)=="admin" and not in_net(ADMIN_CIDRS, ip_of(r)): raise HTTPException(403,"Admin panel is not available from this network.")
    if role_name(s,u) not in ("admin","manager") and t.assignee_id!=u.id: raise HTTPException(403,"Not allowed.")
    if role_name(s,u) not in ("admin","manager","employee"): raise HTTPException(403,"Not allowed.")
    if not t.attachment_path or not os.path.isfile(t.attachment_path): raise HTTPException(404,"No attachment available.")
    return FileResponse(t.attachment_path,filename=t.attachment_name or "attachment")
@app.post("/work/tasks/{tid}/upload")
def upload_submission(tid:int,r:Request,file:UploadFile=File(...),note:str=Form(""),u:User=Depends(require_employee_or_manager),s:Session=Depends(db)):
    t=s.get(WorkTask,tid)
    if not t: raise HTTPException(404,"Task not found.")
    if role_name(s,u)!="employee" or t.assignee_id!=u.id: raise HTTPException(403,"Only the assigned employee can upload a submission.")
    filename=os.path.basename(file.filename or "submission.zip")
    if not filename.lower().endswith(".zip"): raise HTTPException(422,"Upload a ZIP file.")
    raw=file.file.read()
    if not raw or len(raw)>50*1024*1024: raise HTTPException(413,"ZIP must be non-empty and at most 50 MB.")
    if not raw.startswith(b"PK\x03\x04"): raise HTTPException(422,"This file does not appear to be a valid ZIP archive.")
    root=os.path.join(os.path.dirname(__file__),"uploads");os.makedirs(root,exist_ok=True)
    path=os.path.join(root,f"task-{tid}-user-{u.id}-{secrets.token_hex(6)}.zip")
    with open(path,"wb") as f:f.write(raw)
    t.submission_path=path;t.submission_name=filename;t.submission_note=note;t.status="submitted";t.updated=now()
    version=(s.scalar(select(SubmissionVersion).where(SubmissionVersion.task_id==tid).order_by(SubmissionVersion.version.desc()).limit(1)))
    ver=(version.version+1) if version else 1
    s.add(SubmissionVersion(task_id=tid,user_id=u.id,version=ver,file_name=filename,file_path=path,note=note,submission_url=t.submission_url or ""))
    history(s,tid,u.id,"zip_submitted",f"version={ver}; file={filename}");notify(s,t.manager_id,f"Submission ready for review: {t.title}",f"ZIP submitted (version {ver}).","submission",tid)
    s.commit();audit(s,u.email,"task_zip_submission",f"task={tid}; file={filename}; bytes={len(raw)}",r)
    return task_json(s,t,u)
@app.get("/work/tasks/{tid}/download")
def download_submission(tid:int,r:Request,u:User=Depends(current),s:Session=Depends(db)):
    from fastapi.responses import FileResponse
    t=s.get(WorkTask,tid)
    if not t: raise HTTPException(404,"Task not found.")
    if role_name(s,u)=="admin" and not in_net(ADMIN_CIDRS, ip_of(r)): raise HTTPException(403,"Admin panel is not available from this network.")
    if role_name(s,u) not in ("admin","manager") and t.assignee_id!=u.id: raise HTTPException(403,"Not allowed.")
    if role_name(s,u) not in ("admin","manager","employee"): raise HTTPException(403,"Not allowed.")
    if not t.submission_path or not os.path.isfile(t.submission_path): raise HTTPException(404,"No ZIP submission available.")
    return FileResponse(t.submission_path,filename=t.submission_name or "submission.zip",media_type="application/zip")
@app.get("/work/messages")
def work_messages(r:Request,u:User=Depends(require_employee_or_manager),s:Session=Depends(db)):
    rows=s.scalars(select(WorkMessage).where(or_(WorkMessage.recipient_id==u.id,WorkMessage.recipient_id==None) if role_name(s,u)=="employee" else True).order_by(WorkMessage.id.desc()).limit(300)).all()
    result=[]
    for x in rows:
        ack=s.scalar(select(MessageAcknowledgement).where(MessageAcknowledgement.message_id==x.id,MessageAcknowledgement.user_id==u.id))
        ack_count=len(s.scalars(select(MessageAcknowledgement).where(MessageAcknowledgement.message_id==x.id)).all()) if role_name(s,u)=="manager" else 0
        result.append({"id":x.id,"sender":s.get(User,x.sender_id).name if s.get(User,x.sender_id) else "Unknown","recipient_id":x.recipient_id,"recipient":s.get(User,x.recipient_id).name if x.recipient_id and s.get(User,x.recipient_id) else "Everyone","title":x.title,"body":x.body,"kind":x.kind,"ack_required":x.ack_required,"meeting_at":x.meeting_at,"created":x.created.isoformat(),"acknowledged":bool(ack),"ack_count":ack_count})
    return result
@app.post("/work/messages")
def send_work_message(b:MessageCreate,r:Request,m:User=Depends(require_manager),s:Session=Depends(db)):
    body=b.body.strip()
    if not body: raise HTTPException(422,"Message cannot be empty.")
    recipient=None
    if b.recipient_id is not None:
        recipient=s.get(User,b.recipient_id)
        if not recipient or not recipient.active or role_name(s,recipient)!="employee": raise HTTPException(422,"Choose an active employee or send to everyone.")
    kind=b.kind if b.kind in ("message","meeting","announcement") else "message"
    if kind == "meeting" and not b.meeting_at.strip(): raise HTTPException(422,"Choose a scheduled date and time for the meeting notice.")
    if b.meeting_at and not re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}",b.meeting_at): raise HTTPException(422,"Meeting time must be a valid date and time.")
    msg=WorkMessage(sender_id=m.id,recipient_id=recipient.id if recipient else None,title=b.title.strip() or "Message",body=body,kind=kind,ack_required=b.require_ack,meeting_at=b.meeting_at)
    s.add(msg);s.flush()
    targets=[recipient] if recipient else list(s.scalars(select(User).join(Role,User.role_id==Role.id).where(Role.name=="employee",User.active==True)))
    for target_user in targets:
        if target_user.id != m.id: notify(s,target_user.id,msg.title,body,kind,message_id=msg.id)
    s.commit();s.refresh(msg);audit(s,m.email,"work_message",f"kind={kind}; recipient={recipient.email if recipient else 'all employees'}",r)
    return {"ok":True,"id":msg.id}
@app.get("/admin/work-overview")
def admin_work_overview(r:Request,a:User=Depends(admin),s:Session=Depends(db)):
    tasks=s.scalars(select(WorkTask).order_by(WorkTask.updated.desc()).limit(1000)).all()
    messages=s.scalars(select(WorkMessage).order_by(WorkMessage.id.desc()).limit(500)).all()
    return {"tasks":[task_json(s,t,a) for t in tasks],"messages":[{"id":x.id,"sender":s.get(User,x.sender_id).name if s.get(User,x.sender_id) else "Unknown","recipient_id":x.recipient_id,"recipient":s.get(User,x.recipient_id).name if x.recipient_id and s.get(User,x.recipient_id) else "Everyone","title":x.title,"body":x.body,"kind":x.kind,"ack_required":x.ack_required,"meeting_at":x.meeting_at,"ack_count":len(s.scalars(select(MessageAcknowledgement).where(MessageAcknowledgement.message_id==x.id)).all()),"created":x.created.isoformat()} for x in messages]}

# ---------- admin: import pipeline  (upload -> map -> preview/validate -> commit) ----------
ALIASES = {"email": ["email", "e-mail", "mail", "email address"], "name": ["name", "full name", "fullname", "employee"], "department": ["department", "dept", "team"]}
def load(f: UploadFile) -> pd.DataFrame:
    raw, n = f.file.read(), (f.filename or "").lower()
    try:
        if n.endswith((".xlsx", ".xlsm", ".xls")): return pd.read_excel(io.BytesIO(raw), dtype=str).fillna("")
        if n.endswith(".json"): return pd.read_json(io.BytesIO(raw), dtype=str).fillna("")
        if n.endswith((".csv", ".tsv", ".txt")): return pd.read_csv(io.BytesIO(raw), sep=None, engine="python", dtype=str, encoding_errors="replace").fillna("")
    except Exception as e: raise HTTPException(400, f"Could not read file: {e}")
    raise HTTPException(400, "Unsupported file type. Use CSV, TSV, XLSX, XLS or JSON.")
def automap(cols):
    low = {c.lower().strip(): c for c in cols}
    return {k: next((low[a] for a in al if a in low), None) for k, al in ALIASES.items()}
def analyze(df, mp, s):
    for key in ("email", "name", "department"):
        value = mp.get(key)
        if value is not None and (not isinstance(value, str) or value not in df.columns):
            raise HTTPException(400, f"Invalid column mapping for {key}.")
    have = set(s.scalars(select(User.email))); seen, good, bad = set(), [], []
    for i, row in df.iterrows():
        g = lambda k: str(row[mp[k]]).strip() if mp.get(k) in df.columns else ""
        e, n, d = g("email").lower(), g("name"), g("department")
        err = "Missing name" if not n else "Invalid email" if not EMAIL.match(e) else "Duplicate in file" if e in seen else "Already exists" if e in have else None
        (bad.append({"row": i + 2, "email": e, "error": err}) if err else good.append({"email": e, "name": n, "department": d})); seen.add(e)
    return good, bad
@app.post("/admin/import/preview")
def imp_preview(r: Request, file: UploadFile = File(...), mapping: str = Form(""), a=Depends(admin), s: Session = Depends(db)):
    df = load(file)
    try: mp = json.loads(mapping) if mapping else automap(df.columns)
    except (ValueError, TypeError): raise HTTPException(400, "Column mapping must be valid JSON.")
    if not isinstance(mp, dict): raise HTTPException(400, "Column mapping must be a JSON object.")
    good, bad = analyze(df, mp, s)
    return {"columns": list(df.columns), "mapping": mp, "total": len(df), "valid": len(good), "errors": bad[:500], "sample": good[:20]}
@app.post("/admin/import/commit")
def imp_commit(r: Request, file: UploadFile = File(...), mapping: str = Form(...), role_id: int = Form(...), a=Depends(admin), s: Session = Depends(db)):
    if not s.get(Role, role_id): raise HTTPException(422, "Choose a valid role.")
    try: mp = json.loads(mapping)
    except (ValueError, TypeError): raise HTTPException(400, "Column mapping must be valid JSON.")
    if not isinstance(mp, dict): raise HTTPException(400, "Column mapping must be a JSON object.")
    good, bad = analyze(load(file), mp, s); out = []
    for g in good:
        pw = secrets.token_urlsafe(9); s.add(User(**g, role_id=role_id, pw_hash=hash_pw(pw))); out.append({**g, "temp_password": pw})
    s.commit(); audit(s, a.email, "import", f"{file.filename}: created {len(good)}, skipped {len(bad)}", r)
    return {"created": len(good), "skipped": len(bad), "credentials": out}   # show/export once, then discard

# ---------- task history, submission versions, notifications, search, calendar, reports, backups ----------
def can_view_task(s: Session, u: User, t: WorkTask) -> bool:
    role = role_name(s, u)
    return role == "admin" or (role == "manager") or (role == "employee" and t.assignee_id == u.id)

@app.get("/work/tasks/{tid}/history")
def task_history(tid: int, r: Request, u: User = Depends(current), s: Session = Depends(db)):
    t = s.get(WorkTask, tid)
    if not t: raise HTTPException(404, "Task not found.")
    if role_name(s,u)=="admin" and not in_net(ADMIN_CIDRS, ip_of(r)): raise HTTPException(403,"Admin panel is not available from this network.")
    if not can_view_task(s, u, t): raise HTTPException(403, "You cannot view this task history.")
    rows = s.scalars(select(TaskHistory).where(TaskHistory.task_id == tid).order_by(TaskHistory.id.desc()).limit(300)).all()
    return [{"id":x.id,"actor":(s.get(User,x.actor_id).name if s.get(User,x.actor_id) else "Unknown"),"action":x.action,"detail":x.detail,"created":x.created.isoformat()} for x in rows]

@app.get("/work/tasks/{tid}/submissions")
def task_submissions(tid: int, r: Request, u: User = Depends(current), s: Session = Depends(db)):
    t=s.get(WorkTask,tid)
    if not t: raise HTTPException(404,"Task not found.")
    if role_name(s,u)=="admin" and not in_net(ADMIN_CIDRS, ip_of(r)): raise HTTPException(403,"Admin panel is not available from this network.")
    if not can_view_task(s,u,t): raise HTTPException(403,"You cannot view these submissions.")
    rows=s.scalars(select(SubmissionVersion).where(SubmissionVersion.task_id==tid).order_by(SubmissionVersion.version.desc())).all()
    return [{"id":x.id,"version":x.version,"user":(s.get(User,x.user_id).name if s.get(User,x.user_id) else "Unknown"),"submission_url":x.submission_url,"file_name":x.file_name,"note":x.note,"has_file":bool(x.file_path and os.path.isfile(x.file_path)),"created":x.created.isoformat()} for x in rows]

@app.get("/work/tasks/{tid}/submissions/{version_id}/download")
def download_submission_version(tid: int, version_id: int, r: Request, u: User = Depends(current), s: Session = Depends(db)):
    from fastapi.responses import FileResponse
    t=s.get(WorkTask,tid); v=s.get(SubmissionVersion,version_id)
    if not t or not v or v.task_id != tid: raise HTTPException(404,"Submission version not found.")
    if role_name(s,u)=="admin" and not in_net(ADMIN_CIDRS, ip_of(r)): raise HTTPException(403,"Admin panel is not available from this network.")
    if not can_view_task(s,u,t): raise HTTPException(403,"You cannot download this submission.")
    if not v.file_path or not os.path.isfile(v.file_path): raise HTTPException(404,"This version has no ZIP file.")
    return FileResponse(v.file_path, filename=v.file_name or f"submission-v{v.version}.zip", media_type="application/zip")

@app.get("/work/notifications")
def get_notifications(u: User = Depends(require_employee_or_manager), s: Session = Depends(db)):
    rows=s.scalars(select(Notification).where(Notification.user_id==u.id).order_by(Notification.id.desc()).limit(300)).all()
    return [{"id":x.id,"title":x.title,"body":x.body,"kind":x.kind,"task_id":x.task_id,"message_id":x.message_id,"read":x.read_at is not None,"created":x.created.isoformat()} for x in rows]

@app.patch("/work/notifications/{nid}/read")
def read_notification(nid: int, u: User = Depends(require_employee_or_manager), s: Session = Depends(db)):
    n=s.get(Notification,nid)
    if not n or n.user_id != u.id: raise HTTPException(404,"Notification not found.")
    if n.read_at is None: n.read_at=now(); s.commit()
    return {"ok":True,"id":nid,"read":True}

@app.post("/work/notifications/read-all")
def read_all_notifications(u: User = Depends(require_employee_or_manager), s: Session = Depends(db)):
    rows=s.scalars(select(Notification).where(Notification.user_id==u.id,Notification.read_at==None)).all()
    for n in rows: n.read_at=now()
    s.commit(); return {"ok":True,"count":len(rows)}

@app.post("/work/messages/{mid}/ack")
def acknowledge_message(mid: int, u: User = Depends(require_employee_or_manager), s: Session = Depends(db)):
    m=s.get(WorkMessage,mid)
    if not m: raise HTTPException(404,"Message not found.")
    role=role_name(s,u)
    if role == "employee" and m.recipient_id not in (None,u.id): raise HTTPException(403,"This message was not sent to you.")
    existing=s.scalar(select(MessageAcknowledgement).where(MessageAcknowledgement.message_id==mid,MessageAcknowledgement.user_id==u.id))
    if not existing: s.add(MessageAcknowledgement(message_id=mid,user_id=u.id)); s.commit()
    return {"ok":True,"acknowledged":True}

@app.get("/work/messages/{mid}/acknowledgements")
def message_acknowledgements(mid: int, m: User = Depends(require_manager), s: Session = Depends(db)):
    msg=s.get(WorkMessage,mid)
    if not msg: raise HTTPException(404,"Message not found.")
    target_ids=[msg.recipient_id] if msg.recipient_id is not None else [x.id for x in s.scalars(select(User).join(Role,User.role_id==Role.id).where(Role.name=="employee",User.active==True))]
    acknowledgements={x.user_id:x.acknowledged_at.isoformat() for x in s.scalars(select(MessageAcknowledgement).where(MessageAcknowledgement.message_id==mid))}
    return {"message_id":mid,"required":msg.ack_required,"total":len(target_ids),"acknowledged":len([i for i in target_ids if i in acknowledgements]),"people":[{"user_id":i,"name":(s.get(User,i).name if s.get(User,i) else "Unknown"),"acknowledged_at":acknowledgements.get(i)} for i in target_ids]}

@app.get("/work/calendar")
def work_calendar(u: User = Depends(require_employee_or_manager), s: Session = Depends(db)):
    st=select(WorkTask).where(WorkTask.deadline!="")
    if role_name(s,u)=="employee": st=st.where(WorkTask.assignee_id==u.id)
    rows=s.scalars(st.order_by(WorkTask.deadline).limit(1000)).all()
    items=[{"id":t.id,"title":t.title,"deadline":t.deadline,"priority":t.priority,"status":t.status,"kind":"task_deadline","assignee_name":(s.get(User,t.assignee_id).name if s.get(User,t.assignee_id) else "Unknown"),"task_id":t.id} for t in rows]
    messages=s.scalars(select(WorkMessage).where(WorkMessage.kind=="meeting").order_by(WorkMessage.created.desc()).limit(300)).all()
    for msg in messages:
        if role_name(s,u)=="employee" and msg.recipient_id not in (None,u.id): continue
        items.append({"id":f"meeting-{msg.id}","title":msg.title,"deadline":msg.meeting_at or "","created":msg.created.isoformat(),"kind":"meeting","status":"notice","task_id":None,"assignee_name":""})
    return sorted(items,key=lambda x:x.get("deadline") or x.get("created") or "9999",reverse=False)

@app.get("/work/reports")
def work_reports(u: User = Depends(require_employee_or_manager), s: Session = Depends(db)):
    role=role_name(s,u)
    st=select(WorkTask)
    if role=="employee": st=st.where(WorkTask.assignee_id==u.id)
    rows=s.scalars(st).all()
    counts={k:sum(1 for t in rows if t.status==k) for k in ("assigned","in_progress","submitted","needs_changes","approved","delayed")}
    today=now().date().isoformat()
    overdue=[t for t in rows if t.deadline and t.deadline[:10] < today and t.status not in ("approved","submitted")]
    by_employee=[]
    if role=="manager":
        grouped={}
        for t in rows:
            a=s.get(User,t.assignee_id); name=a.name if a else "Unknown"
            g=grouped.setdefault(t.assignee_id,{"employee_id":t.assignee_id,"employee":name,"total":0,"approved":0,"overdue":0,"submitted":0})
            g["total"]+=1; g["approved"]+=int(t.status=="approved"); g["submitted"]+=int(t.status=="submitted"); g["overdue"]+=int(t in overdue)
        by_employee=list(grouped.values())
    return {"total":len(rows),"status_counts":counts,"overdue":len(overdue),"awaiting_review":counts["submitted"],"by_employee":by_employee}

@app.get("/work/search")
def work_search(q: str = "", u: User = Depends(require_employee_or_manager), s: Session = Depends(db)):
    q=q.strip()[:160]
    if not q: return {"tasks":[],"messages":[],"people":[]}
    pattern=f"%{q}%"; role=role_name(s,u)
    ts=select(WorkTask).where(or_(WorkTask.title.ilike(pattern),WorkTask.description.ilike(pattern),WorkTask.submission_note.ilike(pattern)))
    if role=="employee": ts=ts.where(WorkTask.assignee_id==u.id)
    tasks=s.scalars(ts.order_by(WorkTask.updated.desc()).limit(100)).all()
    ms=s.scalars(select(WorkMessage).where(or_(WorkMessage.title.ilike(pattern),WorkMessage.body.ilike(pattern))).order_by(WorkMessage.id.desc()).limit(50)).all()
    if role=="employee": ms=[m for m in ms if m.recipient_id in (None,u.id)]
    ps=[]
    if role=="manager": ps=[{"id":p.id,"name":p.name,"email":p.email,"department":p.department} for p in s.scalars(select(User).where(User.active==True).order_by(User.name)) if role_name(s,p)=="employee" and (q.lower() in p.name.lower() or q.lower() in p.email.lower() or q.lower() in (p.department or "").lower())][:50]
    return {"tasks":[task_json(s,t,u) for t in tasks],"messages":[{"id":m.id,"title":m.title,"body":m.body,"kind":m.kind,"created":m.created.isoformat()} for m in ms],"people":ps}

@app.get("/admin/search")
def admin_search(q: str = "", a: User = Depends(admin), s: Session = Depends(db)):
    q=q.strip()[:160]
    if not q: return {"users":[],"tasks":[],"messages":[]}
    pattern=f"%{q}%"
    users_=s.scalars(select(User).where(or_(User.name.ilike(pattern),User.email.ilike(pattern),User.department.ilike(pattern))).limit(100)).all()
    tasks_=s.scalars(select(WorkTask).where(or_(WorkTask.title.ilike(pattern),WorkTask.description.ilike(pattern))).order_by(WorkTask.updated.desc()).limit(100)).all()
    msgs=s.scalars(select(WorkMessage).where(or_(WorkMessage.title.ilike(pattern),WorkMessage.body.ilike(pattern))).order_by(WorkMessage.id.desc()).limit(50)).all()
    return {"users":[{"id":x.id,"name":x.name,"email":x.email,"department":x.department,"active":x.active,"role":role_name(s,x)} for x in users_],"tasks":[task_json(s,t,a) for t in tasks_],"messages":[{"id":m.id,"title":m.title,"body":m.body,"kind":m.kind,"created":m.created.isoformat()} for m in msgs]}

@app.get("/admin/reports")
def admin_reports(a: User = Depends(admin), s: Session = Depends(db)):
    rows=s.scalars(select(WorkTask)).all()
    counts={k:sum(1 for t in rows if t.status==k) for k in ("assigned","in_progress","submitted","needs_changes","approved","delayed")}
    today=now().date().isoformat()
    overdue=[t for t in rows if t.deadline and t.deadline[:10] < today and t.status not in ("approved","submitted")]
    active_users=s.scalars(select(User).where(User.active==True)).all()
    return {"total_tasks":len(rows),"status_counts":counts,"overdue":len(overdue),"awaiting_review":counts["submitted"],"active_users":len(active_users),"employees":sum(1 for x in active_users if role_name(s,x)=="employee"),"managers":sum(1 for x in active_users if role_name(s,x)=="manager")}

@app.get("/admin/backup")
def admin_backup(r: Request, a: User = Depends(admin), s: Session = Depends(db)):
    from fastapi.responses import FileResponse
    if not engine.url.drivername.startswith("sqlite"):
        raise HTTPException(501,"Automatic backup download currently supports the local SQLite database. For PostgreSQL, configure pg_dump backups.")
    db_path=engine.url.database
    if not db_path: raise HTTPException(500,"Database path is unavailable.")
    if not os.path.isabs(db_path): db_path=os.path.abspath(os.path.join(os.path.dirname(__file__),db_path))
    if not os.path.isfile(db_path): raise HTTPException(404,"Database file was not found.")
    backup_dir=os.path.join(os.path.dirname(__file__),"backups");os.makedirs(backup_dir,exist_ok=True)
    stamp=now().strftime("%Y%m%d-%H%M%S")
    out=os.path.join(backup_dir,f"bizsuite-backup-{stamp}.zip")
    with tempfile.TemporaryDirectory() as tmp:
        snapshot=os.path.join(tmp,"bizsuite.db")
        src=sqlite3.connect(db_path); dst=sqlite3.connect(snapshot)
        try: src.backup(dst)
        finally: dst.close(); src.close()
        with zipfile.ZipFile(out,"w",zipfile.ZIP_DEFLATED) as z:
            z.write(snapshot,"bizsuite.db")
            upload_root=os.path.join(os.path.dirname(__file__),"uploads")
            if os.path.isdir(upload_root):
                for root,_,files in os.walk(upload_root):
                    for name in files:
                        path=os.path.join(root,name); z.write(path,os.path.join("uploads",os.path.relpath(path,upload_root)))
    audit(s,a.email,"backup_created",os.path.basename(out),r)
    return FileResponse(out,filename=os.path.basename(out),media_type="application/zip")


# ---------- team chat: everyone <-> everyone (text + voice), polled by the desktop apps ----------
class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    sender_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    recipient_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    channel: Mapped[str] = mapped_column(String(10), default="all")      # all | mgmt | dm
    kind: Mapped[str] = mapped_column(String(10), default="text")        # text | voice
    body: Mapped[str] = mapped_column(Text, default="")
    duration: Mapped[int] = mapped_column(Integer, default=0)
    audio_mime: Mapped[str] = mapped_column(String(60), default="")
    audio: Mapped[bytes | None] = mapped_column(LargeBinary().with_variant(LONGBLOB(), "mysql"), nullable=True, deferred=True)
    created: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)

MAX_VOICE_BYTES = 3 * 1024 * 1024
def chat_visible(s: Session, u: User):
    cond = or_(ChatMessage.channel == "all", ChatMessage.sender_id == u.id, ChatMessage.recipient_id == u.id)
    if role_name(s, u) in ("admin", "manager"): cond = or_(cond, ChatMessage.channel == "mgmt")
    return cond
def chat_json(m: ChatMessage, names: dict):
    return {"id": m.id, "sender_id": m.sender_id, "sender_name": names.get(m.sender_id, "Unknown"), "recipient_id": m.recipient_id,
            "channel": m.channel, "kind": m.kind, "body": m.body, "duration": m.duration, "created": m.created.isoformat()}
def chat_target(s: Session, u: User, channel: str, recipient_id: int | None):
    if channel not in ("all", "mgmt", "dm"): raise HTTPException(422, "Unknown chat channel.")
    if channel == "dm":
        t = s.get(User, recipient_id) if recipient_id else None
        if not t or not t.active or t.id == u.id: raise HTTPException(422, "Choose an active person to message.")
        return t.id
    return None

@app.get("/chat/me")
def chat_me(u: User = Depends(current), s: Session = Depends(db)):
    return {"id": u.id, "name": u.name, "role": role_name(s, u)}
@app.get("/chat/people")
def chat_people(u: User = Depends(current), s: Session = Depends(db)):
    rows = s.scalars(select(User).where(User.active == True, User.id != u.id).order_by(User.name)).all()
    return [{"id": x.id, "name": x.name, "department": x.department, "role": role_name(s, x)} for x in rows]
@app.get("/chat/messages")
def chat_list(after_id: int = 0, u: User = Depends(current), s: Session = Depends(db)):
    st = select(ChatMessage).where(chat_visible(s, u))
    if after_id > 0: rows = s.scalars(st.where(ChatMessage.id > after_id).order_by(ChatMessage.id).limit(300)).all()
    else: rows = list(reversed(s.scalars(st.order_by(ChatMessage.id.desc()).limit(300)).all()))
    ids = {x.sender_id for x in rows}
    names = {x.id: x.name for x in s.scalars(select(User).where(User.id.in_(ids)))} if ids else {}
    return [chat_json(m, names) for m in rows]
class ChatIn(BaseModel): channel: str = "all"; recipient_id: int | None = None; body: str
@app.post("/chat/messages")
def chat_send(b: ChatIn, u: User = Depends(current), s: Session = Depends(db)):
    body = b.body.strip()
    if not body: raise HTTPException(422, "Type a message first.")
    if len(body) > 4000: raise HTTPException(422, "Message is too long (4000 characters max).")
    rid = chat_target(s, u, b.channel, b.recipient_id)
    m = ChatMessage(sender_id=u.id, recipient_id=rid, channel=b.channel, kind="text", body=body)
    s.add(m); s.commit(); s.refresh(m)
    return chat_json(m, {u.id: u.name})
@app.post("/chat/voice")
def chat_voice(file: UploadFile = File(...), channel: str = Form("all"), recipient_id: int | None = Form(None), duration: int = Form(0),
               u: User = Depends(current), s: Session = Depends(db)):
    rid = chat_target(s, u, channel, recipient_id)
    raw = file.file.read(MAX_VOICE_BYTES + 1)
    if not raw: raise HTTPException(422, "The voice message is empty.")
    if len(raw) > MAX_VOICE_BYTES: raise HTTPException(413, "Voice message is too large (3 MB max, about 2 minutes).")
    mime = (file.content_type or "audio/webm").split(";")[0].strip().lower()
    if not mime.startswith("audio/") and mime != "video/webm": raise HTTPException(422, "Only audio can be sent as a voice message.")
    m = ChatMessage(sender_id=u.id, recipient_id=rid, channel=channel, kind="voice", duration=max(0, min(duration, 600)), audio_mime=mime, audio=raw)
    s.add(m); s.commit(); s.refresh(m)
    return chat_json(m, {u.id: u.name})
@app.get("/chat/messages/{mid}/audio")
def chat_audio(mid: int, u: User = Depends(current), s: Session = Depends(db)):
    m = s.scalar(select(ChatMessage).where(ChatMessage.id == mid, chat_visible(s, u)))
    if not m or m.kind != "voice" or not m.audio: raise HTTPException(404, "Voice message not found.")
    return Response(content=bytes(m.audio), media_type=m.audio_mime or "audio/webm")
@app.delete("/chat/messages/{mid}")
def chat_delete(mid: int, u: User = Depends(current), s: Session = Depends(db)):
    m = s.get(ChatMessage, mid)
    if not m: return {"ok": True}
    if m.sender_id != u.id and role_name(s, u) != "admin": raise HTTPException(403, "You can only delete your own messages.")
    s.delete(m); s.commit(); return {"ok": True}
