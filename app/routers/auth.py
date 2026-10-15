from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import create_access_token, get_current_user, get_password_hash, require_roles, verify_password
from app.database import get_db
from app.models import User, UserRole
from app.schemas import AdminCreate, LoginResponse, UserLogin, UserOut, UserRegister

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register(payload: UserRegister, db: AsyncSession = Depends(get_db)):
    email = str(payload.email).lower()
    existing = await db.scalar(select(User.id).where(User.email == email))
    if existing is not None:
        raise HTTPException(status_code=409, detail="An account with this email already exists.")
    user = User(
        full_name=payload.full_name.strip(),
        email=email,
        phone=payload.phone,
        hashed_password=get_password_hash(payload.password),
        role=UserRole.CUSTOMER,
        is_active=True,
    )
    db.add(user)
    try:
        await db.commit()
        await db.refresh(user)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="An account with this email already exists.")
    return user


@router.post("/login", response_model=LoginResponse)
async def login(payload: UserLogin, db: AsyncSession = Depends(get_db)):
    email = str(payload.email).lower()
    user = await db.scalar(select(User).where(User.email == email))
    if user is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password.", headers={"WWW-Authenticate": "Bearer"})
    if not user.is_active:
        raise HTTPException(status_code=403, detail="This account is inactive.")
    return LoginResponse(access_token=create_access_token(user.id), user=user)


@router.post("/admin/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_admin_account(
    payload: AdminCreate,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_roles(UserRole.ADMIN)),
):
    email = str(payload.email).lower()
    if await db.scalar(select(User.id).where(User.email == email)) is not None:
        raise HTTPException(status_code=409, detail="An account with this email already exists.")
    user = User(
        full_name=payload.full_name,
        email=email,
        hashed_password=get_password_hash(payload.password),
        role=UserRole.ADMIN,
        is_active=True,
    )
    db.add(user)
    try:
        await db.commit()
        await db.refresh(user)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="An account with this email already exists.")
    return user


@router.get("/me", response_model=UserOut)
async def get_my_profile(current_user: User = Depends(get_current_user)):
    return current_user
