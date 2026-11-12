"""
Safe admin bootstrap — only creates an admin if none exists.
Never overwrites an existing administrator password.
"""
import logging
from sqlalchemy.orm import Session
from backend.models import User, UserRole
from backend.auth import hash_password
from backend.config import settings

logger = logging.getLogger("bizsuite.bootstrap")


def ensure_admin(db: Session) -> None:
    existing = db.query(User).filter(User.role == UserRole.ADMIN).first()
    if existing:
        logger.info("Admin already exists (id=%s). Skipping bootstrap.", existing.id)
        return

    admin = User(
        email=settings.ADMIN_EMAIL.lower().strip(),
        name=settings.ADMIN_NAME,
        password_hash=hash_password(settings.ADMIN_PASSWORD),
        role=UserRole.ADMIN,
        is_active=True,
    )
    db.add(admin)
    db.commit()
    logger.info("Bootstrap admin created: %s", settings.ADMIN_EMAIL)