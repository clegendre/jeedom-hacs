"""Shared models for the Jeedom integration."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from homeassistant.const import Platform


@dataclass
class JeedomEntitySpec:
    platform: Platform
    unique_id: str
    name: str
    device_info: Dict[str, Any]
    entity_config: Dict[str, Any]
    action_config: Dict[str, Any] = field(default_factory=dict)
    state_cmd_ids: Dict[str, int] = field(default_factory=dict)
    device_key: Optional[str] = None
    is_pilot_climate: bool = False


__all__ = ["JeedomEntitySpec"]
