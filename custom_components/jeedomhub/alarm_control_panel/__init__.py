"""Alarm control panel platform for Jeedom."""

from .alarm_control_panel import JeedomAlarmControlPanel, async_setup_entry

__all__ = ["JeedomAlarmControlPanel", "async_setup_entry"]
