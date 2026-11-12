from datetime import date
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func
from backend.database import get_db
from backend.auth import get_current_user
from backend.models import User, Task, Project, Announcement, UserRole, TaskStatus, ProjectStatus
from backend.schemas import DashboardStats, TaskOut, AnnouncementOut

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/stats", response_model=DashboardStats)
async def get_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    total_users = db.query(User).count()
    total_employees = db.query(User).filter(User.role == UserRole.EMPLOYEE).count()
    total_managers = db.query(User).filter(User.role == UserRole.MANAGER).count()
    total_tasks = db.query(Task).count()
    open_tasks = db.query(Task).filter(Task.status != TaskStatus.COMPLETED).count()
    completed_tasks = db.query(Task).filter(Task.status == TaskStatus.COMPLETED).count()
    overdue_tasks = (
        db.query(Task)
        .filter(
            Task.due_date < date.today(),
            Task.status != TaskStatus.COMPLETED,
        )
        .count()
    )
    total_projects = db.query(Project).count()
    active_projects = db.query(Project).filter(Project.status == ProjectStatus.ACTIVE).count()

    recent_tasks = (
        db.query(Task)
        .options(joinedload(Task.creator), joinedload(Task.assignee))
        .order_by(Task.created_at.desc())
        .limit(5)
        .all()
    )
    recent_announcements = (
        db.query(Announcement)
        .options(joinedload(Announcement.creator))
        .filter(Announcement.is_active == True)
        .order_by(Announcement.created_at.desc())
        .limit(5)
        .all()
    )

    return DashboardStats(
        total_users=total_users,
        total_employees=total_employees,
        total_managers=total_managers,
        total_tasks=total_tasks,
        open_tasks=open_tasks,
        completed_tasks=completed_tasks,
        overdue_tasks=overdue_tasks,
        total_projects=total_projects,
        active_projects=active_projects,
        recent_tasks=[TaskOut.model_validate(t) for t in recent_tasks],
        recent_announcements=[AnnouncementOut.model_validate(a) for a in recent_announcements],
    )