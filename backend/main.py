"""
BizSuite by NovaSoft — single process serves API + frontend.
No separate Node/nginx server required. Deploy with: bash start.sh
"""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text

from backend.config import settings
from backend.database import engine, SessionLocal, Base
from backend.bootstrap import ensure_admin
from backend.services.file_service import ensure_upload_dir

from backend.routes import (
    auth,
    users,
    tasks,
    projects,
    announcements,
    files,
    chat,
    dashboard,
    settings as settings_routes,
    audit,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("bizsuite")

limiter = Limiter(key_func=get_remote_address)

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting BizSuite (built-in server)...")
    ensure_upload_dir()

    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("Database connection OK")
    except Exception as e:
        logger.error("Database connection failed: %s", e)

    # Safety net if migrations did not run
    try:
        from backend import models  # noqa: F401
        Base.metadata.create_all(bind=engine)
    except Exception as e:
        logger.warning("create_all skipped: %s", e)

    try:
        db = SessionLocal()
        ensure_admin(db)
        db.close()
    except Exception as e:
        logger.error("Bootstrap failed: %s", e)

    yield
    logger.info("Shutting down BizSuite")


app = FastAPI(
    title=settings.APP_NAME,
    description="BizSuite by NovaSoft — Business Management Platform (API + UI, single service)",
    version="1.1.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

_cors = settings.cors_origins_list
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors if _cors != ["*"] else ["*"],
    allow_credentials=_cors != ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# —— API routers ——
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(tasks.router)
app.include_router(projects.router)
app.include_router(announcements.router)
app.include_router(files.router)
app.include_router(chat.router)
app.include_router(dashboard.router)
app.include_router(settings_routes.router)
app.include_router(audit.router)


@app.get("/health")
async def health():
    db_status = "ok"
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as e:
        db_status = f"error: {type(e).__name__}"
    return {
        "status": "ok" if db_status == "ok" else "degraded",
        "app": settings.APP_NAME,
        "version": "1.1.0",
        "database": db_status,
        "mode": "single-service",
    }


def _html(name: str):
    path = FRONTEND_DIR / name
    if path.exists():
        return FileResponse(path, media_type="text/html")
    return JSONResponse({"detail": f"{name} missing"}, status_code=404)


@app.get("/")
async def root():
    return _html("index.html")


@app.get("/login")
async def login_page():
    return _html("login.html")


@app.get("/dashboard")
async def dashboard_page():
    return _html("dashboard.html")


# Clean page routes (no .html in URL)
PAGE_MAP = {
    "tasks": "pages/tasks.html",
    "projects": "pages/projects.html",
    "team": "pages/team.html",
    "chat": "pages/chat.html",
    "announcements": "pages/announcements.html",
    "files": "pages/files.html",
    "settings": "pages/settings.html",
    "admin": "pages/admin.html",
}


@app.get("/app/{page}")
async def app_page(page: str):
    rel = PAGE_MAP.get(page)
    if not rel:
        return JSONResponse({"detail": "Not found"}, status_code=404)
    path = FRONTEND_DIR / rel
    if path.exists():
        return FileResponse(path, media_type="text/html")
    return JSONResponse({"detail": "Page missing"}, status_code=404)


# Static assets (CSS / JS)
static_dir = FRONTEND_DIR / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

pages_dir = FRONTEND_DIR / "pages"
if pages_dir.exists():
    app.mount("/pages", StaticFiles(directory=str(pages_dir), html=True), name="pages")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error on %s", request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )
