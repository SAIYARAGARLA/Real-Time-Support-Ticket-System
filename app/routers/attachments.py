from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import get_current_user
from app.database import get_db
from app.models import Message, User, UserRole
from app.services.ticket_access import get_ticket_for_user

router = APIRouter(tags=["Attachments"])
UPLOAD_DIR = Path("uploads").resolve()


@router.get("/attachments/{filename}")
async def download_attachment(
    filename: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # UUID-prefixed filenames and basename checks prevent path traversal.
    if Path(filename).name != filename or filename in {"", ".", ".."}:
        raise HTTPException(status_code=400, detail="Invalid attachment name.")
    attachment_path = f"/attachments/{filename}"
    message = await db.scalar(select(Message).where(Message.attachment_path == attachment_path))
    if message is None:
        raise HTTPException(status_code=404, detail="Attachment not found.")
    await get_ticket_for_user(db, message.ticket_id, current_user)
    if current_user.role == UserRole.CUSTOMER and message.is_internal_note:
        raise HTTPException(status_code=404, detail="Attachment not found.")
    target = (UPLOAD_DIR / filename).resolve()
    if target.parent != UPLOAD_DIR or not target.is_file():
        raise HTTPException(status_code=404, detail="Attachment file not found.")
    return FileResponse(target, filename=filename)
