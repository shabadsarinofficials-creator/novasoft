from datetime import datetime, date
from typing import Optional, List, Any
from pydantic import BaseModel, EmailStr, Field, ConfigDict
from backend.models import UserRole, TaskStatus, TaskPriority, ProjectStatus


# ---------- Auth ----------
class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    user_id: Optional[int] = None
    role: Optional[str] = None


class LoginRequest(BaseModel):
    # Login identifiers are matched against the existing users table.
    # Keep this as a string so internal accounts such as admin@novasoft.local
    # are accepted; EmailStr rejects reserved internal domains like .local.
    email: str = Field(..., min_length=3, max_length=255)
    password: str


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=8)


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    token: str
    new_password: str = Field(..., min_length=8)


# ---------- User ----------
class UserBase(BaseModel):
    email: EmailStr
    name: str
    role: UserRole = UserRole.EMPLOYEE
    phone: Optional[str] = None
    department: Optional[str] = None


class UserCreate(UserBase):
    password: str = Field(..., min_length=8)


class UserUpdate(BaseModel):
    name: Optional[str] = None
    role: Optional[UserRole] = None
    phone: Optional[str] = None
    department: Optional[str] = None
    is_active: Optional[bool] = None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    name: str
    role: UserRole
    is_active: bool
    phone: Optional[str] = None
    department: Optional[str] = None
    avatar_url: Optional[str] = None
    created_at: datetime
    last_login: Optional[datetime] = None


class UserBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    email: EmailStr
    role: UserRole


# ---------- Task ----------
class TaskBase(BaseModel):
    title: str
    description: Optional[str] = None
    status: TaskStatus = TaskStatus.TODO
    priority: TaskPriority = TaskPriority.NORMAL
    start_date: Optional[date] = None
    due_date: Optional[date] = None
    assignee_id: Optional[int] = None
    project_id: Optional[int] = None


class TaskCreate(TaskBase):
    pass


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[TaskStatus] = None
    priority: Optional[TaskPriority] = None
    start_date: Optional[date] = None
    due_date: Optional[date] = None
    assignee_id: Optional[int] = None
    project_id: Optional[int] = None
    feedback: Optional[str] = None


class TaskCommentCreate(BaseModel):
    body: str


class TaskCommentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    body: str
    author: UserBrief
    created_at: datetime


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    title: str
    description: Optional[str] = None
    status: TaskStatus
    priority: TaskPriority
    start_date: Optional[date] = None
    due_date: Optional[date] = None
    feedback: Optional[str] = None
    created_by_id: int
    assignee_id: Optional[int] = None
    project_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime
    creator: Optional[UserBrief] = None
    assignee: Optional[UserBrief] = None


# ---------- Project ----------
class ProjectBase(BaseModel):
    name: str
    description: Optional[str] = None
    status: ProjectStatus = ProjectStatus.PLANNING
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    manager_id: Optional[int] = None


class ProjectCreate(ProjectBase):
    member_ids: Optional[List[int]] = None


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[ProjectStatus] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    manager_id: Optional[int] = None


class ProjectMemberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user: UserBrief
    joined_at: datetime


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    description: Optional[str] = None
    status: ProjectStatus
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    manager_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime
    manager: Optional[UserBrief] = None
    members: Optional[List[ProjectMemberOut]] = None


# ---------- Announcement ----------
class AnnouncementCreate(BaseModel):
    title: str
    body: str
    target_audience: str = "all"


class AnnouncementUpdate(BaseModel):
    title: Optional[str] = None
    body: Optional[str] = None
    target_audience: Optional[str] = None
    is_active: Optional[bool] = None


class AnnouncementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    title: str
    body: str
    target_audience: str
    is_active: bool
    created_by_id: int
    created_at: datetime
    updated_at: datetime
    creator: Optional[UserBrief] = None


# ---------- Chat ----------
class ConversationCreate(BaseModel):
    title: Optional[str] = None
    is_group: bool = False
    member_ids: List[int]


class MessageCreate(BaseModel):
    body: str


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    body: str
    sender_id: int
    created_at: datetime
    sender: Optional[UserBrief] = None


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    title: Optional[str] = None
    is_group: bool
    created_at: datetime
    updated_at: datetime
    members: Optional[List[UserBrief]] = None
    last_message: Optional[MessageOut] = None
    unread_count: int = 0


# ---------- File ----------
class FileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    original_filename: str
    content_type: Optional[str] = None
    size_bytes: int
    uploader_id: int
    task_id: Optional[int] = None
    project_id: Optional[int] = None
    created_at: datetime
    uploader: Optional[UserBrief] = None


# ---------- Dashboard ----------
class DashboardStats(BaseModel):
    total_users: int
    total_employees: int
    total_managers: int
    total_tasks: int
    open_tasks: int
    completed_tasks: int
    overdue_tasks: int
    total_projects: int
    active_projects: int
    recent_tasks: List[TaskOut] = []
    recent_announcements: List[AnnouncementOut] = []


# ---------- Audit ----------
class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    actor_id: Optional[int] = None
    action: str
    target_type: Optional[str] = None
    target_id: Optional[int] = None
    meta: Optional[dict] = None
    success: bool
    created_at: datetime
    actor: Optional[UserBrief] = None


# ---------- Settings ----------
class SettingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    key: str
    value: Optional[str] = None


class SettingUpdate(BaseModel):
    value: str


# ---------- Generic ----------
class MessageResponse(BaseModel):
    detail: str


class HealthResponse(BaseModel):
    status: str
    app: str
    database: str