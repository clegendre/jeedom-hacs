"""Light platform for Jeedom."""

from .light import JeedomLight, async_setup_entry

__all__ = ["JeedomLight", "async_setup_entry"]
