from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Notification, User, UserRole
from app.websockets.manager import notification_manager


async def queue_notification(
    db: AsyncSession,
    user_id: int,
    title: str,
    message: str,
    ticket_id: Optional[int] = None,
) -> Notification:
    notification = Notification(
        user_id=user_id,
        ticket_id=ticket_id,
        title=title,
        message=message,
    )
    db.add(notification)
    await db.flush()
    # Delivery is best-effort; the notification remains persisted even if the client is offline.
    await notification_manager.send_to_user(
        user_id,
        {
            "type": "notification",
            "id": notification.id,
            "ticket_id": notification.ticket_id,
            "title": notification.title,
            "message": notification.message,
            "is_read": notification.is_read,
            "created_at": notification.created_at.isoformat() if notification.created_at else None,
        },
    )
    return notification


async def publish_notification(notification: Notification) -> None:
    await notification_manager.send_to_user(
        notification.user_id,
        {
            "type": "notification",
            "id": notification.id,
            "ticket_id": notification.ticket_id,
            "title": notification.title,
            "message": notification.message,
            "is_read": notification.is_read,
            "created_at": notification.created_at.isoformat() if notification.created_at else None,
        },
    )


async def publish_notifications(notifications: list[Notification]) -> None:
    for notification in notifications:
        await publish_notification(notification)


async def queue_admin_notifications(
    db: AsyncSession,
    title: str,
    message: str,
    ticket_id: Optional[int] = None,
) -> list[Notification]:
    result = await db.execute(select(User.id).where(User.role == UserRole.ADMIN, User.is_active.is_(True)))
    notifications = []
    for (user_id,) in result.all():
        notifications.append(await queue_notification(db, user_id, title, message, ticket_id))
    return notifications
