from typing import Optional
from datetime import datetime, timedelta
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import get_current_user, require_roles
from app.database import get_db
from app.models import (
    Agent, Category, Feedback, SLAPolicy, Ticket, TicketHistory,
    TicketPriority, TicketStatus, User, UserRole, utcnow,
)
from app.schemas import (
    FeedbackCreate, FeedbackOut, TicketAssign, TicketCreate, TicketHistoryOut,
    TicketOut, TicketPriorityUpdate, TicketStatusUpdate,
)
from app.services.assignment import auto_assign_ticket, publish_open_ticket_counts
from app.services.email_service import send_email
from app.services.notifications import queue_notification
from app.services.ticket_access import get_ticket_for_user

router = APIRouter(prefix="/tickets", tags=["Tickets"])

ACTIVE_STATUSES = [TicketStatus.OPEN, TicketStatus.ASSIGNED, TicketStatus.IN_PROGRESS, TicketStatus.WAITING_ON_CUSTOMER]
ALLOWED_TRANSITIONS = {
    TicketStatus.ASSIGNED: {TicketStatus.IN_PROGRESS},
    TicketStatus.IN_PROGRESS: {TicketStatus.WAITING_ON_CUSTOMER, TicketStatus.RESOLVED},
    TicketStatus.WAITING_ON_CUSTOMER: {TicketStatus.IN_PROGRESS, TicketStatus.RESOLVED},
    TicketStatus.RESOLVED: {TicketStatus.CLOSED},
}


@router.post("", response_model=TicketOut, status_code=status.HTTP_201_CREATED)
async def create_ticket(
    payload: TicketCreate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_roles(UserRole.CUSTOMER)),
    db: AsyncSession = Depends(get_db),
):
    category = await db.get(Category, payload.category_id)
    if category is None:
        raise HTTPException(status_code=404, detail="Category not found.")
    if not category.is_active:
        raise HTTPException(status_code=400, detail="Inactive categories cannot be used for new tickets.")
    policy = await db.scalar(select(SLAPolicy).where(SLAPolicy.priority == payload.priority, SLAPolicy.is_active.is_(True)))
    if policy is None:
        raise HTTPException(status_code=503, detail="SLA policies are not configured. Run: python -m app.seed")

    now = utcnow()
    ticket = Ticket(
        ticket_number=f"PENDING-{uuid4().hex}",
        customer_id=current_user.id,
        category_id=payload.category_id,
        subject=payload.subject.strip(),
        description=payload.description.strip(),
        priority=payload.priority,
        status=TicketStatus.OPEN,
        sla_policy_id=policy.id,
        first_response_due=now + timedelta(minutes=policy.first_response_minutes),
        resolution_due=now + timedelta(minutes=policy.resolution_minutes),
    )
    db.add(ticket)
    await db.flush()
    ticket.ticket_number = f"TKT-{now:%Y%m%d}-{ticket.id:04d}"
    db.add(TicketHistory(
        ticket_id=ticket.id, changed_by_id=current_user.id,
        old_status=None, new_status=TicketStatus.OPEN.value,
        action="CREATED", details="Ticket created by customer.",
    ))
    await auto_assign_ticket(db, ticket)
    await db.commit()
    await db.refresh(ticket)
    background_tasks.add_task(
        send_email,
        current_user.email,
        f"Support ticket created: {ticket.ticket_number}",
        f"Your ticket {ticket.ticket_number} has been created. Current status: {ticket.status.value}.",
    )
    await publish_open_ticket_counts(db)
    return ticket


