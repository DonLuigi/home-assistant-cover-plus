# CoverPlus (Cover+)

A Home Assistant custom integration that **adds smart capabilities to basic covers**.
Start with tilt orchestration for covers that lack tilt, and grow into richer behaviors (e.g., partial "daylight" openings).

- Time-based virtual model (ignores real cover state)
- Non-blocking calls to your real cover
- Clean pipeline: *pre-tilt → move → post-tilt*
- Custom services:
  - `cover.set_position_and_tilt` (entity service)
  - `coverplus.set_position_and_tilt` (domain service)

## Installation (HACS custom repo)

1. Push this repo to GitHub and tag a release (e.g. `v0.4.0`).
2. Home Assistant → HACS → Integrations → ⋮ → **Custom repositories**
   - URL: `https://github.com/<your-username>/coverplus`
   - Category: **Integration**
3. Add → Install → Restart Home Assistant.

### Manual install

Download the latest release zip and extract into HA config so you have:
```
<config>/custom_components/coverplus/*
```

## Configuration (YAML)

```yaml
cover:
  - platform: coverplus
    covers:
      - real_entity_id: cover.YOUR_REAL_COVER
        name: "CoverPlus Virtual Cover"
        open_time_sec: 20     # seconds for 0→100 position
        tilt_time_ms: 750     # ms for 0→100 tilt (slat flip)
        # trace_ticks: true    # optional: log every tick
```

### Logger (recommended while testing)

```yaml
logger:
  default: warning
  logs:
    custom_components.coverplus: debug
```

## Developer Tools → Services examples

**Open / Close / Stop**
```yaml
service: cover.open_cover
data:
  entity_id: cover.coverplus_virtual
```
```yaml
service: cover.close_cover
data:
  entity_id: cover.coverplus_virtual
```
```yaml
service: cover.stop_cover
data:
  entity_id: cover.coverplus_virtual
```

**Position only**
```yaml
service: cover.set_cover_position
data:
  entity_id: cover.coverplus_virtual
  position: 70
```

**Tilt only**
```yaml
service: cover.set_cover_tilt_position
data:
  entity_id: cover.coverplus_virtual
  tilt_position: 35
```

**Combined (entity service)**
```yaml
service: cover.set_position_and_tilt
data:
  entity_id: cover.coverplus_virtual
  position: 65
  tilt: 40
```

**Combined (domain service)**
```yaml
service: coverplus.set_position_and_tilt
data:
  entity_id: cover.coverplus_virtual
  position: 65
  tilt: 40
```

## Notes

- If Open moves the wrong way, an `invert_direction` option can be added easily in `_motor` (future enhancement).
- For script-driven real covers, prefer script `mode: parallel` or `queued`.
- Calibrate times carefully; they dominate accuracy.