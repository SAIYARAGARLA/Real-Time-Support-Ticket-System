from typing import Optional
import json
from datetime import datetime

import jwt
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import func, select

from app.auth.security import decode_access_token
from app.database import AsyncSessionLocal
from app.models import Agent, Message, Notification, Ticket, TicketStatus, User, UserRole
from app.services.assignment import OPEN_STATUSES
from app.services.notifications import queue_notification
from app.models import utcnow
from app.websockets.manager import notification_manager, ticket_manager

router = APIRouter(tags=["WebSockets"])


def _message_json(message: Message) -> dict:
    return {
        "id": message.id,
        "ticket_id": message.ticket_id,
        "sender_id": message.sender_id,
        "sender_role": message.sender_role,
        "message": message.message,
        "is_internal_note": message.is_internal_note,
        "is_read": message.is_read,
        "attachment_path": message.attachment_path,
        "created_at": message.created_at.isoformat() if message.created_at else None,
    }


async def _get_user_from_token(token: Optional[str]) -> Optional[User]:
    if not token:
        return None
    try:
        user_id = decode_access_token(token)
    except jwt.InvalidTokenError:
        return None
    async with AsyncSessionLocal() as db:
        user = await db.get(User, user_id)
        if user is None or not user.is_active:
            return None
        # Return scalar data only; no relationship access is performed after close.
        return user


async def _user_can_access_ticket(user: User, ticket_id: int) -> bool:
    async with AsyncSessionLocal() as db:
        ticket = await db.get(Ticket, ticket_id)
        if ticket is None:
            return False
        if user.role == UserRole.ADMIN:
            return True
        if user.role == UserRole.CUSTOMER:
            return ticket.customer_id == user.id
        agent_id = await db.scalar(select(Agent.id).where(Agent.user_id == user.id))
        return agent_id is not None and ticket.assigned_agent_id == agent_id


async def _ticket_chat_message(ticket_id: int, user: User, data: dict) -> None:
    kind = data.get("type", "message")
    if kind == "typing":
        await ticket_manager.broadcast(
            ticket_id,
            {
                "type": "typing",
                "user_id": user.id,
                "user_name": user.full_name,
                "role": user.role.value,
                "is_typing": bool(data.get("is_typing", True)),
            },
        )
        return
    if kind != "message":
        return

    text = data.get("message", "")
    if not isinstance(text, str) or not text.strip() or len(text.strip()) >= 2000:
        raise ValueError("Message must contain 1 to 1999 characters.")
    internal = bool(data.get("is_internal_note", False))
    if internal and user.role == UserRole.CUSTOMER:
        raise PermissionError("Customers cannot send internal notes.")

    async with AsyncSessionLocal() as db:
        ticket = await db.get(Ticket, ticket_id)
        if ticket is None:
            raise ValueError("Ticket not found.")
        if user.role == UserRole.CUSTOMER and ticket.status == TicketStatus.CLOSED:
            raise PermissionError("Customers cannot send messages on closed tickets.")
        message = Message(
            ticket_id=ticket_id,
            sender_id=user.id,
            sender_role=user.role.value,
            message=text.strip(),
            is_internal_note=internal,
        )
        db.add(message)
        if user.role == UserRole.AGENT and ticket.first_response_at is None and not internal:
            ticket.first_response_at = utcnow()
        await db.flush()

        if not internal:
            if user.role in (UserRole.AGENT, UserRole.ADMIN):
                if not ticket_manager.is_connected(ticket_id, ticket.customer_id):
                    await queue_notification(
                        db, ticket.customer_id, "New reply on your ticket",
                        f"There is a new reply on ticket {ticket.ticket_number}.", ticket_id,
                    )
            elif ticket.assigned_agent_id is not None:
                agent = await db.get(Agent, ticket.assigned_agent_id)
                if agent:
                    await queue_notification(
                        db, agent.user_id, "New customer message",
                        f"The customer replied on ticket {ticket.ticket_number}.", ticket_id,
                    )
        await db.commit()
        await db.refresh(message)
        payload = {"type": "message", **_message_json(message)}
    await ticket_manager.broadcast(ticket_id, payload, internal=internal)


