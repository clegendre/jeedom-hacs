"""Binary sensor platform for Jeedom."""

from .binary_sensor import JeedomBinarySensor, async_setup_entry

__all__ = ["JeedomBinarySensor", "async_setup_entry"]
