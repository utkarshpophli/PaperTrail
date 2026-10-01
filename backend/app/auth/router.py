"""Auth routes: register / login / refresh / me.

Per ARCHITECTURE.md's Authentication section, the backend owns identity
directly (no third-party auth SaaS). Register and login are rate-limited
per-IP (SECURITY.md: "per-IP limits on unauthenticated endpoints").
"""

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.auth.exceptions import EmailAlreadyRegisteredError, InvalidCredentialsError
from app.auth.schemas import LoginRequest, RefreshRequest, RegisterRequest, TokenResponse, UserResponse
from app.auth.security import create_access_token, create_refresh_token, decode_token, hash_password, verify_password
from app.auth.service import get_user_by_subject
from app.core.logging import get_logger
from app.core.rate_limit import limiter
from app.db.session import get_db
from app.models.user import User

logger = get_logger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

# Precomputed once so the "no such user" path costs the same bcrypt work as
# the "wrong password" path — otherwise the short-circuit on a missing user
# skips verify_password entirely, and the ~100ms timing gap enables email
# enumeration via /auth/login even though both cases return an identical body.
_DUMMY_PASSWORD_HASH = hash_password("dummy-password-for-timing-parity")


@router.post("/register", response_model=UserResponse, status_code=201)
@limiter.limit("5/minute")
async def register(request: Request, body: RegisterRequest, db: AsyncSession = Depends(get_db)) -> User:
    existing = await db.scalar(select(User).where(User.email == body.email))
    if existing is not None:
        raise EmailAlreadyRegisteredError("An account with this email already exists")

    user = User(email=body.email, hashed_password=hash_password(body.password))
    db.add(user)
    await db.commit()
    await db.refresh(user)
    logger.info("user_registered user_id=%s", user.id)
    return user


@router.post("/login", response_model=TokenResponse)
@limiter.limit("5/minute")
async def login(request: Request, body: LoginRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    user = await db.scalar(select(User).where(User.email == body.email))
    hashed = user.hashed_password if user is not None else _DUMMY_PASSWORD_HASH
    if user is None or not verify_password(body.password, hashed):
        raise InvalidCredentialsError("Incorrect email or password")

    logger.info("user_logged_in user_id=%s", user.id)
    return TokenResponse(
        access_token=create_access_token(str(user.id)),
        refresh_token=create_refresh_token(str(user.id)),
    )


@router.post("/refresh", response_model=TokenResponse)
@limiter.limit("10/minute")
async def refresh(request: Request, body: RefreshRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    subject = decode_token(body.refresh_token, expected_type="refresh")
    user = await get_user_by_subject(db, subject)

    # ponytail: stateless rotation, no server-side revocation list — an old
    # refresh token stays valid until it expires even after this call issues
    # a new one. Add a revoked-token store if refresh-token theft becomes a
    # real threat model concern before refresh tokens naturally expire.
    return TokenResponse(
        access_token=create_access_token(str(user.id)),
        refresh_token=create_refresh_token(str(user.id)),
    )


@router.get("/me", response_model=UserResponse)
async def me(current_user: User = Depends(get_current_user)) -> User:
    return current_user
