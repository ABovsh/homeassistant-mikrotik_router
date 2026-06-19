# CLAUDE.md - Mikrotik Router HACS Integration

## Project

- **Domain:** `mikrotik_router` | **Version:** tracks `manifest.json` (currently 2.4.4) | **IoT:** `local_polling`
- **HA Min:** 2024.3.0 (`hacs.json`) | **Fork of:** `jnctech/homeassistant-mikrotik_router`
- **Repo:** `github.com/ABovsh/homeassistant-mikrotik_router` (Anton's **private fork**, public on GitHub)
- **Deps:** `librouteros>=3.4.1,<4.0`, `mac-vendor-lookup>=0.1.12`
- **Platforms:** sensor, binary_sensor, switch, button, device_tracker, update
- **What this fork adds vs upstream:** LTE signal/band sensors (RSRP/RSRQ/SINR/CQI/RSSI, with RSSI
  derived when the R11e omits it) + an LTE-only `network-mode` switch, auto-discovering LTE interfaces.

## Workflow (this is Anton's private fork — overrides upstream ceremony)

- **Push directly to `master`. No feature branches, no PRs, no `dev`.** (Stale `dev`/`feature/*`/`docs/*`
  remote branches are upstream leftovers — ignore them; do not cut releases by merging `dev`.)
- **Every change:** bump `manifest.json` `version`, run `ruff` + `pytest`, commit conventional
  (`fix:`/`feat:`/`refactor:`/`chore:`), push `master`.
- **Do NOT engage jnctech's ADR / CHANGE-REGISTER / ISSUES / FEATURE-POLL ceremony.** Those `docs/`
  files belong to upstream; this fork doesn't maintain them.
- **No `git tag` / GitHub release** unless Anton explicitly asks.
- **No `Co-Authored-By` trailer** in commits.

## Testing & quality

- Run the suite natively: `python3 -m pytest tests/` (this Linux host pip-installs
  `pytest-homeassistant-custom-component`; no Docker needed).
- **Do NOT set `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`** — the HA test fixtures (`hass`, etc.) come from the
  pytest-HA plugin; disabling autoload makes the whole suite error on collection.
- `ruff check custom_components/mikrotik_router/` must be clean.
- Keep SonarCloud Grade A (reliability/security/maintainability); cognitive complexity ≤15/function.

## Deploy to live HA (cp + restart)

1. **Back up the live dir OUTSIDE `custom_components/`:**
   `cp -r /mnt/ha/custom_components/mikrotik_router /mnt/ha/_integration_backups/mikrotik_router-<ts>`.
   NEVER back up to a sibling like `custom_components/mikrotik_router.backup-<ts>` — HA scans every
   subdir of `custom_components/` as an integration and the dotted name breaks setup of the real one
   (→ all entities `unavailable`).
2. `cp -r custom_components/mikrotik_router/. /mnt/ha/custom_components/mikrotik_router/`
3. `rm -rf /mnt/ha/custom_components/mikrotik_router/__pycache__`
4. **Restart HA** (not config-entry reload — new Python needs reimport; reload reuses the cached module).
   Token in `/opt/scripts/ha-config.env`. Verify `sensor.mikrotik_lte_rsrp` is not `unavailable`.

## Reference docs (upstream-maintained, integration-facing)

- [HA Coding Standards](docs/ha-coding-standards.md), [Quality Gates](docs/quality-gates.md),
  [Architecture Notes](docs/architecture.md), [LTE sensor spec](docs/internal/LTE_SENSOR_SPEC.md).

## Repo is public — don't leak homelab specifics

Anything committed here is visible to every user. Keep code/docs **integration-facing**. Tokens, MACs,
internal hostnames, SIM identifiers (IMEI/IMSI/ICCID), and router captures/debug dumps go in
`docs/internal/` (gitignored) or stay out of the repo entirely.
