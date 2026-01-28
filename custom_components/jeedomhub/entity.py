"""Base entity classes for Jeedom integration."""
from __future__ import annotations

from typing import Callable, List

from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.restore_state import RestoreEntity

from .hub import JeedomHub
from .models import JeedomEntitySpec


class JeedomEntity(RestoreEntity, Entity):
    """Base entity with dispatcher subscriptions."""

    def __init__(self, hub: JeedomHub, spec: JeedomEntitySpec) -> None:
        self._hub = hub
        self._spec = spec
        self._unsub: List[Callable[[], None]] = []
        self._attr_unique_id = spec.unique_id
        self._attr_name = spec.name
        self._attr_device_info = spec.device_info

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        for cmd_id in self._spec.state_cmd_ids.values():
            if cmd_id is None:
                continue
            signal = self._hub.signal_cmd(cmd_id)
            self._unsub.append(
                async_dispatcher_connect(self.hass, signal, self._handle_cmd_update)
            )
        last_state = await self.async_get_last_state()
        if last_state is not None and hasattr(self, "_restore_from_state"):
            self._restore_from_state(last_state)

    async def async_will_remove_from_hass(self) -> None:
        for unsub in self._unsub:
            unsub()
        self._unsub.clear()

    def _safe_write_ha_state(self) -> None:
        """Schedule state write on the Home Assistant event loop."""
        if not self.hass:
            return
        self.hass.loop.call_soon_threadsafe(self.async_write_ha_state)

    def _handle_cmd_update(self, cmd_id: int, value) -> None:
        """Handle an update coming from Jeedom cmd events."""
        raise NotImplementedError


__all__ = ["JeedomEntity"]
