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

    # Do not create a duplicate account if the configured bootstrap email already
    # belongs to a non-admin user. This preserves the existing account and data.
    configured_email = settings.ADMIN_EMAIL.lower().strip()
    email_owner = db.query(User).filter(User.email == configured_email).first()
    if email_owner:
        logger.warning(
            "Configured admin email already belongs to user id=%s with role=%s; "
            "not changing the account automatically.",
            email_owner.id,
            email_owner.role.value,
        )
        return

    admin = User(
        email=configured_email,
        name=settings.ADMIN_NAME,
        password_hash=hash_password(settings.ADMIN_PASSWORD),
        role=UserRole.ADMIN,
        is_active=True,
    )
    db.add(admin)
    db.commit()
    logger.info("Bootstrap admin created: %s", settings.ADMIN_EMAIL)