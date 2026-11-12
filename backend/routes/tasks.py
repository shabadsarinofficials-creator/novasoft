from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from typing import List, Optional
from backend.database import get_db
from backend.auth import get_current_user, require_roles
from backend.models import User, Task, TaskComment, TaskStatus, TaskPriority, UserRole, AuditLog
from backend.schemas import (
    TaskCreate, TaskUpdate, TaskOut, TaskCommentCreate, TaskCommentOut, MessageResponse,
)
from backend.permissions import can_create_task, can_edit_task, can_delete_task

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.get("", response_model=List[TaskOut])
async def list_tasks(
    status: Optional[TaskStatus] = None,
    priority: Optional[TaskPriority] = None,
    assignee_id: Optional[int] = None,
    project_id: Optional[int] = None,
    overdue: Optional[bool] = None,
    q: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(Task).options(
        joinedload(Task.creator),
        joinedload(Task.assignee),
    )
    if current_user.role == UserRole.EMPLOYEE:
        query = query.filter(Task.assignee_id == current_user.id)
    if status:
        query = query.filter(Task.status == status)
    if priority:
        query = query.filter(Task.priority == priority)
    if assignee_id:
        query = query.filter(Task.assignee_id == assignee_id)
    if project_id:
        query = query.filter(Task.project_id == project_id)
    if overdue:
        query = query.filter(
            Task.due_date < date.today(),
            Task.status.notin_([TaskStatus.COMPLETED]),
        )
    if q:
        like = f"%{q}%"
        query = query.filter(Task.title.ilike(like) | Task.description.ilike(like))
    return query.order_by(Task.due_date.nullslast(), Task.created_at.desc()).all()


@router.get("/{task_id}", response_model=TaskOut)
async def get_task(
    task_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    task = (
        db.query(Task)
        .options(joinedload(Task.creator), joinedload(Task.assignee))
        .filter(Task.id == task_id)
        .first()
    )
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if current_user.role == UserRole.EMPLOYEE and task.assignee_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not allowed to view this task")
    return task


@router.post("", response_model=TaskOut, status_code=201)
async def create_task(
    data: TaskCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not can_create_task(current_user):
        raise HTTPException(status_code=403, detail="Only managers and admins can create tasks")
    task = Task(**data.model_dump(), created_by_id=current_user.id)
    db.add(task)
    db.add(AuditLog(actor_id=current_user.id, action="task_create", target_type="task", meta={"title": task.title}))
    db.commit()
    db.refresh(task)
    return task


@router.patch("/{task_id}", response_model=TaskOut)
async def update_task(
    task_id: int,
    data: TaskUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if not can_edit_task(current_user, task):
        raise HTTPException(status_code=403, detail="Cannot edit this task")

    # Employees limited to status + feedback
    if current_user.role == UserRole.EMPLOYEE:
        allowed = {"status", "feedback"}
        updates = {k: v for k, v in data.model_dump(exclude_unset=True).items() if k in allowed}
    else:
        updates = data.model_dump(exclude_unset=True)

    for k, v in updates.items():
        setattr(task, k, v)
    db.add(AuditLog(actor_id=current_user.id, action="task_update", target_type="task", target_id=task.id, meta=updates))
    db.commit()
    db.refresh(task)
    return task


@router.delete("/{task_id}", response_model=MessageResponse)
async def delete_task(
    task_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not can_delete_task(current_user):
        raise HTTPException(status_code=403, detail="Cannot delete tasks")
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    db.delete(task)
    db.add(AuditLog(actor_id=current_user.id, action="task_delete", target_type="task", target_id=task_id))
    db.commit()
    return MessageResponse(detail="Task deleted")


@router.get("/{task_id}/comments", response_model=List[TaskCommentOut])
async def list_comments(
    task_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return (
        db.query(TaskComment)
        .options(joinedload(TaskComment.author))
        .filter(TaskComment.task_id == task_id)
        .order_by(TaskComment.created_at)
        .all()
    )


@router.post("/{task_id}/comments", response_model=TaskCommentOut, status_code=201)
async def add_comment(
    task_id: int,
    data: TaskCommentCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    comment = TaskComment(task_id=task_id, author_id=current_user.id, body=data.body)
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return comment