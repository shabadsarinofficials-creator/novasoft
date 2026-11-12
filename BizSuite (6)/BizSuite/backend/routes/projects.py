from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from typing import List, Optional
from backend.database import get_db
from backend.auth import get_current_user
from backend.models import User, Project, ProjectMember, UserRole, AuditLog
from backend.schemas import ProjectCreate, ProjectUpdate, ProjectOut, MessageResponse
from backend.permissions import can_manage_projects

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.get("", response_model=List[ProjectOut])
async def list_projects(
    status: Optional[str] = None,
    q: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(Project).options(
        joinedload(Project.manager),
        joinedload(Project.members).joinedload(ProjectMember.user),
    )
    if current_user.role == UserRole.EMPLOYEE:
        # Only projects where user is member or manager
        member_project_ids = (
            db.query(ProjectMember.project_id)
            .filter(ProjectMember.user_id == current_user.id)
            .subquery()
        )
        query = query.filter(
            (Project.manager_id == current_user.id) | (Project.id.in_(member_project_ids))
        )
    if status:
        query = query.filter(Project.status == status)
    if q:
        like = f"%{q}%"
        query = query.filter(Project.name.ilike(like) | Project.description.ilike(like))
    return query.order_by(Project.created_at.desc()).all()


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(
    project_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project = (
        db.query(Project)
        .options(
            joinedload(Project.manager),
            joinedload(Project.members).joinedload(ProjectMember.user),
        )
        .filter(Project.id == project_id)
        .first()
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.post("", response_model=ProjectOut, status_code=201)
async def create_project(
    data: ProjectCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not can_manage_projects(current_user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    member_ids = data.member_ids or []
    payload = data.model_dump(exclude={"member_ids"})
    project = Project(**payload)
    if not project.manager_id:
        project.manager_id = current_user.id
    db.add(project)
    db.flush()
    for uid in set(member_ids):
        db.add(ProjectMember(project_id=project.id, user_id=uid))
    db.add(AuditLog(actor_id=current_user.id, action="project_create", target_type="project", meta={"name": project.name}))
    db.commit()
    db.refresh(project)
    return project


@router.patch("/{project_id}", response_model=ProjectOut)
async def update_project(
    project_id: int,
    data: ProjectUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not can_manage_projects(current_user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(project, k, v)
    db.add(AuditLog(actor_id=current_user.id, action="project_update", target_type="project", target_id=project.id))
    db.commit()
    db.refresh(project)
    return project


@router.post("/{project_id}/members/{user_id}", response_model=MessageResponse)
async def add_member(
    project_id: int,
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not can_manage_projects(current_user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    existing = (
        db.query(ProjectMember)
        .filter(ProjectMember.project_id == project_id, ProjectMember.user_id == user_id)
        .first()
    )
    if existing:
        return MessageResponse(detail="Already a member")
    db.add(ProjectMember(project_id=project_id, user_id=user_id))
    db.commit()
    return MessageResponse(detail="Member added")


@router.delete("/{project_id}/members/{user_id}", response_model=MessageResponse)
async def remove_member(
    project_id: int,
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not can_manage_projects(current_user):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    member = (
        db.query(ProjectMember)
        .filter(ProjectMember.project_id == project_id, ProjectMember.user_id == user_id)
        .first()
    )
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    db.delete(member)
    db.commit()
    return MessageResponse(detail="Member removed")