from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

import voluptuous as vol
import homeassistant.helpers.config_validation as cv

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.entity_platform import AddEntitiesCallback, async_get_current_platform
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.components.cover import (
    CoverEntity,
    CoverEntityFeature,
    PLATFORM_SCHEMA as COVER_PLATFORM_SCHEMA,
)

_LOGGER = logging.getLogger(__name__)

DOMAIN = "coverplus"

# ---- Config keys
CONF_COVERS = "covers"
CONF_REAL_ENTITY_ID = "real_entity_id"
CONF_NAME = "name"
CONF_OPEN_TIME_SEC = "open_time_sec"   # seconds for 0→100 position
CONF_TILT_TIME_MS = "tilt_time_ms"     # ms for 0→100 tilt
CONF_UNIQUE_ID = "unique_id"
CONF_TRACE_TICKS = "trace_ticks"

SINGLE_COVER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_REAL_ENTITY_ID): cv.entity_domain("cover"),
        vol.Required(CONF_NAME): cv.string,
        vol.Required(CONF_OPEN_TIME_SEC): vol.All(int, vol.Range(min=1, max=3600)),
        vol.Required(CONF_TILT_TIME_MS): vol.All(int, vol.Range(min=100, max=60000)),
        vol.Optional(CONF_UNIQUE_ID): cv.string,
        vol.Optional(CONF_TRACE_TICKS, default=False): cv.boolean,
    }
)

PLATFORM_SCHEMA = COVER_PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_COVERS): vol.All(cv.ensure_list, [SINGLE_COVER_SCHEMA]),
    }
)

# ---- Directions
UP = "UP"
DOWN = "DOWN"
STOPPED = "STOPPED"

EPS = 1e-6

# One-time guards for service registration
_ENTITY_SERVICE_REGISTERED = False
_DOMAIN_SERVICE_REGISTERED = False

# hass.data keys
DATA_ENTITIES = "entities"  # map: entity_id -> TiltVirtualCover


async def async_setup_platform(
    hass: HomeAssistant,
    config: Dict[str, Any],
    async_add_entities: AddEntitiesCallback,
    discovery_info: Optional[Dict[str, Any]] = None,
) -> None:
    # Prepare hass.data bucket
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN].setdefault(DATA_ENTITIES, {})

    covers_conf = config.get(CONF_COVERS, [])
    entities: List[TiltVirtualCover] = []
    for cfg in covers_conf:
        entities.append(
            TiltVirtualCover(
                hass=hass,
                real_entity_id=cfg[CONF_REAL_ENTITY_ID],
                name=cfg[CONF_NAME],
                open_time_sec=cfg[CONF_OPEN_TIME_SEC],
                tilt_time_ms=cfg[CONF_TILT_TIME_MS],
                unique_id=cfg.get(CONF_UNIQUE_ID),
                trace_ticks=cfg.get(CONF_TRACE_TICKS, False),
            )
        )

    async_add_entities(entities)
    _LOGGER.info("[setup] Added %d CoverPlus virtual cover(s)", len(entities))

    # 1) Entity-level service under 'cover' domain
    global _ENTITY_SERVICE_REGISTERED
    if not _ENTITY_SERVICE_REGISTERED:
        platform = async_get_current_platform()
        platform.async_register_entity_service(
            "set_position_and_tilt",
            {
                vol.Optional("position"): vol.All(int, vol.Range(min=0, max=100)),
                vol.Optional("tilt"): vol.All(int, vol.Range(min=0, max=100)),
            },
            "async_set_position_and_tilt",
        )
        _ENTITY_SERVICE_REGISTERED = True
        _LOGGER.debug("[setup] Registered entity service cover.set_position_and_tilt")

    # 2) Domain-level service under 'coverplus' domain that routes to entity instances
    global _DOMAIN_SERVICE_REGISTERED
    if not _DOMAIN_SERVICE_REGISTERED:
        SERVICE_SCHEMA = vol.Schema(
            {
                vol.Required("entity_id"): cv.entity_ids,
                vol.Optional("position"): vol.All(int, vol.Range(min=0, max=100)),
                vol.Optional("tilt"): vol.All(int, vol.Range(min=0, max=100)),
            }
        )

        async def _handle_domain_set_position_and_tilt(call: ServiceCall) -> None:
            entity_ids = call.data["entity_id"]
            position = call.data.get("position")
            tilt = call.data.get("tilt")
            registry: Dict[str, TiltVirtualCover] = hass.data[DOMAIN][DATA_ENTITIES]

            _LOGGER.debug(
                "[svc_domain] coverplus.set_position_and_tilt %s",
                {"entity_ids": entity_ids, "position": position, "tilt": tilt},
            )

            tasks = []
            for eid in entity_ids:
                ent = registry.get(eid)
                if ent is None:
                    _LOGGER.warning("[svc_domain] Entity %s not managed by %s", eid, DOMAIN)
                    continue
                tasks.append(ent.async_set_position_and_tilt(position=position, tilt=tilt))

            if tasks:
                await asyncio.gather(*tasks)

        hass.services.async_register(
            DOMAIN, "set_position_and_tilt", _handle_domain_set_position_and_tilt, schema=SERVICE_SCHEMA
        )
        _DOMAIN_SERVICE_REGISTERED = True
        _LOGGER.debug("[setup] Registered domain service coverplus.set_position_and_tilt")


