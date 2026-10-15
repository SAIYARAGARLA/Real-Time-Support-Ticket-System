from typing import Optional
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models import AgentAvailability, TicketPriority, TicketStatus, UserRole


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class UserRegister(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    phone: Optional[str] = Field(default=None, max_length=30)
    password: str = Field(min_length=8, max_length=72)

    @field_validator("full_name")
    @classmethod
    def normalize_full_name(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise ValueError("Full name must contain at least two non-space characters.")
        return value


class UserLogin(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=72)


class UserOut(ORMModel):
    id: int
    full_name: str
    email: EmailStr
    phone: Optional[str] = None
    role: UserRole
    is_active: bool
    created_at: datetime


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class AdminCreate(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)

    @field_validator("full_name")
    @classmethod
    def normalize_full_name(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise ValueError("Full name must contain at least two non-space characters.")
        return value


class AgentCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    category_ids: list[int] = Field(default_factory=list)
    max_open_tickets: int = Field(default=10, ge=1, le=500)
    availability: AgentAvailability = AgentAvailability.OFFLINE


class AgentUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=120)
    email: Optional[EmailStr] = None
    category_ids: Optional[list[int]] = None
    max_open_tickets: Optional[int] = Field(default=None, ge=1, le=500)
    availability: Optional[AgentAvailability] = None
    is_active: Optional[bool] = None


class AgentOut(BaseModel):
    id: int
    user_id: int
    name: str
    email: EmailStr
    category_ids: list[int]
    categories: list[str]
    availability: AgentAvailability
    max_open_tickets: int
    is_active: bool
    created_at: datetime


class AvailabilityUpdate(BaseModel):
    availability: AgentAvailability


class CategoryCreate(BaseModel):
    category_name: str = Field(min_length=2, max_length=100)
    description: Optional[str] = Field(default=None, max_length=2000)
    is_active: bool = True


class CategoryUpdate(BaseModel):
    category_name: Optional[str] = Field(default=None, min_length=2, max_length=100)
    description: Optional[str] = Field(default=None, max_length=2000)
    is_active: Optional[bool] = None


class CategoryOut(ORMModel):
    id: int
    category_name: str
    description: Optional[str]
    is_active: bool
    created_at: datetime
    updated_at: datetime


class SLAPolicyOut(ORMModel):
    id: int
    name: str
    priority: TicketPriority
    first_response_minutes: int
    resolution_minutes: int
    escalation_minutes: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class SLAPolicyUpdate(BaseModel):
    first_response_minutes: int = Field(gt=0, le=525600)
    resolution_minutes: int = Field(gt=0, le=525600)
    escalation_minutes: int = Field(default=5, gt=0, le=10080)
    is_active: bool = True


class TicketCreate(BaseModel):
    category_id: int
    subject: str = Field(min_length=5, max_length=150)
    description: str = Field(min_length=10, max_length=10000)
    priority: TicketPriority = TicketPriority.MEDIUM

    @field_validator("subject")
    @classmethod
    def normalize_subject(cls, value: str) -> str:
        value = value.strip()
        if not 5 <= len(value) <= 150:
            raise ValueError("Subject must contain between 5 and 150 characters.")
        return value

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 10:
            raise ValueError("Description must contain at least 10 characters.")
        return value


class TicketStatusUpdate(BaseModel):
    status: TicketStatus


class TicketPriorityUpdate(BaseModel):
    priority: TicketPriority


class TicketAssign(BaseModel):
    agent_id: int


class TicketOut(ORMModel):
    id: int
    ticket_number: str
    customer_id: int
    category_id: int
    subject: str
    description: str
    priority: TicketPriority
    status: TicketStatus
    assigned_agent_id: Optional[int]
    sla_policy_id: int
    first_response_due: datetime
    resolution_due: datetime
    first_response_at: Optional[datetime]
    resolved_at: Optional[datetime]
    closed_at: Optional[datetime]
    sla_breached: bool
    first_response_breached: bool
    resolution_breached: bool
    reopen_count: int
    total_waiting_seconds: int
    created_at: datetime
    updated_at: datetime


class TicketHistoryOut(ORMModel):
    id: int
    ticket_id: int
    changed_by_id: Optional[int]
    old_status: Optional[str]
    new_status: Optional[str]
    action: str
    details: Optional[str]
    created_at: datetime


class MessageCreate(BaseModel):
    message: str = Field(min_length=1, max_length=1999)
    is_internal_note: bool = False

    @field_validator("message")
    @classmethod
    def normalize_message(cls, value: str) -> str:
        value = value.strip()
        if not value or len(value) >= 2000:
            raise ValueError("Message must contain 1 to 1999 non-space characters.")
        return value


class MessageOut(ORMModel):
    id: int
    ticket_id: int
    sender_id: int
    sender_role: str
    message: str
    is_internal_note: bool
    is_read: bool
    attachment_path: Optional[str]
    created_at: datetime


class FeedbackCreate(BaseModel):
    rating: int = Field(ge=1, le=5)
    comment: Optional[str] = Field(default=None, max_length=4000)


class FeedbackOut(ORMModel):
    id: int
    ticket_id: int
    customer_id: int
    rating: int
    comment: Optional[str]
    created_at: datetime


class NotificationOut(ORMModel):
    id: int
    user_id: int
    ticket_id: Optional[int]
    title: str
    message: str
    is_read: bool
    created_at: datetime
