"""
ORM models package.

Importing this package registers all model classes on the shared
:class:`~app.database.Base` declarative base so that
``Base.metadata.create_all`` and Alembic autogenerate can discover them.
"""

from app.models.account import Account  # noqa: F401
from app.models.holding import Holding  # noqa: F401
from app.models.parse_log import ParseLog  # noqa: F401
from app.models.statement import Statement  # noqa: F401
from app.models.activity import Activity  # noqa: F401

__all__ = ["Account", "Statement", "Holding", "ParseLog", "Activity"]
