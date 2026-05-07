# Issues — Mikrotik Router HACS Integration

## Current Priorities

1. ISS-260417-librouteros-4x-break — librouteros 4.0.1 breaks `connect()` kwarg; hotfix v2.3.14 pinned `<4.0` (proper 4.x migration tracked separately)
2. ISS-260320-new-device-discovery — New devices require HA restart (UID tracking in place, dispatcher needs entity guard hardening)

---

## Active

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
**Priority:** Medium
**Created:** 2026-03-20
**Status:** 🟡 In Progress — UID tracking infrastructure done, dispatcher disabled pending entity guard fix

**Done:**
- ✅ `_check_new_uids()` tracks UIDs per entity-relevant data path (`_ENTITY_UID_PATHS`)
- ✅ `_check_entity_exists()` guard improved (early return if entity_id in platform.entities)
- ✅ device_tracker callback ignores dispatches from main coordinator
- ✅ First-run skip prevents redundant entity setup during startup

**Remaining:**
- Harden entity guard: `async_add_entities` still causes "does not generate unique IDs" when called for existing entities even with the guard. Investigate HA's `EntityPlatform.entities` dict timing.
- Re-enable dispatcher once guard is validated in live environment
- Test: add new host mid-run, verify entity created without log errors

---

## Backlog

### ISS-260326-tracker-wireless-detection — Device tracker uses old wireless detection logic
**Type:** Bug
**Priority:** Medium
**Created:** 2026-03-26
**Status:** 🔴 Closed — fixed in feature/v240-issues

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

### ISS-260320-new-device-discovery — New devices require HA restart to appear
**Type:** Feature | **Priority:** High | **Created:** 2026-03-20
**Status:** 🟡 Partially done — UID tracking in place, dispatcher disabled pending entity guard hardening

### ISS-260320-refactor-dedup — Refactor duplicated patterns
**Type:** Refactoring | **Priority:** Medium | **Created:** 2026-03-20
**Status:** 🔴 Closed — firewall helper extracted (feature/v240-issues), switch toggle extracted (PR #51), apiparser extracted (PR #30). Entity description mixin deferred.

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
