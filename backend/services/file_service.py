import os
import uuid
import aiofiles
from pathlib import Path
from fastapi import UploadFile, HTTPException, status
from sqlalchemy.orm import Session
from backend.config import settings
from backend.models import StoredFile, User

ALLOWED_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".txt", ".csv", ".png", ".jpg", ".jpeg", ".gif", ".webp",
    ".zip", ".rar", ".7z",
}


def ensure_upload_dir() -> Path:
    path = Path(settings.UPLOAD_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return path


async def save_upload(
    db: Session,
    file: UploadFile,
    uploader: User,
    task_id: int | None = None,
    project_id: int | None = None,
) -> StoredFile:
    ensure_upload_dir()

    original = file.filename or "unnamed"
    # Never trust user-supplied filename for storage
    ext = Path(original).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File type not allowed. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    content = await file.read()
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File exceeds maximum size of {settings.MAX_UPLOAD_MB} MB",
        )

    stored_name = f"{uuid.uuid4().hex}{ext}"
    dest = Path(settings.UPLOAD_DIR) / stored_name

    async with aiofiles.open(dest, "wb") as f:
        await f.write(content)

    record = StoredFile(
        original_filename=original[:500],
        stored_filename=stored_name,
        content_type=file.content_type,
        size_bytes=len(content),
        uploader_id=uploader.id,
        task_id=task_id,
        project_id=project_id,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def get_file_path(stored: StoredFile) -> Path:
    path = Path(settings.UPLOAD_DIR) / stored.stored_filename
    if not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found on disk")
    # Path traversal protection
    if not path.resolve().is_relative_to(Path(settings.UPLOAD_DIR).resolve()):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid file path")
    return path