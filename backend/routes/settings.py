from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from backend.database import get_db
from backend.auth import get_current_user, require_roles
from backend.models import User, Setting, UserRole, AuditLog
from backend.schemas import SettingOut, SettingUpdate, MessageResponse

router = APIRouter(prefix="/api/settings", tags=["settings"])

DEFAULT_SETTINGS = {
    "workspace_name": "BizSuite",
    "allow_employee_uploads": "true",
    "default_task_priority": "normal",
}


@router.get("", response_model=List[SettingOut])
async def list_settings(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Ensure defaults exist
    for key, value in DEFAULT_SETTINGS.items():
        if not db.query(Setting).filter(Setting.key == key).first():
            db.add(Setting(key=key, value=value))
    db.commit()
    return db.query(Setting).order_by(Setting.key).all()


@router.put("/{key}", response_model=SettingOut)
async def update_setting(
    key: str,
    data: SettingUpdate,
    current_user: User = Depends(require_roles(UserRole.ADMIN)),
    db: Session = Depends(get_db),
):
    setting = db.query(Setting).filter(Setting.key == key).first()
    if not setting:
        setting = Setting(key=key, value=data.value)
        db.add(setting)
    else:
        setting.value = data.value
    db.add(AuditLog(actor_id=current_user.id, action="setting_update", meta={"key": key}))
    db.commit()
    db.refresh(setting)
    return setting