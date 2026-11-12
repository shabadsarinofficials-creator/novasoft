"""Interactively reset an existing BizSuite admin password.

Run from the BizSuite project root in Render Shell:
    python scripts/reset_admin_password.py

This script never creates/deletes users and never prints the password.
"""
from getpass import getpass

from backend.auth import hash_password
from backend.config import settings
from backend.database import SessionLocal
from backend.models import User, UserRole


def main() -> None:
    email = input(f"Admin email [{settings.ADMIN_EMAIL}]: ").strip() or settings.ADMIN_EMAIL
    email = email.lower()
    password = getpass("New password (minimum 8 characters): ")
    confirm = getpass("Confirm new password: ")

    if len(password) < 8:
        raise SystemExit("Password must contain at least 8 characters.")
    if password != confirm:
        raise SystemExit("Passwords do not match.")

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).with_for_update().first()
        if user is None:
            raise SystemExit(f"No existing user found for {email}. No account was created.")
        if user.role != UserRole.ADMIN:
            raise SystemExit(f"The account {email} is not an administrator. No changes made.")
        user.password_hash = hash_password(password)
        db.commit()
        print(f"Password updated successfully for existing administrator: {email}")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
