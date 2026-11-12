from datetime import datetime, timedelta
import secrets
from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from backend.models import User, RecoveryRequest, AuditLog
from backend.auth import verify_password, hash_password, create_access_token
from backend.schemas import LoginRequest


def login_user(db: Session, data: LoginRequest) -> dict:
    user = db.query(User).filter(User.email == data.email.lower().strip()).first()
    if not user or not verify_password(data.password, user.password_hash):
        # Generic message — do not reveal whether email exists
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is deactivated")

    user.last_login = datetime.utcnow()
    db.add(AuditLog(actor_id=user.id, action="login", success=True))
    db.commit()

    token = create_access_token({"sub": str(user.id), "role": user.role.value})
    return {"access_token": token, "token_type": "bearer"}


def change_password(db: Session, user: User, current: str, new: str) -> None:
    if not verify_password(current, user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")
    user.password_hash = hash_password(new)
    db.add(AuditLog(actor_id=user.id, action="password_change", success=True))
    db.commit()


def request_password_reset(db: Session, email: str) -> None:
    """Always return success-looking response; never reveal if email exists."""
    user = db.query(User).filter(User.email == email.lower().strip()).first()
    if user and user.is_active:
        token = secrets.token_urlsafe(32)
        req = RecoveryRequest(
            email=user.email,
            token=token,
            expires_at=datetime.utcnow() + timedelta(hours=1),
        )
        db.add(req)
        db.add(AuditLog(actor_id=user.id, action="password_reset_request", success=True))
        db.commit()
        # In production: send email with token. For now token is stored for testing.
        # Log only in development if needed; never log the token in production.
    # Always silent success from API perspective


def reset_password_with_token(db: Session, token: str, new_password: str) -> None:
    req = (
        db.query(RecoveryRequest)
        .filter(
            RecoveryRequest.token == token,
            RecoveryRequest.used == False,
            RecoveryRequest.expires_at > datetime.utcnow(),
        )
        .first()
    )
    if not req:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired reset token")

    user = db.query(User).filter(User.email == req.email).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired reset token")

    user.password_hash = hash_password(new_password)
    req.used = True
    db.add(AuditLog(actor_id=user.id, action="password_reset", success=True))
    db.commit()