@router.get("", response_model=list[TicketOut])
async def list_tickets(
    ticket_number: Optional[str] = None,
    subject: Optional[str] = None,
    status_filter: Optional[TicketStatus] = Query(default=None, alias="status"),
    priority: Optional[TicketPriority] = None,
    category_id: Optional[int] = None,
    assigned_agent_id: Optional[int] = None,
    sla_breached: Optional[bool] = None,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    sort_by: str = Query("created_at", pattern="^(created_at|priority|resolution_due|updated_at|ticket_number)$"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    statement = select(Ticket)
    if current_user.role == UserRole.CUSTOMER:
        statement = statement.where(Ticket.customer_id == current_user.id)
    elif current_user.role == UserRole.AGENT:
        agent_id = await db.scalar(select(Agent.id).where(Agent.user_id == current_user.id))
        if agent_id is None:
            return []
        statement = statement.where(Ticket.assigned_agent_id == agent_id)
    if ticket_number:
        statement = statement.where(Ticket.ticket_number == ticket_number)
    if subject:
        statement = statement.where(Ticket.subject.ilike(f"%{subject}%"))
    if status_filter:
        statement = statement.where(Ticket.status == status_filter)
    if priority:
        statement = statement.where(Ticket.priority == priority)
    if category_id is not None:
        statement = statement.where(Ticket.category_id == category_id)
    if assigned_agent_id is not None:
        statement = statement.where(Ticket.assigned_agent_id == assigned_agent_id)
    if sla_breached is not None:
        statement = statement.where(Ticket.sla_breached.is_(sla_breached))
    if from_date is not None:
        statement = statement.where(Ticket.created_at >= from_date)
    if to_date is not None:
        statement = statement.where(Ticket.created_at <= to_date)
    sort_column = getattr(Ticket, sort_by)
    statement = statement.order_by(sort_column.asc() if order == "asc" else sort_column.desc())
    result = await db.execute(statement.offset(skip).limit(limit))
    return result.scalars().all()


@router.get("/{ticket_id}", response_model=TicketOut)
async def get_ticket(ticket_id: int, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await get_ticket_for_user(db, ticket_id, current_user)


@router.put("/{ticket_id}/status", response_model=TicketOut)
async def update_ticket_status(
    ticket_id: int,
    payload: TicketStatusUpdate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.AGENT)),
    db: AsyncSession = Depends(get_db),
):
    ticket = await get_ticket_for_user(db, ticket_id, current_user)
    if ticket.status == TicketStatus.CLOSED:
        raise HTTPException(status_code=409, detail="Closed tickets cannot be updated.")
    if payload.status == ticket.status:
        return ticket
    if payload.status not in ALLOWED_TRANSITIONS.get(ticket.status, set()):
        raise HTTPException(status_code=400, detail=f"Invalid status transition: {ticket.status.value} -> {payload.status.value}.")

    now = utcnow()
    old_status = ticket.status
    if old_status == TicketStatus.WAITING_ON_CUSTOMER and ticket.waiting_started_at:
        ticket.total_waiting_seconds += max(0, int((now - ticket.waiting_started_at).total_seconds()))
        ticket.waiting_started_at = None
    if payload.status == TicketStatus.WAITING_ON_CUSTOMER:
        ticket.waiting_started_at = now
    if payload.status == TicketStatus.RESOLVED:
        ticket.resolved_at = now
    if payload.status == TicketStatus.CLOSED:
        ticket.closed_at = now
    ticket.status = payload.status
    ticket.updated_at = now
    db.add(TicketHistory(
        ticket_id=ticket.id, changed_by_id=current_user.id,
        old_status=old_status.value, new_status=payload.status.value,
        action="STATUS_CHANGED", details=f"Status changed by {current_user.role.value}.",
    ))
    notification = await queue_notification(
        db, ticket.customer_id, "Ticket status updated",
        f"Ticket {ticket.ticket_number} is now {payload.status.value}.", ticket.id,
    )
    await db.commit()
    await db.refresh(ticket)
    if payload.status == TicketStatus.RESOLVED:
        customer = await db.get(User, ticket.customer_id)
        if customer:
            background_tasks.add_task(send_email, customer.email, f"Ticket resolved: {ticket.ticket_number}", f"Your ticket {ticket.ticket_number} has been marked resolved.")
    await publish_open_ticket_counts(db)
    return ticket


@router.put("/{ticket_id}/priority", response_model=TicketOut)
async def update_ticket_priority(
    ticket_id: int,
    payload: TicketPriorityUpdate,
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.AGENT)),
    db: AsyncSession = Depends(get_db),
):
    ticket = await get_ticket_for_user(db, ticket_id, current_user)
    if ticket.status == TicketStatus.CLOSED:
        raise HTTPException(status_code=409, detail="Closed tickets cannot be updated.")
    policy = await db.scalar(select(SLAPolicy).where(SLAPolicy.priority == payload.priority, SLAPolicy.is_active.is_(True)))
    if policy is None:
        raise HTTPException(status_code=404, detail="Active SLA policy for this priority was not found.")
    old_priority = ticket.priority
    now = utcnow()
    ticket.priority = payload.priority
    ticket.sla_policy_id = policy.id
    # Priority changes start a fresh SLA window. Do not carry waiting time
    # from the previous SLA window into the newly calculated deadline.
    ticket.first_response_due = now + timedelta(minutes=policy.first_response_minutes)
    ticket.resolution_due = now + timedelta(minutes=policy.resolution_minutes)
    ticket.total_waiting_seconds = 0
    # If the ticket is currently waiting on the customer, keep waiting_started_at:
    # only the wait accrued after this new SLA window began is counted.
    db.add(TicketHistory(
        ticket_id=ticket.id, changed_by_id=current_user.id,
        old_status=ticket.status.value, new_status=ticket.status.value,
        action="PRIORITY_CHANGED", details=f"Priority changed from {old_priority.value} to {payload.priority.value}; SLA deadlines recalculated.",
    ))
    await db.commit()
    await db.refresh(ticket)
    return ticket


