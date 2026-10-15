from typing import Optional
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import require_roles
from app.database import get_db
from app.models import Agent, AgentAvailability, Category, Feedback, SLAPolicy, Ticket, TicketPriority, TicketStatus, User, UserRole

router = APIRouter(prefix="/reports", tags=["Reports & Dashboard"])


@router.get("/dashboard")
async def dashboard(db: AsyncSession = Depends(get_db), _admin: User = Depends(require_roles(UserRole.ADMIN))):
    total = await db.scalar(select(func.count(Ticket.id))) or 0
    rows = await db.execute(select(Ticket.status, func.count(Ticket.id)).group_by(Ticket.status))
    by_status = {status.value: count for status, count in rows.all()}
    unassigned = await db.scalar(select(func.count(Ticket.id)).where(Ticket.assigned_agent_id.is_(None), Ticket.status.in_([TicketStatus.OPEN, TicketStatus.ASSIGNED, TicketStatus.IN_PROGRESS, TicketStatus.WAITING_ON_CUSTOMER]))) or 0
    breached = await db.scalar(select(func.count(Ticket.id)).where(Ticket.sla_breached.is_(True))) or 0
    online = await db.scalar(select(func.count(Agent.id)).where(Agent.availability == AgentAvailability.ONLINE, Agent.is_active.is_(True))) or 0
    return {"total_tickets": total, "tickets_by_status": by_status, "unassigned_tickets": unassigned, "sla_breached_tickets": breached, "agents_online": online}


@router.get("/agent-performance")
async def agent_performance(
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_roles(UserRole.ADMIN)),
):
    agents = list((await db.scalars(select(Agent).order_by(Agent.id))).all())
    output = []
    for agent in agents:
        statement = select(Ticket).where(Ticket.assigned_agent_id == agent.id)
        if from_date:
            statement = statement.where(Ticket.created_at >= from_date)
        if to_date:
            statement = statement.where(Ticket.created_at <= to_date)
        tickets = list((await db.scalars(statement)).all())
        resolved = [t for t in tickets if t.resolved_at is not None]
        first_response_minutes = [max(0, (t.first_response_at - t.created_at).total_seconds() / 60) for t in tickets if t.first_response_at]
        resolution_hours = [max(0, (t.resolved_at - t.created_at).total_seconds() / 3600) for t in resolved]
        rating_statement = select(func.avg(Feedback.rating)).join(Ticket, Ticket.id == Feedback.ticket_id).where(Ticket.assigned_agent_id == agent.id)
        if from_date:
            rating_statement = rating_statement.where(Feedback.created_at >= from_date)
        if to_date:
            rating_statement = rating_statement.where(Feedback.created_at <= to_date)
        ratings = await db.scalar(rating_statement)
        breached_pct = (sum(1 for t in tickets if t.sla_breached) * 100 / len(tickets)) if tickets else 0.0
        output.append({
            "agent_id": agent.id,
            "agent_name": agent.name,
            "tickets_in_period": len(tickets),
            "tickets_resolved": len(resolved),
            "average_first_response_minutes": round(sum(first_response_minutes) / len(first_response_minutes), 2) if first_response_minutes else None,
            "average_resolution_hours": round(sum(resolution_hours) / len(resolution_hours), 2) if resolution_hours else None,
            "sla_breach_percentage": round(breached_pct, 2),
            "average_rating": round(float(ratings), 2) if ratings is not None else None,
        })
    return {"from_date": from_date, "to_date": to_date, "agents": output}


@router.get("/category-summary")
async def category_summary(
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_roles(UserRole.ADMIN)),
):
    categories = list((await db.scalars(select(Category).order_by(Category.category_name))).all())
    output = []
    for category in categories:
        statement = select(Ticket).where(Ticket.category_id == category.id)
        if from_date:
            statement = statement.where(Ticket.created_at >= from_date)
        if to_date:
            statement = statement.where(Ticket.created_at <= to_date)
        tickets = list((await db.scalars(statement)).all())
        durations = [(t.resolved_at - t.created_at).total_seconds() / 3600 for t in tickets if t.resolved_at]
        output.append({
            "category_id": category.id,
            "category_name": category.category_name,
            "ticket_count": len(tickets),
            "average_resolution_hours": round(sum(durations) / len(durations), 2) if durations else None,
        })
    return {"from_date": from_date, "to_date": to_date, "categories": output}


@router.get("/sla-summary")
async def sla_summary(db: AsyncSession = Depends(get_db), _admin: User = Depends(require_roles(UserRole.ADMIN))):
    output = []
    for priority in TicketPriority:
        total = await db.scalar(select(func.count(Ticket.id)).where(Ticket.priority == priority)) or 0
        breached = await db.scalar(select(func.count(Ticket.id)).where(Ticket.priority == priority, Ticket.sla_breached.is_(True))) or 0
        output.append({"priority": priority.value, "total": total, "sla_breached": breached, "sla_met": total - breached})
    return {"priorities": output}


@router.get("/customer-satisfaction")
async def customer_satisfaction(db: AsyncSession = Depends(get_db), _admin: User = Depends(require_roles(UserRole.ADMIN))):
    average = await db.scalar(select(func.avg(Feedback.rating)))
    distribution = {}
    for rating in range(1, 6):
        distribution[str(rating)] = await db.scalar(select(func.count(Feedback.id)).where(Feedback.rating == rating)) or 0
    count = sum(distribution.values())
    return {"average_rating": round(float(average), 2) if average is not None else None, "total_ratings": count, "rating_distribution": distribution}