@router.websocket("/ws/tickets/{ticket_id}")
async def ticket_chat(websocket: WebSocket, ticket_id: int, token: Optional[str] = None):
    user = await _get_user_from_token(token)
    if user is None:
        await websocket.close(code=1008, reason="Invalid or expired token")
        return
    if not await _user_can_access_ticket(user, ticket_id):
        await websocket.close(code=1008, reason="Not authorized for this ticket")
        return

    await ticket_manager.connect(ticket_id, websocket, user.id, user.role.value)
    try:
        async with AsyncSessionLocal() as db:
            statement = select(Message).where(Message.ticket_id == ticket_id)
            if user.role == UserRole.CUSTOMER:
                statement = statement.where(Message.is_internal_note.is_(False))
            newest = list((await db.scalars(statement.order_by(Message.created_at.desc()).limit(50))).all())
            visible = list(reversed(newest))
            unread_statement = select(Message).where(
                Message.ticket_id == ticket_id,
                Message.sender_id != user.id,
                Message.is_read.is_(False),
            )
            if user.role == UserRole.CUSTOMER:
                unread_statement = unread_statement.where(Message.is_internal_note.is_(False))
            unread_rows = await db.scalars(unread_statement)
            has_unread = False
            for item in unread_rows.all():
                item.is_read = True
                has_unread = True
            if has_unread:
                await db.commit()
            await websocket.send_json({"type": "history", "messages": [_message_json(m) for m in visible]})

        while True:
            data = await websocket.receive_json()
            if not isinstance(data, dict):
                await websocket.send_json({"type": "error", "message": "Send a JSON object."})
                continue
            try:
                await _ticket_chat_message(ticket_id, user, data)
            except (ValueError, PermissionError) as exc:
                await websocket.send_json({"type": "error", "message": str(exc)})
    except WebSocketDisconnect:
        pass
    except Exception:
        try:
            await websocket.close(code=1011, reason="WebSocket error")
        except Exception:
            pass
    finally:
        ticket_manager.disconnect(ticket_id, websocket)


@router.websocket("/ws/notifications")
async def live_notifications(websocket: WebSocket, token: Optional[str] = None):
    user = await _get_user_from_token(token)
    if user is None:
        await websocket.close(code=1008, reason="Invalid or expired token")
        return
    await notification_manager.connect(websocket, user.id)
    try:
        async with AsyncSessionLocal() as db:
            open_count = 0
            if user.role == UserRole.ADMIN:
                open_count = await db.scalar(select(func.count(Ticket.id)).where(Ticket.status.in_(OPEN_STATUSES))) or 0
            elif user.role == UserRole.AGENT:
                agent_id = await db.scalar(select(Agent.id).where(Agent.user_id == user.id))
                if agent_id:
                    open_count = await db.scalar(select(func.count(Ticket.id)).where(Ticket.assigned_agent_id == agent_id, Ticket.status.in_(OPEN_STATUSES))) or 0
            unread_count = await db.scalar(
                select(func.count(Notification.id)).where(
                    Notification.user_id == user.id,
                    Notification.is_read.is_(False),
                )
            ) or 0
            await websocket.send_json({"type": "connected", "user_id": user.id, "unread_notifications": unread_count, "open_ticket_count": int(open_count)})
        while True:
            text = await websocket.receive_text()
            if text.lower() == "ping":
                await websocket.send_json({"type": "pong", "at": datetime.utcnow().isoformat()})
    except WebSocketDisconnect:
        pass
    except Exception:
        try:
            await websocket.close(code=1011, reason="WebSocket error")
        except Exception:
            pass
    finally:
        notification_manager.disconnect(websocket, user.id)
