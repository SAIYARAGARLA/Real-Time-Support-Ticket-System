from typing import Optional
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import get_current_user
from app.database import get_db
from app.models import Agent, Message, TicketStatus, User, UserRole, utcnow
from app.schemas import MessageCreate, MessageOut
from app.services.notifications import queue_notification
from app.services.ticket_access import get_ticket_for_user
from app.websockets.manager import ticket_manager

router = APIRouter(prefix="/tickets", tags=["Ticket Messages"])
UPLOAD_DIR = Path("uploads")
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
ALLOWED_CONTENT_TYPES = {"application/pdf", "image/jpeg", "image/png", "image/gif", "image/webp"}


async def _save_message(
    ticket_id: int,
    body: str,
    is_internal_note: bool,
    attachment_path: Optional[str],
    current_user: User,
    db: AsyncSession,
) -> Message:
    ticket = await get_ticket_for_user(db, ticket_id, current_user)
    if current_user.role == UserRole.CUSTOMER and ticket.status == TicketStatus.CLOSED:
        raise HTTPException(status_code=409, detail="Customers cannot send messages on closed tickets.")
    if is_internal_note and current_user.role == UserRole.CUSTOMER:
        raise HTTPException(status_code=403, detail="Customers cannot send internal notes.")
    if not body.strip():
        raise HTTPException(status_code=422, detail="Message cannot be empty.")
    message = Message(
        ticket_id=ticket_id,
        sender_id=current_user.id,
        sender_role=current_user.role.value,
        message=body.strip(),
        is_internal_note=is_internal_note,
        attachment_path=attachment_path,
    )
    db.add(message)
    if current_user.role == UserRole.AGENT and ticket.first_response_at is None and not is_internal_note:
        ticket.first_response_at = utcnow()
    await db.flush()

    if not is_internal_note:
        if current_user.role == UserRole.AGENT or current_user.role == UserRole.ADMIN:
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
    await ticket_manager.broadcast(
        ticket_id,
        {
            "type": "message",
            "id": message.id,
            "ticket_id": message.ticket_id,
            "sender_id": message.sender_id,
            "sender_role": message.sender_role,
            "message": message.message,
            "is_internal_note": message.is_internal_note,
            "is_read": message.is_read,
            "attachment_path": message.attachment_path,
            "created_at": message.created_at.isoformat(),
        },
        internal=message.is_internal_note,
    )
    return message


@router.get("/{ticket_id}/messages", response_model=list[MessageOut])
async def list_messages(
    ticket_id: int,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_ticket_for_user(db, ticket_id, current_user)
    statement = select(Message).where(Message.ticket_id == ticket_id)
    if current_user.role == UserRole.CUSTOMER:
        statement = statement.where(Message.is_internal_note.is_(False))
    result = await db.execute(statement.order_by(Message.created_at.asc()).offset(skip).limit(limit))
    messages = list(result.scalars().all())

    # Viewing the conversation marks other participants' visible messages as read.
    ids = [m.id for m in messages if m.sender_id != current_user.id and not m.is_read]
    if ids:
        rows = await db.execute(select(Message).where(Message.id.in_(ids)))
        for row in rows.scalars().all():
            row.is_read = True
        await db.commit()
    return messages


@router.post("/{ticket_id}/messages", response_model=MessageOut, status_code=status.HTTP_201_CREATED)
async def send_message(
    ticket_id: int,
    payload: MessageCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await _save_message(ticket_id, payload.message, payload.is_internal_note, None, current_user, db)


@router.post("/{ticket_id}/attachments", response_model=MessageOut, status_code=status.HTTP_201_CREATED)
async def upload_attachment(
    ticket_id: int,
    file: UploadFile = File(...),
    is_internal_note: bool = Form(False),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(status_code=415, detail="Only image files and PDFs are allowed.")
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if not data:
        raise HTTPException(status_code=422, detail="Attachment cannot be empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Attachment size cannot exceed 5 MB.")
    # Run access/rule validation before storing the file.
    ticket = await get_ticket_for_user(db, ticket_id, current_user)
    if current_user.role == UserRole.CUSTOMER and ticket.status == TicketStatus.CLOSED:
        raise HTTPException(status_code=409, detail="Customers cannot send attachments on closed tickets.")
    if is_internal_note and current_user.role == UserRole.CUSTOMER:
        raise HTTPException(status_code=403, detail="Customers cannot send internal notes.")
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = Path(file.filename or "attachment").name
    stored_name = f"{uuid4().hex}_{safe_name}"
    target = UPLOAD_DIR / stored_name
    target.write_bytes(data)
    return await _save_message(
        ticket_id, f"Attachment: {safe_name}", is_internal_note,
        f"/attachments/{stored_name}", current_user, db,
    )
