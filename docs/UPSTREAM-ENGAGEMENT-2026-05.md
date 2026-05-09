# Upstream Engagement Cross-Reference — 2026-05

**Date:** 2026-05-09
**Branch:** `claude/review-engagement-requests-dIZVx`
**Status:** Plan only — no code changes in this commit

Survey of `tomaae/homeassistant-mikrotik_router` open issues and PRs as of 2026-05-09, mapped against the current state of this fork (`v2.3.16`).

---

## 1. Headline

The dominant signal upstream is the **HA 2026.4 / Python 3.14 / librouteros 4.x meltdown**. Six PRs and four issues are all chasing the same connect-path break, with hundreds of cumulative thumbs-up. Our v2.3.14 pin makes this fork *work*, but it doesn't *solve* the workaround. Solving it (ADR-010) is the lead deliverable.

The secondary signal is a backlog of long-standing `planned`-labelled feature requests upstream that have sat since 2022–2025. About half are already implemented in this fork; the rest map cleanly onto the existing `FEATURE-POLL.md` and `sensor-gap-analysis.md` items, so no new design surface is needed.

---

## 2. Solve the Workaround First — librouteros 4.x

| Item | Fork status |
|------|-------------|
| `connect() got an unexpected keyword argument 'login_methods'` (upstream #477, #481, #487, #488; PRs #476/#480/#483/#484/#486/#489) | **Mitigated, not solved.** v2.3.14 pinned `librouteros<4.0` in `manifest.json`. `mikrotikapi.py:102` still calls the 3.x API; `const.py:21` still defines `DEFAULT_LOGIN_METHOD = "plain"` as a string. |

**Plan:** ADR-010 (this PR) — proper migration in `v2.4.0`. Drops the pin, renames the kwarg, maps the string config value to the librouteros callable inside `MikrotikAPI.__init__` so the config-flow contract is preserved. ISS-260509-librouteros-4x-migration tracks the work.

This is the first deliverable. Quick wins below are sequenced after the migration ships.

---

## 3. Upstream Bugs — Cross-Reference

| Upstream # | Title | Fork status |
|-----------|-------|-------------|
| #477 | Loss of connection after HA 2026.4.2 | Mitigated by v2.3.14 pin. Properly resolved by ADR-010. |
| #488 | unexpected keyword 'login_methods' | Same as above. |
| #487 | KeyError 'Hass' in `coordinator.get_access` | **Not yet addressed.** Our `coordinator.py:710` has the same `tmp_user[username]["group"]` lookup with no `KeyError` guard. Add to fork backlog (separate ISS, separate PR — independent of librouteros migration). |
| #481 | SSL `RECORD_LAYER_FAILURE` + KeyError `current-firmware` after 2026.4.2 | KeyError part covered by upstream PR #428 (read-only firmware-version fetch). Worth porting once 4.x migration lands. SSL part is environmental and not actionable in our code. |
| #471 | OptionsFlow `AttributeError` (HA 2026.3 / Py 3.14) | **Already fixed** in fork v2.3.6 (PR #19, see ISS-260320-options-flow-crash). |
| #421 | `clients_wireless` always 0 in v2.2 (regression) | **Already fixed** in fork — `_is_wireless_host` rewrite (v2.3.x). |
| #433 | Crash on `/caps-man/registration-table` when wireless package disabled | **Status unknown.** Worth verifying against fork; if our query path hits the same endpoint without a capability check, file a follow-up. Adds to backlog ISS. |
| #418 | Deprecated `self.config_entry` setter (HA 2025.12) | **Already fixed** in fork v2.3.6 (PR #19). |
| #309 | `rate` attribute regression on port (since 2.1.4) | **Status unknown.** Quick check needed in `*_types.py` to confirm the port attribute is exposed. |

---

## 4. Upstream Feature Requests (`planned` label) — Cross-Reference

Highest community engagement first.

| Upstream # | Ask | Fork status / mapping |
|-----------|-----|-----------------------|
| #249 | LTE modem cell info (RSSI/RSRP/RSRQ/SINR, band, cell-id) — 26 comments | **Not implemented.** Maps to `FEATURE-POLL.md` B10 / `sensor-gap-analysis.md` B10. Quick win candidate. |
| #233 | Per-SSID/per-interface client count sensor — 12 comments | **Not implemented.** Adjacent to `sensor-gap-analysis.md` A12 (bridge host count) and existing `clients_wireless` sensor. Would derive from already-fetched `wireless_hosts`. Easy win once A12 lands. |
| #259 | PoE-out status + power per port — 2 👍 | **Already implemented** in fork — `poe_out_status`, `poe_out_voltage`, `poe_out_current`, `poe_out_power` all present in `sensor_types.py` (sensor-gap-analysis.md §Currently Surfaced). |
| #260 | WireGuard sensors (RouterOS 7) | **Not implemented.** Maps to `FEATURE-POLL.md` B2 / `sensor-gap-analysis.md` B2. Top-priority Phase 2 item. |
| #334 | Container sensors + start/stop | **Already implemented** in fork — see ADR-008. |
| #310 | Firewall RAW rules enable/disable | **Already implemented** in fork — see ADR-008. |
| #321 | DHCP client/relay/server values | **Partially implemented** in fork (DHCP client status/address; relay/server fields not yet). See ADR-008. |
| #413 | Per-wireless-registration entity (uptime, signal, CCQ) | **Not implemented.** Adjacent to `sensor-gap-analysis.md` A9/A10. Data is already fetched (`wireless_hosts`); just needs entity definitions. Easy win. |
| #255 | Send SMS via LTE | **Not implemented.** Out of scope for sensor expansion; would require a `service.send_sms`. Defer; low fit with current architecture. |
| #245 | `runtime_left` UPS attribute as `timedelta` | **Not implemented.** Trivial change — convert in `apiparser` or expose as a separate computed sensor. Quick win. |
| #298 | Service to refresh env vars after script | **Already implemented** in fork — see ADR-008 (refresh after `MikrotikScriptButton.async_press`). |
| #432 | Port RX FCS error / extended port stats | **Not implemented.** Maps to `sensor-gap-analysis.md` A2 (`tx-queue-drop`) and A3 (`link-downs`). Same data path; bundle. Easy win. |
| #111 | WAN RX/TX per VPN client | **Not implemented.** Niche; PPP active connection details (`sensor-gap-analysis.md` A13) covers the discovery half. Park for now. |
| #428 (PR) | Check firmware version even without write access | **Not implemented.** Worth porting — improves the integration for read-only API users and reduces required RouterOS permissions. Small PR. |

---

## 5. Sequencing

### Release cut 1 — `v2.4.0`: Solve the workaround
**Scope:** ADR-010 only. Drop the `<4.0` pin, migrate `mikrotikapi.py` to the librouteros 4.x signature, audit and patch any other 4.0 breaking changes that surface in tests, live-validate against the v2.3.14 hardware matrix.
**Why first:** the pin is the dominant pain point upstream and the only thing blocking us from being a clean drop-in for the 21+ frustrated upstream users on issue #477 alone.

### Release cut 2 — `v2.4.x` quick wins from upstream demand
After `v2.4.0` ships and soaks. All of these are additive (no breaking changes), data is already fetched, and they slot into existing `*_types.py` files:

1. `sensor-gap-analysis.md` A1 — Firewall rule byte/packet counters (covers upstream #432 partially)
2. A2 — Interface queue drops (covers upstream #432)
3. A3 — Interface link-downs counter (covers upstream #432)
4. A9/A10 — Wireless client signal & link rate (covers upstream #413, partially #233)
5. A11 — Container running binary_sensor
6. UPS `runtime_left` as `timedelta` (covers upstream #245)

### Release cut 3 — Hardening from upstream bug reports
1. Guard `coordinator.get_access` against missing user in `/user` print (covers upstream #487)
2. Capability-gate `/caps-man/registration-table` (covers upstream #433, pending verification)
3. Port upstream PR #428 — read-only firmware version fetch (covers upstream #481 partial)

### Release cut 4 — `v2.5.0`: Phase 2 new data sources
Drives from `FEATURE-POLL.md` B2 / B10 / B7 / B4 / B5 / B11 prioritization. Each requires a coordinator query, a capability gate, and entity definitions — bigger surface, separate ADRs per data source per CLAUDE.md ("ADR required for ... API contract ... changes").

---

## 6. Out of Scope for This Plan

- Upstream PR **#479** (stale-bot timer extension) — repo-governance change at upstream that doesn't affect us.
- Upstream **#255** (SMS via LTE) — viable but architecturally orthogonal; would need its own ADR for service contract.
- Upstream **#111** (per-VPN-client traffic) — niche; revisit if demand surfaces in our own tracker.

---

## 7. References

- `docs/decisions/ADR-008-upstream-feature-port.md` — prior round of upstream FR ports (#310, #321, #334, #298)
- `docs/decisions/ADR-010-librouteros-4x-migration.md` — this round's lead deliverable
- `docs/FEATURE-POLL.md` — community-facing feature poll (B-series)
- `docs/sensor-gap-analysis.md` — full A/B/C technical taxonomy
- `docs/ISSUES.md` — ISS-260417-librouteros-4x-break (the original break), ISS-260509-librouteros-4x-migration (the proper fix), ISS-260509-upstream-demand-quickwins (the additive backlog)
