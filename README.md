# CoverPlus (Cover+)

Add **smart, time-based tilt orchestration** to any basic cover. UI-configurable, YAML-friendly, and with a proper **reload** button in Developer Tools → YAML.

## Highlights
- Time-based virtual model (ignores real cover state)
- Non-blocking motor calls
- Clean pipeline: *pre-tilt → move → post-tilt*
- **Config Flow** (UI) or **YAML** (both top-level and `cover:` platform)
- Services:
  - `cover.set_position_and_tilt` (entity)
  - `coverplus.set_position_and_tilt` (domain)
- **Reload**: `coverplus.reload` via Developer Tools → YAML

## Configure

### A) UI (recommended)
Settings → Devices & Services → **Add Integration** → search **CoverPlus**.

### B) Top-level YAML (enables “Reload” button)
```yaml
coverplus:
  covers:
    - real_entity_id: cover.living_room_blind
      name: "CoverPlus Virtual Cover"
      open_time_sec: 20
      tilt_time_ms: 750
      # trace_ticks: true
```
**Reload:** Developer Tools → YAML → **CoverPlus: Reload** (calls `coverplus.reload`).

### C) `cover:` platform YAML (also supported)
```yaml
cover:
  - platform: coverplus
    covers:
      - real_entity_id: cover.living_room_blind
        name: "CoverPlus Virtual Cover"
        open_time_sec: 20
        tilt_time_ms: 750
```

## Logger
```yaml
logger:
  default: warning
  logs:
    custom_components.coverplus: debug
```