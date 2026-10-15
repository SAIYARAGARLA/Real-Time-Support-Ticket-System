from typing import Optional
from datetime import datetime

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Agent,
    AgentAvailability,
    Ticket,
    TicketHistory,
    TicketStatus,
    User,
    UserRole,
)
from app.models import agent_categories
from app.services.notifications import queue_notification

OPEN_STATUSES = [TicketStatus.OPEN, TicketStatus.ASSIGNED, TicketStatus.IN_PROGRESS, TicketStatus.WAITING_ON_CUSTOMER]


async def choose_agent(db: AsyncSession, category_id: int) -> Optional[Agent]:
    open_count = func.count(Ticket.id)
    statement = (
        select(Agent, open_count.label("open_count"))
        .join(agent_categories, agent_categories.c.agent_id == Agent.id)
        .outerjoin(
            Ticket,
            and_(Ticket.assigned_agent_id == Agent.id, Ticket.status.in_(OPEN_STATUSES)),
        )
        .where(
            agent_categories.c.category_id == category_id,
            Agent.availability == AgentAvailability.ONLINE,
            Agent.is_active.is_(True),
        )
        .group_by(Agent.id)
        .order_by(open_count.asc(), Agent.id.asc())
    )
    rows = (await db.execute(statement)).all()
    for agent, current_open_count in rows:
        if current_open_count < agent.max_open_tickets:
            return agent
    return None


async def auto_assign_ticket(db: AsyncSession, ticket: Ticket) -> Optional[Agent]:
    if ticket.status not in (TicketStatus.OPEN, TicketStatus.ASSIGNED):
        return None
    agent = await choose_agent(db, ticket.category_id)
    if agent is None:
        return None

    old_agent_id = ticket.assigned_agent_id
    old_status = ticket.status.value
    ticket.assigned_agent_id = agent.id
    ticket.status = TicketStatus.ASSIGNED
    ticket.assigned_at = datetime.utcnow()
    db.add(
        TicketHistory(
            ticket_id=ticket.id,
            changed_by_id=None,
            old_status=old_status,
            new_status=TicketStatus.ASSIGNED.value,
            action="AUTO_ASSIGNED" if old_agent_id is None else "REASSIGNED",
            details=f"Ticket assigned to agent {agent.id} by automatic assignment.",
        )
    )
    await queue_notification(
        db,
        agent.user_id,
        "Ticket assigned",
        f"Ticket {ticket.ticket_number} has been assigned to you.",
        ticket.id,
    )
    if old_agent_id is not None and old_agent_id != agent.id:
        old_agent = await db.get(Agent, old_agent_id)
        if old_agent is not None:
            await queue_notification(
                db,
                old_agent.user_id,
                "Ticket reassigned",
                f"Ticket {ticket.ticket_number} has been reassigned to another agent.",
                ticket.id,
            )
    return agent


async def assign_waiting_tickets(db: AsyncSession) -> list[Ticket]:
    result = await db.execute(
        select(Ticket)
        .where(Ticket.status == TicketStatus.OPEN, Ticket.assigned_agent_id.is_(None))
        .order_by(Ticket.created_at.asc(), Ticket.id.asc())
    )
    tickets = list(result.scalars().all())
    assigned: list[Ticket] = []
    for ticket in tickets:
        agent = await auto_assign_ticket(db, ticket)
        if agent is not None:
            assigned.append(ticket)
    return assigned


async def publish_open_ticket_counts(db: AsyncSession) -> None:
    from app.websockets.manager import notification_manager

    rows = (
        await db.execute(
            select(Agent.user_id, func.count(Ticket.id))
            .outerjoin(
                Ticket,
                and_(Ticket.assigned_agent_id == Agent.id, Ticket.status.in_(OPEN_STATUSES)),
            )
            .where(Agent.is_active.is_(True))
            .group_by(Agent.id, Agent.user_id)
        )
    ).all()
    for user_id, count in rows:
        await notification_manager.send_to_user(
            user_id, {"type": "open_ticket_count", "count": int(count)}
        )

    admin_rows = await db.execute(select(User.id).where(User.role == UserRole.ADMIN, User.is_active.is_(True)))
    admin_ids = [row[0] for row in admin_rows.all()]
    admin_count = await db.scalar(select(func.count(Ticket.id)).where(Ticket.status.in_(OPEN_STATUSES))) or 0
    for user_id in admin_ids:
        await notification_manager.send_to_user(
            user_id, {"type": "open_ticket_count", "count": int(admin_count)}
        )
