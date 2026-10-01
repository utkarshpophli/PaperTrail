"""FastAPI dependency that resolves the acting user.

Two modes (``settings.local_mode``):

- ``local_mode`` (default): a single-user, run-on-your-own-machine setup. No
  login exists; every request acts as one fixed local user, so the ownership
  model (``user_id`` on every row) and the database schema are unchanged. This
  is only safe while the API is reachable from this machine alone -- keep it
  bound to loopback (see docs/SECURITY.md).
- otherwise: bearer access-token auth.
"""

import secrets
import uuid

from fastapi import Depends, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.exceptions import InvalidTokenError
from app.auth.security import decode_token, hash_password
from app.auth.service import get_user_by_subject
from app.core.config import get_settings
from app.db.session import get_db
from app.models.user import User

# auto_error=False so a missing Authorization header doesn't 401 before
# ``get_current_user`` can decide whether local mode applies.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)

LOCAL_USER_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")
LOCAL_USER_EMAIL = "local@papertrail.local"


async def get_or_create_local_user(db: AsyncSession) -> User:
    user = await db.get(User, LOCAL_USER_ID)
    if user is not None:
        return user
    # The password is random and discarded: nobody can log in as this user,
    # and concurrent first requests race safely on the fixed primary key.
    await db.execute(
        pg_insert(User)
        .values(id=LOCAL_USER_ID, email=LOCAL_USER_EMAIL, hashed_password=hash_password(secrets.token_urlsafe(48)))
        .on_conflict_do_nothing()
    )
    await db.commit()
    user = await db.get(User, LOCAL_USER_ID)
    assert user is not None
    return user


async def get_current_user(
    request: Request,
    token: str | None = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    if get_settings().local_mode:
        user = await get_or_create_local_user(db)
    else:
        if token is None:
            raise InvalidTokenError("Not authenticated")
        subject = decode_token(token, expected_type="access")
        user = await get_user_by_subject(db, subject)
    # Set once resolved so per-user rate limiting (app.core.rate_limit) can
    # key on it — Request is the same object dependencies and the route
    # handler share, so this is visible wherever else reads request.state.
    request.state.user_id = str(user.id)
    return user
