"""Shared SQLAlchemy declarative base and constraint naming convention."""

from types import MappingProxyType
from typing import Final

from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION: Final = MappingProxyType(
    {
        "ix": "ix_%(column_0_label)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    }
)


class OrmBase(AsyncAttrs, DeclarativeBase):
    """Base class shared by all SQLAlchemy persistence records."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