@router.put("/{ticket_id}/assign", response_model=TicketOut)
async def manually_assign_ticket(
    ticket_id: int,
    payload: TicketAssign,
    current_user: User = Depends(require_roles(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    ticket = await db.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found.")
    if ticket.status == TicketStatus.CLOSED:
        raise HTTPException(status_code=409, detail="Closed tickets cannot be reassigned.")
    agent = await db.get(Agent, payload.agent_id)
    if agent is None or not agent.is_active:
        raise HTTPException(status_code=404, detail="Active agent not found.")
    from app.models import agent_categories
    supports_category = await db.scalar(select(agent_categories.c.agent_id).where(agent_categories.c.agent_id == agent.id, agent_categories.c.category_id == ticket.category_id))
    if supports_category is None:
        raise HTTPException(status_code=400, detail="This agent is not configured to handle the ticket category.")
    actual_count = await db.scalar(select(func.count(Ticket.id)).where(Ticket.assigned_agent_id == agent.id, Ticket.status.in_(ACTIVE_STATUSES))) or 0
    if ticket.assigned_agent_id != agent.id and actual_count >= agent.max_open_tickets:
        raise HTTPException(status_code=409, detail="Agent has reached the maximum open-ticket capacity.")
    old_agent_id = ticket.assigned_agent_id
    old_status = ticket.status
    ticket.assigned_agent_id = agent.id
    ticket.status = TicketStatus.ASSIGNED if old_status == TicketStatus.OPEN else old_status
    ticket.assigned_at = utcnow()
    db.add(TicketHistory(
        ticket_id=ticket.id, changed_by_id=current_user.id,
        old_status=old_status.value, new_status=ticket.status.value,
        action="REASSIGNED" if old_agent_id else "MANUALLY_ASSIGNED",
        details=f"Admin assigned ticket to agent {agent.id}.",
    ))
    notifications = []
    if old_agent_id is not None and old_agent_id != agent.id:
        old_agent = await db.get(Agent, old_agent_id)
        if old_agent:
            notifications.append(await queue_notification(db, old_agent.user_id, "Ticket reassigned", f"Ticket {ticket.ticket_number} was reassigned.", ticket.id))
    if old_agent_id != agent.id:
        notifications.append(await queue_notification(db, agent.user_id, "Ticket assigned", f"Ticket {ticket.ticket_number} has been assigned to you.", ticket.id))
    await db.commit()
    await db.refresh(ticket)
    await publish_open_ticket_counts(db)
    return ticket


@router.put("/{ticket_id}/reopen", response_model=TicketOut)
async def reopen_ticket(
    ticket_id: int,
    current_user: User = Depends(require_roles(UserRole.CUSTOMER)),
    db: AsyncSession = Depends(get_db),
):
    ticket = await get_ticket_for_user(db, ticket_id, current_user)
    if ticket.status != TicketStatus.RESOLVED or ticket.resolved_at is None:
        raise HTTPException(status_code=409, detail="Only resolved tickets can be reopened.")
    if utcnow() > ticket.resolved_at + timedelta(days=7):
        raise HTTPException(status_code=400, detail="A ticket can only be reopened within 7 days of resolution.")
    if ticket.reopen_count >= 2:
        raise HTTPException(status_code=409, detail="A ticket can be reopened at most twice.")
    old_status = ticket.status
    ticket.status = TicketStatus.IN_PROGRESS
    ticket.reopen_count += 1
    ticket.resolved_at = None
    ticket.closed_at = None
    db.add(TicketHistory(
        ticket_id=ticket.id, changed_by_id=current_user.id,
        old_status=old_status.value, new_status=ticket.status.value,
        action="REOPENED", details=f"Customer reopened ticket (count {ticket.reopen_count}).",
    ))
    if ticket.assigned_agent_id is not None:
        agent = await db.get(Agent, ticket.assigned_agent_id)
        if agent:
            await queue_notification(db, agent.user_id, "Ticket reopened", f"Ticket {ticket.ticket_number} has been reopened by the customer.", ticket.id)
    await db.commit()
    await db.refresh(ticket)
    await publish_open_ticket_counts(db)
    return ticket


@router.get("/{ticket_id}/history", response_model=list[TicketHistoryOut])
async def ticket_history(
    ticket_id: int,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_ticket_for_user(db, ticket_id, current_user)
    result = await db.execute(select(TicketHistory).where(TicketHistory.ticket_id == ticket_id).order_by(TicketHistory.created_at.asc()).offset(skip).limit(limit))
    return result.scalars().all()


@router.post("/{ticket_id}/feedback", response_model=FeedbackOut, status_code=status.HTTP_201_CREATED)
async def submit_feedback(
    ticket_id: int,
    payload: FeedbackCreate,
    current_user: User = Depends(require_roles(UserRole.CUSTOMER)),
    db: AsyncSession = Depends(get_db),
):
    ticket = await get_ticket_for_user(db, ticket_id, current_user)
    if ticket.status not in (TicketStatus.RESOLVED, TicketStatus.CLOSED):
        raise HTTPException(status_code=400, detail="Feedback is allowed only for resolved or closed tickets.")
    if await db.scalar(select(Feedback.id).where(Feedback.ticket_id == ticket_id)) is not None:
        raise HTTPException(status_code=409, detail="Feedback has already been submitted for this ticket.")
    feedback = Feedback(ticket_id=ticket_id, customer_id=current_user.id, rating=payload.rating, comment=payload.comment)
    db.add(feedback)
    try:
        await db.commit()
        await db.refresh(feedback)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Feedback has already been submitted for this ticket.")
    return feedback


@router.get("/{ticket_id}/feedback", response_model=FeedbackOut)
async def get_feedback(
    ticket_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ticket = await get_ticket_for_user(db, ticket_id, current_user)
    feedback = await db.scalar(select(Feedback).where(Feedback.ticket_id == ticket_id))
    if feedback is None:
        raise HTTPException(status_code=404, detail="No feedback found for this ticket.")
    return feedback
