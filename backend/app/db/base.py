import enum

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""


def enum_values(enum_class: type[enum.Enum]) -> list[str]:
    """``values_callable`` for ``sqlalchemy.Enum``: persist enum *values*, not member
    names. SQLAlchemy defaults to names, which silently disagrees with the
    hyphenated Postgres labels the migrations create (``reported-result``) --
    invisible under ``create_all`` (names on both sides) and a hard failure on any
    alembic-provisioned database.
    """
    return [member.value for member in enum_class]
