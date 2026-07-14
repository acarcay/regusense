"""
Backward-compatibility shim.

The canonical logging setup lives in core.logging — use that module directly.
This module exists only so `from core.logging_config import setup_logging`
keeps working.
"""

from core.logging import get_logger, setup_logging

__all__ = ["setup_logging", "get_logger"]
