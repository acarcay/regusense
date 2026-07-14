"""
Backward-compatibility shim.

The canonical settings live in config.settings — add new settings there.
This module exists only so `from core.config import settings` keeps working.
"""

from config.settings import Settings, get_settings, settings

__all__ = ["Settings", "get_settings", "settings"]
