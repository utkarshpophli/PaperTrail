"""Shared user-lookup logic used by both the token dependency and the
refresh route, so "resolve a JWT subject to a live User" has one
implementation, not one per caller.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.exceptions import InvalidTokenError
from app.models.user import User


async def get_user_by_subject(db: AsyncSession, subject: str) -> User:
    try:
        user_id = uuid.UUID(subject)
    except ValueError as exc:
        raise InvalidTokenError("Token subject is not a valid user id") from exc

    user = await db.get(User, user_id)
    if user is None:
        raise InvalidTokenError("User for token no longer exists")

    return user
