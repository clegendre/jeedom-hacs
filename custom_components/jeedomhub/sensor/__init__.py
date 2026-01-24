"""Sensor platform for Jeedom."""

from .sensor import JeedomSensor, async_setup_entry

__all__ = ["JeedomSensor", "async_setup_entry"]
