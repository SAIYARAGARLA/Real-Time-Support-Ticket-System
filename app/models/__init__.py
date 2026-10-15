from typing import Optional
from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    return datetime.utcnow()


def enum_values(enum_class):
    return [item.value for item in enum_class]


class UserRole(str, PyEnum):
    ADMIN = "Admin"
    AGENT = "Agent"
    CUSTOMER = "Customer"


class AgentAvailability(str, PyEnum):
    ONLINE = "Online"
    OFFLINE = "Offline"


class TicketPriority(str, PyEnum):
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"
    URGENT = "Urgent"


class TicketStatus(str, PyEnum):
    OPEN = "Open"
    ASSIGNED = "Assigned"
    IN_PROGRESS = "In Progress"
    WAITING_ON_CUSTOMER = "Waiting on Customer"
    RESOLVED = "Resolved"
    CLOSED = "Closed"


agent_categories = Table(
    "agent_categories",
    Base.metadata,
    Column("agent_id", ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True),
    Column("category_id", ForeignKey("categories.id", ondelete="CASCADE"), primary_key=True),
    Column("created_at", DateTime, default=utcnow, nullable=False),
    Column("updated_at", DateTime, default=utcnow, onupdate=utcnow, nullable=False),
)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    phone: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        SAEnum(UserRole, values_callable=enum_values, name="user_role"),
        default=UserRole.CUSTOMER,
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    agent_profile: Mapped[Optional["Agent"]] = relationship(back_populates="user", uselist=False)
    created_tickets: Mapped[list["Ticket"]] = relationship(
        back_populates="customer", foreign_keys="Ticket.customer_id"
    )
    messages: Mapped[list["Message"]] = relationship(back_populates="sender")
    history_changes: Mapped[list["TicketHistory"]] = relationship(back_populates="changed_by")
    feedback_entries: Mapped[list["Feedback"]] = relationship(back_populates="customer")
    notifications: Mapped[list["Notification"]] = relationship(back_populates="user")


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    category_name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    agents: Mapped[list["Agent"]] = relationship(secondary=agent_categories, back_populates="categories")
    tickets: Mapped[list["Ticket"]] = relationship(back_populates="category")


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    availability: Mapped[AgentAvailability] = mapped_column(
        SAEnum(AgentAvailability, values_callable=enum_values, name="agent_availability"),
        default=AgentAvailability.OFFLINE,
        nullable=False,
    )
    max_open_tickets: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    user: Mapped["User"] = relationship(back_populates="agent_profile")
    categories: Mapped[list["Category"]] = relationship(secondary=agent_categories, back_populates="agents")
    tickets: Mapped[list["Ticket"]] = relationship(back_populates="assigned_agent", foreign_keys="Ticket.assigned_agent_id")


class SLAPolicy(Base):
    __tablename__ = "sla_policies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    priority: Mapped[TicketPriority] = mapped_column(
        SAEnum(TicketPriority, values_callable=enum_values, name="sla_priority"),
        unique=True,
        nullable=False,
    )
    first_response_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    resolution_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    escalation_minutes: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    __table_args__ = (
        CheckConstraint("first_response_minutes > 0", name="ck_sla_response_positive"),
        CheckConstraint("resolution_minutes > 0", name="ck_sla_resolution_positive"),
        CheckConstraint("escalation_minutes > 0", name="ck_sla_escalation_positive"),
    )
    tickets: Mapped[list["Ticket"]] = relationship(back_populates="sla_policy")


class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    ticket_number: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)
    customer_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"), nullable=False)
    subject: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[TicketPriority] = mapped_column(
        SAEnum(TicketPriority, values_callable=enum_values, name="ticket_priority"),
        default=TicketPriority.MEDIUM,
        nullable=False,
    )
    status: Mapped[TicketStatus] = mapped_column(
        SAEnum(TicketStatus, values_callable=enum_values, name="ticket_status"),
        default=TicketStatus.OPEN,
        nullable=False,
    )
    assigned_agent_id: Mapped[Optional[int]] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"), index=True, nullable=True)
    sla_policy_id: Mapped[int] = mapped_column(ForeignKey("sla_policies.id"), nullable=False)
    first_response_due: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    resolution_due: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    first_response_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    sla_breached: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    first_response_breached: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    resolution_breached: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    first_response_escalated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    resolution_escalated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reopen_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    waiting_started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    total_waiting_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    assigned_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    customer: Mapped["User"] = relationship(back_populates="created_tickets", foreign_keys=[customer_id])
    category: Mapped["Category"] = relationship(back_populates="tickets")
    assigned_agent: Mapped[Optional["Agent"]] = relationship(back_populates="tickets", foreign_keys=[assigned_agent_id])
    sla_policy: Mapped["SLAPolicy"] = relationship(back_populates="tickets")
    messages: Mapped[list["Message"]] = relationship(back_populates="ticket", cascade="all, delete-orphan")
    history: Mapped[list["TicketHistory"]] = relationship(back_populates="ticket", cascade="all, delete-orphan")
    feedback: Mapped[Optional["Feedback"]] = relationship(back_populates="ticket", uselist=False, cascade="all, delete-orphan")
    notifications: Mapped[list["Notification"]] = relationship(back_populates="ticket")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"), index=True, nullable=False)
    sender_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    sender_role: Mapped[str] = mapped_column(String(20), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    is_internal_note: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    attachment_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    ticket: Mapped["Ticket"] = relationship(back_populates="messages")
    sender: Mapped["User"] = relationship(back_populates="messages")


class TicketHistory(Base):
    __tablename__ = "ticket_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"), index=True, nullable=False)
    changed_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    old_status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    new_status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    ticket: Mapped["Ticket"] = relationship(back_populates="history")
    changed_by: Mapped[Optional["User"]] = relationship(back_populates="history_changes")


class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"), unique=True, nullable=False)
    customer_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    __table_args__ = (CheckConstraint("rating >= 1 AND rating <= 5", name="ck_feedback_rating_range"),)
    ticket: Mapped["Ticket"] = relationship(back_populates="feedback")
    customer: Mapped["User"] = relationship(back_populates="feedback_entries")


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    ticket_id: Mapped[Optional[int]] = mapped_column(ForeignKey("tickets.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str] = mapped_column(String(150), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    user: Mapped["User"] = relationship(back_populates="notifications")
    ticket: Mapped[Optional["Ticket"]] = relationship(back_populates="notifications")


__all__ = [
    "UserRole", "AgentAvailability", "TicketPriority", "TicketStatus",
    "User", "Category", "Agent", "SLAPolicy", "Ticket", "Message",
    "TicketHistory", "Feedback", "Notification", "agent_categories", "utcnow",
]
