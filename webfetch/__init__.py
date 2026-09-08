from .auth import login
from .client import Result, download, fetch, read_tables
from .search import discover

__all__ = ["fetch", "read_tables", "download", "discover", "login", "Result", "wayback", "Snapshot"]
from ._archive import Snapshot, wayback
