from __future__ import annotations
import logging

_LOGGER = logging.getLogger(__name__)
DOMAIN = "coverplus"

async def async_setup(hass, config):
    _LOGGER.debug("[init] %s domain loaded", DOMAIN)
    return True