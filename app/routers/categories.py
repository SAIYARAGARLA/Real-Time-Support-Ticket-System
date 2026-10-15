from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import get_current_user, require_roles
from app.database import get_db
from app.models import Category, Ticket, TicketStatus, User, UserRole
from app.schemas import CategoryCreate, CategoryOut, CategoryUpdate

router = APIRouter(prefix="/categories", tags=["Categories"])


@router.post("", response_model=CategoryOut, status_code=status.HTTP_201_CREATED)
async def create_category(
    payload: CategoryCreate,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_roles(UserRole.ADMIN)),
):
    category = Category(
        category_name=payload.category_name.strip(),
        description=payload.description,
        is_active=payload.is_active,
    )
    db.add(category)
    try:
        await db.commit()
        await db.refresh(category)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Category name already exists.")
    return category


@router.get("", response_model=list[CategoryOut])
async def list_categories(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
    active_only: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    statement = select(Category)
    if active_only:
        statement = statement.where(Category.is_active.is_(True))
    result = await db.execute(statement.order_by(Category.category_name).offset(skip).limit(limit))
    return result.scalars().all()


@router.put("/{category_id}", response_model=CategoryOut)
async def update_category(
    category_id: int,
    payload: CategoryUpdate,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_roles(UserRole.ADMIN)),
):
    category = await db.get(Category, category_id)
    if category is None:
        raise HTTPException(status_code=404, detail="Category not found.")
    values = payload.model_dump(exclude_unset=True)
    if values.get("category_name") is not None:
        category.category_name = values["category_name"].strip()
    if "description" in values:
        category.description = values["description"]
    if values.get("is_active") is not None:
        category.is_active = values["is_active"]
    try:
        await db.commit()
        await db.refresh(category)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Category name already exists.")
    return category


@router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def delete_category(
    category_id: int,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_roles(UserRole.ADMIN)),
):
    category = await db.get(Category, category_id)
    if category is None:
        raise HTTPException(status_code=404, detail="Category not found.")
    open_statuses = [TicketStatus.OPEN, TicketStatus.ASSIGNED, TicketStatus.IN_PROGRESS, TicketStatus.WAITING_ON_CUSTOMER]
    open_count = await db.scalar(select(Ticket.id).where(Ticket.category_id == category_id, Ticket.status.in_(open_statuses)).limit(1))
    if open_count is not None:
        raise HTTPException(status_code=409, detail="A category with open tickets cannot be deleted.")
    historical_reference = await db.scalar(select(Ticket.id).where(Ticket.category_id == category_id).limit(1))
    if historical_reference is not None:
        # Preserve old ticket reports/history; hide the category from new tickets instead.
        category.is_active = False
    else:
        await db.delete(category)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Category is still referenced and cannot be deleted.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
