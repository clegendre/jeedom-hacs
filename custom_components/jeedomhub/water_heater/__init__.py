"""Water heater platform for Jeedom."""

from .water_heater import JeedomWaterHeater, async_setup_entry

__all__ = ["JeedomWaterHeater", "async_setup_entry"]
