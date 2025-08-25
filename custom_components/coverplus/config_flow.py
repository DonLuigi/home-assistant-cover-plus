from __future__ import annotations

import voluptuous as vol
import homeassistant.helpers.config_validation as cv
from homeassistant import config_entries
from typing import Any, Optional

DOMAIN = "coverplus"

class CoverPlusConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: Optional[dict[str, Any]] = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            return self.async_create_entry(title=user_input["name"], data=user_input)

        data_schema = vol.Schema({
            vol.Required("real_entity_id"): cv.entity_domain("cover"),
            vol.Required("name"): str,
            vol.Required("open_time_sec", default=20): vol.All(int, vol.Range(min=1, max=3600)),
            vol.Required("tilt_time_ms", default=750): vol.All(int, vol.Range(min=100, max=60000)),
            vol.Optional("trace_ticks", default=False): bool,
        })
        return self.async_show_form(step_id="user", data_schema=data_schema, errors=errors)


class CoverPlusOptionsFlow(config_entries.OptionsFlow):
    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(self, user_input: Optional[dict[str, Any]] = None):
        data = {**self.config_entry.data, **self.config_entry.options}
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        data_schema = vol.Schema({
            vol.Required("real_entity_id", default=data.get("real_entity_id", "")): cv.entity_domain("cover"),
            vol.Required("name", default=data.get("name", "CoverPlus Virtual Cover")): str,
            vol.Required("open_time_sec", default=int(data.get("open_time_sec", 20))): vol.All(int, vol.Range(min=1, max=3600)),
            vol.Required("tilt_time_ms", default=int(data.get("tilt_time_ms", 750))): vol.All(int, vol.Range(min=100, max=60000)),
            vol.Optional("trace_ticks", default=bool(data.get("trace_ticks", False))): bool,
        })
        return self.async_show_form(step_id="init", data_schema=data_schema)