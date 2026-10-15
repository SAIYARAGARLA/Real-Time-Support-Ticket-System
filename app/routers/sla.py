from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import get_current_user, require_roles
from app.database import get_db
from app.models import SLAPolicy, Ticket, TicketPriority, User, UserRole, utcnow
from app.schemas import SLAPolicyOut, SLAPolicyUpdate

router = APIRouter(prefix="/sla-policies", tags=["SLA Policies"])


@router.get("", response_model=list[SLAPolicyOut])
async def list_sla_policies(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    result = await db.execute(select(SLAPolicy).order_by(SLAPolicy.priority))
    return result.scalars().all()


@router.put("/{priority}", response_model=SLAPolicyOut)
async def update_sla_policy(
    priority: TicketPriority,
    payload: SLAPolicyUpdate,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_roles(UserRole.ADMIN)),
):
    policy = await db.scalar(select(SLAPolicy).where(SLAPolicy.priority == priority))
    if policy is None:
        raise HTTPException(status_code=404, detail="SLA policy not found. Run the seed script first.")
    policy.first_response_minutes = payload.first_response_minutes
    policy.resolution_minutes = payload.resolution_minutes
    policy.escalation_minutes = payload.escalation_minutes
    policy.is_active = payload.is_active
    policy.updated_at = utcnow()
    await db.commit()
    await db.refresh(policy)
    return policy
