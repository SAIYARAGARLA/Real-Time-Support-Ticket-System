from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import get_current_user
from app.database import get_db
from app.models import Notification, User
from app.schemas import NotificationOut

router = APIRouter(prefix="/notifications", tags=["Notifications"])


@router.get("", response_model=list[NotificationOut])
async def list_notifications(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    unread_only: bool = False,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    statement = select(Notification).where(Notification.user_id == current_user.id)
    if unread_only:
        statement = statement.where(Notification.is_read.is_(False))
    result = await db.execute(statement.order_by(Notification.created_at.desc()).offset(skip).limit(limit))
    return result.scalars().all()


@router.put("/{notification_id}/read", response_model=NotificationOut)
async def mark_notification_read(
    notification_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    notification = await db.get(Notification, notification_id)
    if notification is None:
        raise HTTPException(status_code=404, detail="Notification not found.")
    if notification.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="You cannot update another user's notification.")
    notification.is_read = True
    await db.commit()
    await db.refresh(notification)
    return notification


@router.put("/read-all")
async def mark_all_notifications_read(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Notification).where(Notification.user_id == current_user.id, Notification.is_read.is_(False)))
    notifications = list(result.scalars().all())
    for notification in notifications:
        notification.is_read = True
    await db.commit()
    return {"updated": len(notifications)}
