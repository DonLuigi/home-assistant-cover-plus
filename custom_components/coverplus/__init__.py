from __future__ import annotations

import logging
from typing import Any

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.discovery import async_load_platform
from homeassistant.helpers.reload import async_setup_reload_service

_LOGGER = logging.getLogger(__name__)
DOMAIN = "coverplus"
PLATFORMS = [Platform.COVER]

DATA_YAML_CONF = "yaml_conf"

async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    await async_setup_reload_service(hass, DOMAIN, PLATFORMS)

    domain_conf: dict[str, Any] | None = config.get(DOMAIN)
    if domain_conf:
        _LOGGER.debug("[init] YAML config detected under '%s': %s", DOMAIN, domain_conf)
        hass.data.setdefault(DOMAIN, {})
        hass.data[DOMAIN][DATA_YAML_CONF] = domain_conf
        hass.async_create_task(async_load_platform(hass, Platform.COVER, DOMAIN, domain_conf, config))
    else:
        _LOGGER.debug("[init] No top-level YAML for '%s' (using UI config or 'cover:' platform instead)", DOMAIN)

    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    _LOGGER.debug("[init] setup_entry %s", entry.entry_id)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    _LOGGER.debug("[init] unload_entry %s", entry.entry_id)
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)