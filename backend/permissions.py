"""
Centralized permission helpers. All authorization is enforced on the backend.
"""
from fastapi import HTTPException, status
from backend.models import User, UserRole, Task, Project


def is_admin(user: User) -> bool:
    return user.role == UserRole.ADMIN


def is_manager_or_admin(user: User) -> bool:
    return user.role in (UserRole.ADMIN, UserRole.MANAGER)


def can_manage_users(user: User) -> bool:
    return user.role == UserRole.ADMIN


def can_create_task(user: User) -> bool:
    return user.role in (UserRole.ADMIN, UserRole.MANAGER)


def can_edit_task(user: User, task: Task) -> bool:
    if user.role == UserRole.ADMIN:
        return True
    if user.role == UserRole.MANAGER:
        return True
    # Employee can only update status/feedback on own tasks
    return task.assignee_id == user.id


def can_delete_task(user: User) -> bool:
    return user.role in (UserRole.ADMIN, UserRole.MANAGER)


def can_manage_projects(user: User) -> bool:
    return user.role in (UserRole.ADMIN, UserRole.MANAGER)


def can_view_project(user: User, project: Project, member_ids: set[int] | None = None) -> bool:
    if user.role == UserRole.ADMIN:
        return True
    if project.manager_id == user.id:
        return True
    if member_ids and user.id in member_ids:
        return True
    return False


def can_post_announcement(user: User) -> bool:
    return user.role in (UserRole.ADMIN, UserRole.MANAGER)


def can_manage_files_all(user: User) -> bool:
    return user.role == UserRole.ADMIN


def require_admin(user: User) -> None:
    if not is_admin(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")


def require_manager_or_admin(user: User) -> None:
    if not is_manager_or_admin(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Manager or Admin required")