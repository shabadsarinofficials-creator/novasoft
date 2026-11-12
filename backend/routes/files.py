from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session, joinedload
from typing import List, Optional
from backend.database import get_db
from backend.auth import get_current_user
from backend.models import User, StoredFile, UserRole, AuditLog
from backend.schemas import FileOut, MessageResponse
from backend.services.file_service import save_upload, get_file_path

router = APIRouter(prefix="/api/files", tags=["files"])


@router.get("", response_model=List[FileOut])
async def list_files(
    task_id: Optional[int] = None,
    project_id: Optional[int] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(StoredFile).options(joinedload(StoredFile.uploader))
    if current_user.role == UserRole.EMPLOYEE:
        query = query.filter(StoredFile.uploader_id == current_user.id)
    if task_id:
        query = query.filter(StoredFile.task_id == task_id)
    if project_id:
        query = query.filter(StoredFile.project_id == project_id)
    return query.order_by(StoredFile.created_at.desc()).all()


@router.post("/upload", response_model=FileOut, status_code=201)
async def upload_file(
    file: UploadFile = File(...),
    task_id: Optional[int] = Form(None),
    project_id: Optional[int] = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    record = await save_upload(db, file, current_user, task_id=task_id, project_id=project_id)
    db.add(AuditLog(
        actor_id=current_user.id,
        action="file_upload",
        target_type="file",
        target_id=record.id,
        meta={"filename": record.original_filename},
    ))
    db.commit()
    return record


@router.get("/{file_id}/download")
async def download_file(
    file_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    stored = db.query(StoredFile).filter(StoredFile.id == file_id).first()
    if not stored:
        raise HTTPException(status_code=404, detail="File not found")
    # Basic access: owner, admin, or anyone if attached to shared resources
    if current_user.role == UserRole.EMPLOYEE and stored.uploader_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    path = get_file_path(stored)
    return FileResponse(
        path,
        filename=stored.original_filename,
        media_type=stored.content_type or "application/octet-stream",
    )


@router.delete("/{file_id}", response_model=MessageResponse)
async def delete_file(
    file_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    stored = db.query(StoredFile).filter(StoredFile.id == file_id).first()
    if not stored:
        raise HTTPException(status_code=404, detail="File not found")
    if current_user.role != UserRole.ADMIN and stored.uploader_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    path = get_file_path(stored)
    try:
        path.unlink(missing_ok=True)
    except Exception:
        pass
    db.delete(stored)
    db.commit()
    return MessageResponse(detail="File deleted")