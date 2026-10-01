"""Every ORM Enum column must persist enum *values*, matching migration labels.

SQLAlchemy persists member names by default; the migrations create hyphenated
labels (e.g. ``reported-result``). ``create_all`` hides the mismatch because it
builds the DB type from the same names, so this guards the ORM side directly.
"""

import enum

import pytest
from sqlalchemy import Enum

import app.main  # noqa: F401  registers every model on Base.metadata
from app.db.base import Base

_ENUM_COLUMNS = [
    (table.name, column.name, column.type)
    for table in Base.metadata.tables.values()
    for column in table.columns
    if isinstance(column.type, Enum) and column.type.enum_class is not None
]


@pytest.mark.parametrize(("table", "column", "sa_type"), _ENUM_COLUMNS, ids=lambda v: str(v)[:40])
def test_enum_column_persists_values_not_names(table: str, column: str, sa_type: Enum) -> None:
    enum_class: type[enum.Enum] = sa_type.enum_class
    assert list(sa_type.enums) == [member.value for member in enum_class], (
        f"{table}.{column} persists member names; pass values_callable=enum_values"
    )