class TiltVirtualCover(CoverEntity, RestoreEntity):
    """Virtual cover with pre-tilt → move → (optional) post-tilt pipeline."""

    _attr_should_poll = False
    _TICK_MS = 100

    def __init__(
        self,
        hass: HomeAssistant,
        real_entity_id: str,
        name: str,
        open_time_sec: int,
        tilt_time_ms: int,
        unique_id: Optional[str] = None,
        trace_ticks: bool = False,
    ) -> None:
        self.hass = hass
        self._real = real_entity_id
        self._attr_name = name
        self._attr_unique_id = unique_id or f"{DOMAIN}:{real_entity_id}:{name}"
        self._trace_ticks = bool(trace_ticks)

        # timing model
        self._open_time_millis = float(open_time_sec) * 1000.0
        self._tilt_time_millis = float(tilt_time_ms)
        self._position_rate_per_ms = 100.0 / self._open_time_millis  # % per ms
        self._tilt_rate_per_ms = 100.0 / self._tilt_time_millis      # % per ms

        # internal state
        self.last_position: float = 0.0
        self.last_tilt: float = 0.0
        self.last_timestamp_millis: int = 0
        self.last_direction: str = STOPPED

        # cached attrs for HA
        self._attr_current_cover_position = 0
        self._attr_current_cover_tilt_position = 0

        # cancel flag
        self._cancel_requested = False

        # features
        self._attr_supported_features = (
            CoverEntityFeature.OPEN
            | CoverEntityFeature.CLOSE
            | CoverEntityFeature.STOP
            | CoverEntityFeature.SET_POSITION
            | CoverEntityFeature.SET_TILT_POSITION
        )

        self._log(
            "init",
            open_time_ms=self._open_time_millis,
            tilt_time_ms=self._tilt_time_millis,
            position_rate_per_ms=round(self._position_rate_per_ms, 6),
            tilt_rate_per_ms=round(self._tilt_rate_per_ms, 6),
        )

    # ---- logging helpers
    def _snapshot(self) -> Dict[str, Any]:
        return {
            "last_position": round(self.last_position, 3),
            "last_tilt": round(self.last_tilt, 3),
            "last_timestamp_millis": self.last_timestamp_millis,
            "last_direction": self.last_direction,
        }

    def _log(self, tag: str, **payload: Any) -> None:
        base = {"entity": self.entity_id or self._attr_name, "real": self._real}
        base.update(self._snapshot())
        base.update(payload)
        _LOGGER.debug("[%s] %s", tag, base)

    # ---- HA props
    @property
    def is_closed(self) -> Optional[bool]:
        return int(round(self.last_position)) == 0

    @property
    def current_cover_position(self) -> Optional[int]:
        return int(round(self.last_position))

    @property
    def current_cover_tilt_position(self) -> Optional[int]:
        return int(round(self.last_tilt))

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "real_entity": self._real,
            "open_time_sec": self._open_time_millis / 1000.0,
            "tilt_time_ms": int(round(self._tilt_time_millis)),
            **self._snapshot(),
        }

    # ---- state push
    def _push_state(self) -> None:
        self._attr_current_cover_position = int(round(self.last_position))
        self._attr_current_cover_tilt_position = int(round(self.last_tilt))
        self.async_write_ha_state()

    # ---- restore & registry hook
    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # Register this instance for domain service routing
        self.hass.data.setdefault(DOMAIN, {})
        self.hass.data[DOMAIN].setdefault(DATA_ENTITIES, {})
        self.hass.data[DOMAIN][DATA_ENTITIES][self.entity_id] = self

        state = await self.async_get_last_state()
        if state is not None:
            try:
                if (v := state.attributes.get("last_position")) is not None:
                    self.last_position = float(v)
                if (v := state.attributes.get("last_tilt")) is not None:
                    self.last_tilt = float(v)
                if (v := state.attributes.get("last_timestamp_millis")) is not None:
                    self.last_timestamp_millis = int(v)
                if (v := state.attributes.get("last_direction")) in (UP, DOWN, STOPPED):
                    self.last_direction = v
                self._log("restore_ok")
            except Exception as exc:
                self._log("restore_err", error=str(exc))
        self._push_state()

    async def async_will_remove_from_hass(self) -> None:
        # Unregister from domain routing
        try:
            reg = self.hass.data.get(DOMAIN, {}).get(DATA_ENTITIES, {})
            reg.pop(self.entity_id, None)
        except Exception:
            pass

    # ---- utils
    def _now_millis(self) -> int:
        return int(time.monotonic() * 1000)

    def _clamp(self) -> None:
        before_p, before_t = self.last_position, self.last_tilt
        self.last_position = max(0.0, min(100.0, self.last_position))
        self.last_tilt = max(0.0, min(100.0, self.last_tilt))
        if before_p != self.last_position or before_t != self.last_tilt:
            self._log(
                "clamp",
                before_position=round(before_p, 3),
                after_position=round(self.last_position, 3),
                before_tilt=round(before_t, 3),
                after_tilt=round(self.last_tilt, 3),
            )

    async def _svc(self, service: str) -> None:
        """Fire-and-forget service call to the real cover (non-blocking)."""
        payload = {"entity_id": self._real}
        self._log("tx", service=service, payload=payload)
        try:
            self.hass.async_create_task(
                self.hass.services.async_call("cover", service, payload, blocking=False)
            )
            await asyncio.sleep(0)  # yield immediately
            self._log("tx_ok", service=service)
        except Exception as exc:
            self._log("tx_err", service=service, error=str(exc))
            self._cancel_requested = True
            self.last_direction = STOPPED

    # ---- motor control
    async def _motor(self, direction: str) -> None:
        """
        Ensure the real motor matches the requested direction.
        Sends a service call ONLY if the direction changed.
        Safely handles reversals by issuing stop first.
        """
        if direction == self.last_direction:
            self._log("motor_keep", keep_direction=direction)
            return

        self._log("motor_change", from_direction=self.last_direction, to_direction=direction)

        # Stop first on reversals (UP↔DOWN)
        if (
            self.last_direction in (UP, DOWN)
            and direction in (UP, DOWN)
            and direction != self.last_direction
        ):
            await self._svc("stop_cover")
            await asyncio.sleep(0)

        if direction == STOPPED:
            await self._svc("stop_cover")
        elif direction == UP:
            await self._svc("open_cover")
        elif direction == DOWN:
            await self._svc("close_cover")
        else:
            self._log("motor_invalid_direction", direction=direction)
            return

        self.last_direction = direction
        self._log("motor_set", now_direction=self.last_direction)

    # ---- tilt phase (no direction changes; only stops on cancel)
    async def _act_tilt(self, target_tilt: float) -> None:
        target_tilt = float(max(0.0, min(100.0, target_tilt)))
        self._log("act_tilt_begin", target_tilt=target_tilt)

        while True:
            if self._cancel_requested:
                await self._motor(STOPPED)
                self.last_timestamp_millis = self._now_millis()
                self._push_state()
                self._log("act_cancelled_tilt")
                return

            need = target_tilt - self.last_tilt
            if abs(need) < EPS:
                break

            millis_to_boundary = int(abs(need) / self._tilt_rate_per_ms)
            slice_millis = max(1, min(self._TICK_MS, millis_to_boundary if millis_to_boundary > 0 else self._TICK_MS))
            step_sign = 1 if need > 0 else -1

            before_tilt = self.last_tilt
            self.last_tilt += self._tilt_rate_per_ms * slice_millis * step_sign
            self.last_timestamp_millis += slice_millis
            self._clamp()

            if self._trace_ticks:
                self._log(
                    "act_tilt_tick",
                    slice_millis=slice_millis,
                    before_tilt=round(before_tilt, 3),
                    after_tilt=round(self.last_tilt, 3),
                    target_tilt=target_tilt,
                    remaining_ms=max(0, millis_to_boundary - slice_millis),
                )
            self._push_state()
            await asyncio.sleep(slice_millis / 1000.0)

        self._log("act_tilt_end", final_tilt=round(self.last_tilt, 3))

    # ---- position phase (no direction changes; only stops on cancel)
    async def _act_position(self, target_position: float, target_direction: str) -> None:
        target_position = float(max(0.0, min(100.0, target_position)))
        self._log("act_pos_begin", target_position=target_position, target_direction=target_direction)

        while True:
            if self._cancel_requested:
                await self._motor(STOPPED)
                self.last_timestamp_millis = self._now_millis()
                self._push_state()
                self._log("act_cancelled_position")
                return

            need = target_position - self.last_position
            if abs(need) < EPS:
                break

            millis_to_boundary = int(abs(need) / self._position_rate_per_ms)
            slice_millis = max(1, min(self._TICK_MS, millis_to_boundary if millis_to_boundary > 0 else self._TICK_MS))
            step_sign = 1 if need > 0 else -1

            before_position = self.last_position
            self.last_position += self._position_rate_per_ms * slice_millis * step_sign
            self.last_timestamp_millis += slice_millis
            self._clamp()

            if self._trace_ticks:
                self._log(
                    "act_pos_tick",
                    slice_millis=slice_millis,
                    before_position=round(before_position, 3),
                    after_position=round(self.last_position, 3),
                    target_position=target_position,
                    direction=target_direction,
                    remaining_ms=max(0, millis_to_boundary - slice_millis),
                )
            self._push_state()
            await asyncio.sleep(slice_millis / 1000.0)

        self._log("act_pos_end", final_position=round(self.last_position, 3))

    # ---- orchestrator
    async def _act(self, target_position: float, target_tilt: Optional[float]) -> None:
        self._cancel_requested = False

        target_position = float(max(0.0, min(100.0, target_position)))
        if target_tilt is not None:
            target_tilt = float(max(0.0, min(100.0, target_tilt)))

        self._log("act_begin", target_position=target_position, target_tilt=target_tilt)

        # Tilt-only fast path
        if abs(target_position - self.last_position) < EPS:
            if target_tilt is None or abs(target_tilt - self.last_tilt) < EPS:
                await self._motor(STOPPED)
                self.last_timestamp_millis = self._now_millis()
                self._push_state()
                self._log("act_path", mode="idle")
                return

            tilt_direction = UP if target_tilt > self.last_tilt else DOWN
            self._log("act_path", mode="tilt_only", tilt_dir=tilt_direction)
            await self._motor(tilt_direction)
            await self._act_tilt(target_tilt)
            await self._motor(STOPPED)
            self.last_timestamp_millis = self._now_millis()
            self._clamp()
            self._log("act_done", final_position=round(self.last_position, 3), final_tilt=round(self.last_tilt, 3))
            self._push_state()
            return

        # Normal sequence
        target_direction = UP if target_position > self.last_position else DOWN
        self._log("act_path", mode="move_sequence", move_dir=target_direction)

        await self._motor(target_direction)
        await self._act_tilt(100.0 if target_direction == UP else 0.0)
        await self._act_position(target_position, target_direction)

        if target_tilt is not None and abs(target_tilt - self.last_tilt) > EPS:
            post_dir = UP if target_tilt > self.last_tilt else DOWN
            await self._motor(post_dir)
            await self._act_tilt(target_tilt)

        await self._motor(STOPPED)
        self.last_timestamp_millis = self._now_millis()
        self._clamp()
        self._log("act_done", final_position=round(self.last_position, 3), final_tilt=round(self.last_tilt, 3))
        self._push_state()

    # ---- Commands → targets mapping
    async def async_open_cover(self, **kwargs: Any) -> None:
        self._log("cmd_open_cover")
        await self._act(target_position=100.0, target_tilt=100.0)

    async def async_close_cover(self, **kwargs: Any) -> None:
        self._log("cmd_close_cover")
        await self._act(target_position=0.0, target_tilt=0.0)

    async def async_stop_cover(self, **kwargs: Any) -> None:
        self._log("cmd_stop_cover")
        self._cancel_requested = True
        await self._motor(STOPPED)
        self.last_direction = STOPPED
        self.last_timestamp_millis = self._now_millis()
        self._push_state()
        self._log("cmd_stop_cover_done")

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        tp = float(int(kwargs["position"]))
        tt = 0.0 if tp < self.last_position else 100.0
        self._log("cmd_set_cover_position", target_position=tp, mapped_target_tilt=tt)
        await self._act(target_position=tp, target_tilt=tt)

    async def async_set_cover_tilt_position(self, **kwargs: Any) -> None:
        tt = float(int(kwargs["tilt_position"]))
        self._log("cmd_set_cover_tilt_position", target_tilt=tt)
        await self._act(target_position=self.last_position, target_tilt=tt)

    async def async_set_position_and_tilt(self, **kwargs: Any) -> None:
        tp = kwargs.get("position")
        tt = kwargs.get("tilt")
        if tp is None and tt is None:
            self._log("cmd_set_position_and_tilt_noop")
            return
        if tp is None:
            self._log("cmd_set_position_and_tilt_tilt_only", target_tilt=tt)
            await self._act(target_position=self.last_position, target_tilt=float(int(tt)))
            return
        if tt is None:
            tpv = float(int(tp))
            ttv = 0.0 if tpv < self.last_position else 100.0
            self._log("cmd_set_position_and_tilt_pos_only", target_position=tpv, mapped_target_tilt=ttv)
            await self._act(target_position=tpv, target_tilt=ttv)
            return
        self._log("cmd_set_position_and_tilt", target_position=tp, target_tilt=tt)
        await self._act(target_position=float(int(tp)), target_tilt=float(int(tt)))
