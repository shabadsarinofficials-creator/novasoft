from fastapi import APIRouter, Depends, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from slowapi import Limiter
from slowapi.util import get_remote_address
from backend.database import get_db
from backend.auth import get_current_user
from backend.models import User
from backend.schemas import (
    Token, LoginRequest, PasswordChange, PasswordResetRequest,
    PasswordResetConfirm, UserOut, MessageResponse,
)
from backend.services import auth_service

router = APIRouter(prefix="/api/auth", tags=["auth"])
limiter = Limiter(key_func=get_remote_address)


@router.post("/login", response_model=Token)
@limiter.limit("10/minute")
async def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    data = LoginRequest(email=form_data.username, password=form_data.password)
    return auth_service.login_user(db, data)


@router.post("/login-json", response_model=Token)
@limiter.limit("10/minute")
async def login_json(request: Request, data: LoginRequest, db: Session = Depends(get_db)):
    return auth_service.login_user(db, data)


@router.get("/me", response_model=UserOut)
async def me(current_user: User = Depends(get_current_user)):
    return current_user


@router.post("/change-password", response_model=MessageResponse)
async def change_password(
    data: PasswordChange,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    auth_service.change_password(db, current_user, data.current_password, data.new_password)
    return MessageResponse(detail="Password updated successfully")


@router.post("/forgot-password", response_model=MessageResponse)
@limiter.limit("5/minute")
async def forgot_password(request: Request, data: PasswordResetRequest, db: Session = Depends(get_db)):
    auth_service.request_password_reset(db, data.email)
    return MessageResponse(detail="If the email exists, a reset link has been sent")


@router.post("/reset-password", response_model=MessageResponse)
async def reset_password(data: PasswordResetConfirm, db: Session = Depends(get_db)):
    auth_service.reset_password_with_token(db, data.token, data.new_password)
    return MessageResponse(detail="Password has been reset")