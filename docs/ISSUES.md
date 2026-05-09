# Issues — Mikrotik Router HACS Integration

## Current Priorities

1. ISS-260509-mikrotikapi-concurrency — `set_value`/`execute` iterate the librouteros response outside the API lock; rapid switch toggles can corrupt the socket stream and disconnect the integration (#64)
2. ISS-260509-librouteros-4x-migration — Solve the v2.3.14 workaround: migrate to librouteros 4.x and drop the `<4.0` pin (ADR-010, target v2.4.0)
3. ISS-260509-ha-2026.5-untested — HA 2026.5.0 / Python 3.14 not yet validated against the integration; testing planned
4. ISS-260509-upstream-demand-quickwins — Additive sensor wins driven by upstream demand (RX/queue drops, wireless signal/rate, container binary_sensor, UPS runtime_left timedelta)
5. ISS-260509-coordinator-access-keyerror — `coordinator.get_access` raises `KeyError` when configured user is missing from `/user` print (upstream #487)
6. ISS-260417-librouteros-4x-break — librouteros 4.0.1 breaks `connect()` kwarg; all users affected (hotfix v2.3.14 pins `<4.0`)
7. ISS-260320-new-device-discovery — New devices require HA restart to appear
8. ISS-260320-refactor-dedup — Refactor duplicated patterns
9. ISS-260326-tracker-wireless-detection — Device tracker uses old wireless detection logic

---

## Active

### ISS-260509-mikrotikapi-concurrency — set_value/execute corrupt socket under rapid use
**Type:** Bug
**Priority:** High
**Created:** 2026-05-09
**Status:** 🟡 In Progress — fix in `fix/api-concurrency-lock` (v2.3.16)

**Symptom:**
Rapidly toggling PoE switches in the HA UI causes the integration to disconnect. Traceback shows librouteros' `parse_word` raising `ValueError: not enough values to unpack (expected 3, got 2)` while iterating the response inside `_find_entry`. Subsequent polls then time out with `building list for path /ip/arp : timed out` and the coordinator marks itself disconnected. Reported in #64 (RB5009UPr+S+IN, RouterOS 7.22.2, HA 2026.5.0 / Python 3.14).

**Root cause:**
`MikrotikAPI.set_value()` and `MikrotikAPI.execute()` call `query(path, return_list=False)` which returns the librouteros `Path` object **outside** the API lock. They then call `_find_entry(response, ...)` — which iterates the Path and performs additional socket reads — also **outside** the lock. The 30s coordinator poll (`get_arp`, `get_health`, etc.) acquires the lock and reads from the same TCP socket concurrently. The librouteros parser sees a half-finished sentence from the interleaved reads and raises. `run_script()` already does this correctly (iterates inside the lock), so it was the model for the fix.

**Fix:**
Move `_find_entry` and the subsequent `response.update()` / `response(command, **params)` calls inside the existing `with self.lock:` block in `set_value` and `execute`. No public API changes.

**Why this just surfaced:**
The race has existed since the current `set_value`/`execute` shape was introduced. HA moved to Python 3.14 in [2026.3](https://www.home-assistant.io/blog/2026/03/04/release-20263/#running-on-python-314-), so the runtime change alone doesn't explain the timing — there were no reports of this race during the 2026.3 / 2026.4 windows. The first report (#64) is against 2026.5.0; whether 2026.5.0 changed something specific (service dispatch timing, executor pool sizing, or similar) is still being investigated. Either way the lock fix is correct and the race must be closed regardless of cause. Reporter confirmation requested in the GH thread (rollback test against v2.3.14).

---

### ISS-260509-librouteros-4x-migration — Solve the v2.3.14 workaround
**Type:** Migration
**Priority:** High
**Created:** 2026-05-09
**Status:** 🟡 Planned — ADR-010, target `v2.4.0`

**Context:**
v2.3.14 shipped a stopgap that pinned `librouteros>=3.4.1,<4.0` after librouteros 4.0.1 broke the connect path (#55, #56). The integration still calls the librouteros 3.x API (`mikrotikapi.py:102` passes the old kwarg `login_methods=`; `const.py:21` defines `DEFAULT_LOGIN_METHOD = "plain"` as a string, not the callable librouteros 4.x requires). The pin works but is fragile and locks us out of librouteros 4.x bug fixes. Upstream `tomaae` is suffering the same break (issues #477, #481, #487, #488; six independent unmerged PRs).

**Plan:** Per [ADR-010](decisions/ADR-010-librouteros-4x-migration.md):
- `mikrotikapi.py`: import `from librouteros.login import plain, token`. Map the configured string (`"plain"` / `"token"`) to the callable inside `__init__` and store as `self._login_method_fn`. Pass `login_method=self._login_method_fn` (singular kwarg) in `connect()`.
- `const.py`: leave `DEFAULT_LOGIN_METHOD = "plain"` unchanged — the string is the user-visible config value.
- `manifest.json`: change requirement to `librouteros>=4.0,<5`.
- Audit other 4.0 breaking changes (Path call signatures used by `set_value`/`execute`/`run_script`, `query()` return shape, exception class names). Add regression tests for any surface that changed.
- Live-validate against the v2.3.14 hardware matrix (hAP ac2, hAP ax3, RB4011, CRS310) before merging.
- Cut `v2.4.0` (minor bump — dependency floor moves).

**Out of scope:** the unrelated `KeyError` in `coordinator.get_access` (tracked separately as ISS-260509-coordinator-access-keyerror).

---

### ISS-260509-upstream-demand-quickwins — Additive sensors driven by upstream demand
**Type:** Feature
**Priority:** Medium
**Created:** 2026-05-09
**Status:** 🟡 Backlog — sequenced after ISS-260509-librouteros-4x-migration

**Context:**
[Upstream engagement cross-reference](UPSTREAM-ENGAGEMENT-2026-05.md) identified upstream feature requests whose underlying data is **already fetched** by our coordinator, so they're additive entity definitions in `*_types.py` with no coordinator changes. Mapping:

| Upstream # | Maps to | Source data |
|-----------|---------|-------------|
| #432 (RX FCS / port stats) | sensor-gap-analysis A1 (firewall counters), A2 (queue drops), A3 (link-downs) | already in `interface`, `nat`/`mangle`/`filter`/`raw` |
| #413, #233 (per-wireless registration entity, per-SSID client count) | sensor-gap-analysis A9, A10, A12 | already in `wireless_hosts`, `bridge_host` |
| #245 (UPS `runtime_left` as timedelta) | trivial conversion | already in `ups` |
| (FEATURE-POLL A11) | container running binary_sensor | already in `container` (switch exists; binary_sensor doesn't) |

**Plan:**
- Phase 1 (one PR): A1 + A2 + A3 + UPS timedelta. Pure `*_types.py` additions plus optional helper for the timedelta string format. ~7 new sensor descriptions, no coordinator touch, no breaking changes.
- Phase 2 (separate PR): A9 + A10 + container binary_sensor. Per-host attributes, requires care around entity churn; do after Phase 1 soaks.

**Why not first:** quality-gate constraint — these ride on top of the librouteros migration, so they should land after `v2.4.0` to keep the migration's blast radius small and reviewable.

---

### ISS-260509-coordinator-access-keyerror — `get_access` raises `KeyError` on missing user
**Type:** Bug
**Priority:** Medium
**Created:** 2026-05-09
**Status:** 🟡 Backlog

**Context:**
`coordinator.py:710` does `tmp_user[self.config_entry.data[CONF_USERNAME]]["group"]` with no guard for the configured username being absent from the `/user` print result. Upstream #487 reports this surfacing as `KeyError: 'Hass'` on RouterOS 7.22.2 / HA 2026.4.4 with the cAP. Independent of the librouteros migration — a configured user can legitimately disappear (renamed, removed, or filtered by group permissions).

**Plan:**
- Add a defensive lookup: `if username not in tmp_user: log warning, mark access as none, return`.
- Test fixture: `/user` print returning users that don't include the configured one.

---

### ISS-260509-ha-2026.5-untested — HA 2026.5.0 not yet validated
**Type:** Compatibility
**Priority:** Medium
**Created:** 2026-05-09
**Status:** 🟡 Backlog

**Context:**
HA 2026.5.0 (released 2026-05-06) is the first version where a user (#64) has reported the integration breaking. HA has been on Python 3.14 since [2026.3](https://www.home-assistant.io/blog/2026/03/04/release-20263/#running-on-python-314-), so the runtime alone isn't a sufficient explanation — the race in `set_value`/`execute` was present in 2026.3 and 2026.4 too without prior reports. The integration's CI matrix and local dev environment still target Python 3.13.

**Plan:**
- Add Python 3.14 to the CI matrix for the test job
- Validate the integration manually against HA 2026.5.0 (PoE switching, device tracker, sensors, services)
- Diff HA 2026.4 → 2026.5 release notes / commits for service-dispatch or executor-pool changes that could explain why #64 surfaced now
- Document any 2026.5.0-specific behaviour in README compatibility notes

---

### ISS-260507-ups-empty-path — Empty `/system/ups` path disconnects the integration
**Type:** Bug
**Priority:** High
**Created:** 2026-05-07
**Status:** 🔴 Closed — fixed in v2.3.15 (PR for `fix/v2.3.15-ups-poe-current`)

**Symptom:**
On routers with the UPS package enabled but no UPS configured, the integration tile shows "Failed setup, will retry: Mikrotik Disconnected" and never loads. Logs:
```
ERROR ... Mikrotik <host> error while path : no such item
DEBUG ... Finished fetching ... data in 3.380 seconds (success: False)
```
Reported in #61 (RouterOS 7.22.1 on CCR2116-12G-4S+).

**Root cause:**
`coordinator.get_ups()` always issued the `/system/ups monitor` query because the parsed `enabled` field defaulted to `True` when `/system/ups` was empty. The `vals` entry for `enabled` uses `source="disabled"` with `reverse=True`; `from_entry_bool` returns `not default` when the source key is missing, so `enabled` becomes `True` for an empty path. RouterOS then rejects `monitor` with "no such item", and `_query_command` treats it as a connection failure.

**Fix:**
Bail out of `get_ups()` early when `/system/ups` returns no entries — clear `ds["ups"]` and skip both `parse_api` and the `monitor` query.

---

### ISS-260507-poe-current-unit — PoE out current displayed 1000× too large
**Type:** Bug
**Priority:** Medium
**Created:** 2026-05-07
**Status:** 🔴 Closed — fixed in v2.3.15 (PR for `fix/v2.3.15-ups-poe-current`)

**Symptom:**
PoE out current sensor displays `~1234.56 mA` for a port drawing ~25 mA (DE locale shows `1.234,56 mA`). Reported in #60 (RB5009UPr+S+IN, RouterOS 7.22.2).

**Root cause:**
`sensor_types.py` declared `poe_out_current` with `native_unit_of_measurement=AMPERE` and `suggested_unit_of_measurement=MILLIAMPERE`. RouterOS reports the value already in milliamperes (test fixtures use raw integers like `180`, `310`), so HA's unit conversion turned `180 A → 180000 mA`.

**Fix:**
Set `native_unit_of_measurement=MILLIAMPERE`; remove `suggested_unit_of_measurement`.

---

### ISS-260417-librouteros-4x-break — librouteros 4.0.1 breaks connection for all users
**Type:** Bug
**Priority:** Critical
**Created:** 2026-04-17
**Status:** 🟡 In Progress — hotfix branch `fix/librouteros-4x-pin` (v2.3.14) pins `librouteros<4.0`. Proper 4.x migration tracked separately.

**Symptom:**
Users on v2.3.13 (or any prior release) see: `connect() got an unexpected keyword argument 'login_methods'. Did you mean 'login_method'?`

**Root cause:**
librouteros 4.0.1 renamed the `connect()` keyword argument `login_methods` → `login_method`. `manifest.json` declared `librouteros>=3.4.1` with no upper bound, so HACS auto-installed 4.0.1 on upgrade. `mikrotikapi.py:102` still passes the old name.

**Related GitHub issues:**
- #55 (reported 2026-04-10) — direct stack trace
- #56 (reported 2026-04-13) — same symptom post-HA-2026.4.2 update; references upstream #477

**Hotfix (v2.3.14):**
- `manifest.json`: pin `librouteros>=3.4.1,<4.0`

**Follow-up (new ISS to be created for future release):**
- Rename kwarg in `mikrotikapi.py` to `login_method`
- Audit remaining librouteros 4.0.1 breaking changes
- Bump floor to `>=4.0`, drop upper bound

---

### ISS-260320-new-device-discovery — New devices require HA restart to appear
**Type:** Feature
**Priority:** High
**Created:** 2026-03-20
**Status:** 🟡 Backlog
**Source:** coordinator.py line 692, entity.py lines 154-168

**Context:**
The `update_sensors` dispatcher was re-enabled in v2.3.6 to fix new devices not appearing, but it caused thousands of "does not generate unique IDs" log errors every 30s because `_check_entity_exists()` doesn't guard against re-adding existing entities. Reverted in v2.3.8.

**Remaining:**
- Track previously seen UIDs per data path in the coordinator (e.g. `self._known_uids["host"]`)
- Only fire `async_dispatcher_send("update_sensors", self)` when new UIDs appear that weren't in the previous set
- Alternatively, fix `_check_entity_exists()` to skip entities already in `platform.entities`
- Test: add a new host to `ds["host"]` mid-run and verify entity is created without log errors

---

### ISS-260320-refactor-dedup — Refactor duplicated patterns
**Type:** Refactoring
**Priority:** Medium
**Created:** 2026-03-20
**Status:** 🟡 Backlog

**Remaining:**
- coordinator.py: extract firewall rule dedup helper (get_nat/get_mangle/get_filter share ~75 LOC pattern)
- switch.py: extract base class for NAT/Mangle/Filter/Queue UID lookup (~50 LOC)
- ~~apiparser.py: extract shared path traversal from from_entry/from_entry_bool~~ ✅ Done in PR #30
- *_types.py: extract shared entity description base class (~80 LOC)

**Reference:** SonarCloud CPD exclusions already cover sensor_types.py and coordinator.py intentional repetition

---

## Backlog

### ISS-260326-tracker-wireless-detection — Device tracker uses old wireless detection logic
**Type:** Bug
**Priority:** Medium
**Created:** 2026-03-26
**Status:** 🟡 Backlog

**Context:**
`device_tracker.py` lines 157, 169, 199 check `source in ["capsman", "wireless"]` to determine wireless behavior (connection state, icon, attributes). The new `_is_wireless_host()` method in coordinator.py correctly detects wireless clients via bridge host table (fixing hAP ac2), but device_tracker still uses the old check.

**Impact:**
On routers with empty registration tables (hAP ac2 with new WiFi package), wireless clients discovered via bridge table have `source="arp"`, so the device tracker:
- Uses timeout-based `is_connected` instead of registration-based
- Shows wired icon instead of wireless
- Does not show wireless signal/rate attributes

**Fix:**
- Add `is_wireless` bool field to host data in coordinator (set by `_is_wireless_host`)
- Update device_tracker.py to check `self._data.get("is_wireless")` instead of source

---

## Completed

### ISS-260320-test-coverage — Increase test coverage to ≥80%
**Type:** Testing | **Priority:** High | **Created:** 2026-03-20
**Status:** 🔴 Closed — 86% coverage achieved (565 tests, Phase 5 PR)

### ISS-260321-cognitive-complexity — Reduce cognitive complexity to ≤15 per function
**Type:** Quality | **Priority:** High | **Created:** 2026-03-21
**Status:** 🔴 Closed — fixed in refactor/legacy-cleanup (PR #30 + PR #51)

### ISS-260321-silent-failures — Silent failure patterns from security audit
**Type:** Bug/Quality | **Priority:** Medium | **Created:** 2026-03-21
**Status:** 🔴 Closed — fixed in refactor/legacy-cleanup (PR #30 + PR #51)

### ISS-260326-slow-load — Startup bottlenecks blocking HA loading
**Type:** Bug/Performance | **Priority:** High | **Created:** 2026-03-26
**Status:** 🔴 Closed — fixed in v2.3.12 (claude/fix-homeassistant-slow-load)

### ISS-260320-deprecated-datetime — Remaining naive datetime.now() calls
**Type:** Bug | **Priority:** Medium | **Created:** 2026-03-20
**Status:** 🔴 Closed — fixed in v2.3.12 (claude/fix-homeassistant-slow-load)

### ISS-260325-attribute-bloat — ~1300 junk attributes on interface and tracker entities
**Type:** Bug/Quality | **Priority:** High | **Created:** 2026-03-25
**Status:** 🔴 Closed — fixed in v2.3.11-beta.1 (feature/attribute-cleanup)

### ISS-260325-mangle-dedup — Mangle rules with different interfaces removed as duplicates
**Type:** Bug | **Priority:** High | **Created:** 2026-03-25
**Status:** 🔴 Closed — fixed in PR #40 (fix/mangle-duplicate-interface)

### ISS-260324-arp-incomplete — ARP "incomplete" status incorrectly shows device as home
**Type:** Bug | **Priority:** High | **Created:** 2026-03-24
**Status:** 🔴 Closed — fixed in v2.3.10 (PR #38)

### ISS-260322-upstream-frs — Port upstream feature requests
**Type:** Feature | **Priority:** High | **Created:** 2026-03-22
**Status:** 🔴 Closed — released in v2.3.9 (PR #32)

### ISS-260320-options-flow-crash — Options flow crash on HA 2025.12+
**Type:** Bug | **Priority:** Critical | **Created:** 2026-03-20
**Status:** 🔴 Closed — fixed in v2.3.6 (PR #19)

### ISS-260320-blocking-io — Blocking I/O in async methods
**Type:** Bug | **Priority:** High | **Created:** 2026-03-20
**Status:** 🔴 Closed — fixed in v2.3.6 (PR #19)

### ISS-260320-deadlock-run-script — Deadlock in mikrotikapi.py run_script
**Type:** Bug | **Priority:** Critical | **Created:** 2026-03-20
**Status:** 🔴 Closed — fixed in v2.3.6 (PR #19)

### ISS-260320-sonarcloud-token — SonarCloud token expired
**Type:** Infrastructure | **Priority:** Medium | **Created:** 2026-03-20
**Status:** 🔴 Closed — burner token set, SonarCloud passing

### ISS-260320-dispatcher-spam — Duplicate entity log errors from update_sensors
**Type:** Bug | **Priority:** High | **Created:** 2026-03-20
**Status:** 🔴 Closed — dispatcher disabled in v2.3.8 (PR #26). Proper fix tracked as ISS-260320-new-device-discovery

### ISS-260320-ruff-migration — Migrate from Black+flake8 to Ruff
**Type:** Quality | **Priority:** Low | **Created:** 2026-03-20
**Status:** 🔴 Closed — completed in PR #29 (feature/tests-and-refactor). CI uses ruff, all files formatted.
