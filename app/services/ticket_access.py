from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Agent, Ticket, User, UserRole


async def get_ticket_for_user(db: AsyncSession, ticket_id: int, user: User) -> Ticket:
    ticket = await db.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found.")
    allowed = user.role == UserRole.ADMIN or (
        user.role == UserRole.CUSTOMER and ticket.customer_id == user.id
    )
    if user.role == UserRole.AGENT:
        agent_id = await db.scalar(select(Agent.id).where(Agent.user_id == user.id))
        allowed = agent_id is not None and ticket.assigned_agent_id == agent_id
    if not allowed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You cannot access this ticket.")
    return ticket
