from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.security import get_current_user, get_password_hash, require_roles
from app.database import get_db
from app.models import Agent, AgentAvailability, Category, Ticket, TicketStatus, User, UserRole
from app.schemas import AgentCreate, AgentOut, AgentUpdate, AvailabilityUpdate, TicketOut
from app.services.assignment import assign_waiting_tickets, publish_open_ticket_counts
from app.services.notifications import queue_notification

router = APIRouter(tags=["Agents"])


def to_agent_out(agent: Agent) -> AgentOut:
    return AgentOut(
        id=agent.id,
        user_id=agent.user_id,
        name=agent.name,
        email=agent.email,
        category_ids=[category.id for category in agent.categories],
        categories=[category.category_name for category in agent.categories],
        availability=agent.availability,
        max_open_tickets=agent.max_open_tickets,
        is_active=agent.is_active,
        created_at=agent.created_at,
    )


@router.post("/agents", response_model=AgentOut, status_code=status.HTTP_201_CREATED)
async def create_agent(
    payload: AgentCreate,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_roles(UserRole.ADMIN)),
):
    email = str(payload.email).lower()
    if await db.scalar(select(User.id).where(User.email == email)) is not None:
        raise HTTPException(status_code=409, detail="An account with this email already exists.")
    category_result = await db.execute(select(Category).where(Category.id.in_(payload.category_ids)))
    categories = list(category_result.scalars().all())
    if len({item.id for item in categories}) != len(set(payload.category_ids)):
        raise HTTPException(status_code=404, detail="One or more categories were not found.")

    user = User(
        full_name=payload.name.strip(), email=email,
        hashed_password=get_password_hash(payload.password), role=UserRole.AGENT,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    agent = Agent(
        user_id=user.id, name=payload.name.strip(), email=email,
        availability=payload.availability, max_open_tickets=payload.max_open_tickets,
        is_active=True, categories=categories,
    )
    db.add(agent)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Agent email must be unique.")
    if agent.availability == AgentAvailability.ONLINE and agent.is_active:
        await assign_waiting_tickets(db)
        await db.commit()
    result = await db.execute(select(Agent).options(selectinload(Agent.categories)).where(Agent.id == agent.id))
    await publish_open_ticket_counts(db)
    return to_agent_out(result.scalar_one())


@router.get("/agents", response_model=list[AgentOut])
async def list_agents(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_roles(UserRole.ADMIN)),
):
    result = await db.execute(
        select(Agent).options(selectinload(Agent.categories)).order_by(Agent.id).offset(skip).limit(limit)
    )
    return [to_agent_out(agent) for agent in result.scalars().all()]


@router.put("/agents/{agent_id}", response_model=AgentOut)
async def update_agent(
    agent_id: int,
    payload: AgentUpdate,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_roles(UserRole.ADMIN)),
):
    result = await db.execute(select(Agent).options(selectinload(Agent.categories), selectinload(Agent.user)).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found.")
    values = payload.model_dump(exclude_unset=True)
    if "category_ids" in values and values["category_ids"] is not None:
        category_ids = values.pop("category_ids")
        cats_result = await db.execute(select(Category).where(Category.id.in_(category_ids)))
        cats = list(cats_result.scalars().all())
        if len({c.id for c in cats}) != len(set(category_ids)):
            raise HTTPException(status_code=404, detail="One or more categories were not found.")
        agent.categories = cats
    if "name" in values and values["name"] is not None:
        agent.name = values["name"].strip()
        agent.user.full_name = agent.name
    if "email" in values and values["email"] is not None:
        new_email = str(values["email"]).lower()
        duplicate = await db.scalar(select(User.id).where(User.email == new_email, User.id != agent.user_id))
        if duplicate is not None:
            raise HTTPException(status_code=409, detail="Email is already in use.")
        agent.email = new_email
        agent.user.email = new_email
    for field in ("max_open_tickets", "availability", "is_active"):
        if field in values and values[field] is not None:
            setattr(agent, field, values[field])
    if "is_active" in values and values["is_active"] is not None:
        agent.user.is_active = values["is_active"]
    await db.commit()
    if agent.availability == AgentAvailability.ONLINE and agent.is_active:
        await assign_waiting_tickets(db)
        await db.commit()
    await db.refresh(agent)
    result = await db.execute(select(Agent).options(selectinload(Agent.categories), selectinload(Agent.user)).where(Agent.id == agent_id))
    await publish_open_ticket_counts(db)
    return to_agent_out(result.scalar_one())


@router.put("/agents/me/availability", response_model=AgentOut)
async def set_my_availability(
    payload: AvailabilityUpdate,
    current_user: User = Depends(require_roles(UserRole.AGENT)),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Agent).options(selectinload(Agent.categories)).where(Agent.user_id == current_user.id))
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent profile not found.")
    agent.availability = payload.availability
    if payload.availability == AgentAvailability.ONLINE and agent.is_active:
        await db.flush()
        await assign_waiting_tickets(db)
    await db.commit()
    result = await db.execute(select(Agent).options(selectinload(Agent.categories)).where(Agent.id == agent.id))
    agent = result.scalar_one()
    await publish_open_ticket_counts(db)
    return to_agent_out(agent)


@router.get("/agents/me/tickets", response_model=list[TicketOut])
async def get_my_tickets(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    status_filter: Optional[TicketStatus] = Query(default=None, alias="status"),
    current_user: User = Depends(require_roles(UserRole.AGENT)),
    db: AsyncSession = Depends(get_db),
):
    agent_id = await db.scalar(select(Agent.id).where(Agent.user_id == current_user.id))
    if agent_id is None:
        raise HTTPException(status_code=404, detail="Agent profile not found.")
    statement = select(Ticket).where(Ticket.assigned_agent_id == agent_id)
    if status_filter:
        statement = statement.where(Ticket.status == status_filter)
    result = await db.execute(statement.order_by(Ticket.created_at.desc()).offset(skip).limit(limit))
    return result.scalars().all()
