"""LedgerBook: double-entry accounting for small organisations."""
from . import core
from .web import create_app

__all__ = ["core", "create_app"]
