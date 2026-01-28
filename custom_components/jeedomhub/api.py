"""Jeedom API client for executing commands via JSON-RPC or HTTP GET."""
from __future__ import annotations

from typing import Any, Dict, Optional
import logging

from aiohttp import ClientError
import async_timeout
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_LOGGER = logging.getLogger(__name__)


class JeedomApi:
    """Client for Jeedom command execution."""

    def __init__(
        self,
        hass,
        base_url: str,
        api_key: str,
        jsonrpc_url: Optional[str] = None,
        use_jsonrpc: bool = True,
        jsonrpc_fallback: bool = True,
    ) -> None:
        self._hass = hass
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._jsonrpc_url = jsonrpc_url or f"{self._base_url}/core/api/jeeApi.php"
        self._use_jsonrpc = use_jsonrpc
        self._jsonrpc_fallback = jsonrpc_fallback

    async def async_exec_cmd(
        self, cmd_id: int, value: Optional[str] = None, options: Optional[Dict[str, Any]] = None
    ) -> Optional[str]:
        if self._use_jsonrpc:
            result = await self._async_exec_cmd_jsonrpc(cmd_id, value=value, options=options)
            if result is not None:
                return result
            if self._jsonrpc_fallback:
                _LOGGER.warning("JSON-RPC failed for cmd_id=%s, falling back to HTTP GET", cmd_id)
                return await self._async_exec_cmd_http(cmd_id, value=value)
            return None
        return await self._async_exec_cmd_http(cmd_id, value=value)

    async def _async_exec_cmd_http(self, cmd_id: int, value: Optional[str] = None) -> Optional[str]:
        session = async_get_clientsession(self._hass)
        params = {"apikey": self._api_key, "type": "cmd", "id": str(cmd_id)}
        if value is not None:
            params["value"] = str(value)
        url = f"{self._base_url}/core/api/jeeApi.php"

        try:
            async with async_timeout.timeout(10):
                async with session.get(url, params=params) as resp:
                    body = await resp.text()
                    if resp.status >= 400:
                        _LOGGER.error("Jeedom HTTP error %s for cmd_id=%s", resp.status, cmd_id)
                        return None
                    return body
        except (ClientError, TimeoutError) as exc:
            _LOGGER.error("Jeedom HTTP call failed for cmd_id=%s: %s", cmd_id, exc)
            return None

    async def _async_exec_cmd_jsonrpc(
        self, cmd_id: int, value: Optional[str] = None, options: Optional[Dict[str, Any]] = None
    ) -> Optional[str]:
        session = async_get_clientsession(self._hass)
        params: Dict[str, Any] = {"apikey": self._api_key, "id": int(cmd_id)}
        if value is not None:
            try:
                params["value"] = int(value) if str(value).isdigit() else float(value)
            except Exception:
                params["value"] = value
        if options:
            params["options"] = options

        payload = {"jsonrpc": "2.0", "method": "cmd::execCmd", "params": params, "id": 1}

        try:
            async with async_timeout.timeout(10):
                async with session.post(self._jsonrpc_url, json=payload) as resp:
                    body = await resp.text()
                    if resp.status >= 400:
                        _LOGGER.error("Jeedom JSON-RPC HTTP error %s for cmd_id=%s", resp.status, cmd_id)
                        return None
        except (ClientError, TimeoutError) as exc:
            _LOGGER.error("Jeedom JSON-RPC call failed for cmd_id=%s: %s", cmd_id, exc)
            return None

        try:
            parsed = await _parse_json(body)
        except Exception:
            return body

        if isinstance(parsed, dict) and parsed.get("error"):
            _LOGGER.error("Jeedom JSON-RPC error for cmd_id=%s: %s", cmd_id, parsed.get("error"))
            return None
        return body


async def _parse_json(text: str) -> Any:
    """Parse JSON in executor to avoid blocking."""
    import json

    return json.loads(text)


__all__ = ["JeedomApi"]
