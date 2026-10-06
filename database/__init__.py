"""Shared storage; importing this package never opens a database connection."""

from database.session import session_scope

__all__ = ["session_scope"]
