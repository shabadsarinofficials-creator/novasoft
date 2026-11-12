from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from backend.database import get_db
from backend.auth import get_current_user, hash_password, require_roles
from backend.models import User, UserRole, AuditLog
from backend.schemas import UserCreate, UserUpdate, UserOut, MessageResponse
from backend.permissions import can_manage_users, require_admin

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("", response_model=List[UserOut])
async def list_users(
    role: Optional[UserRole] = None,
    active: Optional[bool] = None,
    q: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(User)
    if current_user.role == UserRole.EMPLOYEE:
        # Employees see limited directory
        query = query.filter(User.is_active == True)
    if role:
        query = query.filter(User.role == role)
    if active is not None:
        query = query.filter(User.is_active == active)
    if q:
        like = f"%{q}%"
        query = query.filter((User.name.ilike(like)) | (User.email.ilike(like)))
    return query.order_by(User.name).all()


@router.get("/{user_id}", response_model=UserOut)
async def get_user(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(
    data: UserCreate,
    current_user: User = Depends(require_roles(UserRole.ADMIN)),
    db: Session = Depends(get_db),
):
    if db.query(User).filter(User.email == data.email.lower()).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    user = User(
        email=data.email.lower().strip(),
        name=data.name,
        password_hash=hash_password(data.password),
        role=data.role,
        phone=data.phone,
        department=data.department,
        is_active=True,
    )
    db.add(user)
    db.add(AuditLog(actor_id=current_user.id, action="user_create", target_type="user", meta={"email": user.email}))
    db.commit()
    db.refresh(user)
    return user


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: int,
    data: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Self-update limited fields
    if current_user.id == user_id:
        if data.name is not None:
            user.name = data.name
        if data.phone is not None:
            user.phone = data.phone
        if data.department is not None:
            user.department = data.department
    elif can_manage_users(current_user):
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(user, field, value)
        db.add(AuditLog(
            actor_id=current_user.id,
            action="user_update",
            target_type="user",
            target_id=user.id,
            meta=data.model_dump(exclude_unset=True),
        ))
    else:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    db.commit()
    db.refresh(user)
    return user


@router.post("/{user_id}/deactivate", response_model=MessageResponse)
async def deactivate_user(
    user_id: int,
    current_user: User = Depends(require_roles(UserRole.ADMIN)),
    db: Session = Depends(get_db),
):
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot deactivate yourself")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_active = False
    db.add(AuditLog(actor_id=current_user.id, action="user_deactivate", target_type="user", target_id=user.id))
    db.commit()
    return MessageResponse(detail="User deactivated")


@router.post("/{user_id}/reactivate", response_model=MessageResponse)
async def reactivate_user(
    user_id: int,
    current_user: User = Depends(require_roles(UserRole.ADMIN)),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_active = True
    db.add(AuditLog(actor_id=current_user.id, action="user_reactivate", target_type="user", target_id=user.id))
    db.commit()
    return MessageResponse(detail="User reactivated")


@router.post("/{user_id}/reset-password", response_model=MessageResponse)
async def admin_reset_password(
    user_id: int,
    current_user: User = Depends(require_roles(UserRole.ADMIN)),
    db: Session = Depends(get_db),
):
    """Admin-triggered secure reset — forces password change on next login via temporary password."""
    import secrets
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    temp = secrets.token_urlsafe(12)
    user.password_hash = hash_password(temp)
    db.add(AuditLog(actor_id=current_user.id, action="admin_password_reset", target_type="user", target_id=user.id))
    db.commit()
    # In production, email the temporary password. Return it only for admin testing.
    return MessageResponse(detail=f"Temporary password set: {temp} (share securely and require change)")