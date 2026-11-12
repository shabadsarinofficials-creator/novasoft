from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from typing import List
from backend.database import get_db
from backend.auth import get_current_user
from backend.models import User, Announcement, UserRole, AuditLog
from backend.schemas import AnnouncementCreate, AnnouncementUpdate, AnnouncementOut, MessageResponse
from backend.permissions import can_post_announcement

router = APIRouter(prefix="/api/announcements", tags=["announcements"])


@router.get("", response_model=List[AnnouncementOut])
async def list_announcements(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = (
        db.query(Announcement)
        .options(joinedload(Announcement.creator))
        .filter(Announcement.is_active == True)
    )
    # Filter by audience
    role = current_user.role.value
    query = query.filter(
        (Announcement.target_audience == "all")
        | (Announcement.target_audience == role)
    )
    return query.order_by(Announcement.created_at.desc()).all()


@router.post("", response_model=AnnouncementOut, status_code=201)
async def create_announcement(
    data: AnnouncementCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not can_post_announcement(current_user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    ann = Announcement(
        title=data.title,
        body=data.body,
        target_audience=data.target_audience,
        created_by_id=current_user.id,
    )
    db.add(ann)
    db.add(AuditLog(actor_id=current_user.id, action="announcement_create", target_type="announcement"))
    db.commit()
    db.refresh(ann)
    return ann


@router.patch("/{ann_id}", response_model=AnnouncementOut)
async def update_announcement(
    ann_id: int,
    data: AnnouncementUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not can_post_announcement(current_user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    ann = db.query(Announcement).filter(Announcement.id == ann_id).first()
    if not ann:
        raise HTTPException(status_code=404, detail="Announcement not found")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(ann, k, v)
    db.commit()
    db.refresh(ann)
    return ann


@router.delete("/{ann_id}", response_model=MessageResponse)
async def delete_announcement(
    ann_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not can_post_announcement(current_user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    ann = db.query(Announcement).filter(Announcement.id == ann_id).first()
    if not ann:
        raise HTTPException(status_code=404, detail="Announcement not found")
    ann.is_active = False
    db.add(AuditLog(actor_id=current_user.id, action="announcement_delete", target_type="announcement", target_id=ann_id))
    db.commit()
    return MessageResponse(detail="Announcement deleted")