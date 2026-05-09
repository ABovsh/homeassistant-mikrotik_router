# ADR-010: Migrate to librouteros 4.x (remove `<4.0` pin)

**Date:** 2026-05-09
**Status:** Proposed

## Context

`v2.3.14` shipped a stopgap that pinned `librouteros>=3.4.1,<4.0` in `manifest.json` to revert all users to the last known working state after librouteros 4.0.1 broke the connect path (#55, #56). The pin is a workaround — the integration still calls the librouteros 3.x API. Upstream `tomaae/homeassistant-mikrotik_router` is suffering the same break (issues #477, #481, #487, #488; PRs #476, #480, #483, #484, #486, #489 — all unmerged) and users on HA 2026.4+ / Python 3.14 are independently patching forks. Holding the pin indefinitely is fragile:

- HA Core or other custom components may eventually require `librouteros>=4`, forcing a conflict.
- Python 3.14 wheel availability for older librouteros is not guaranteed long-term.
- New librouteros features and bug fixes (the 4.x branch is the maintained line) are unavailable while pinned.

The librouteros 4.0 changelog and the upstream community PRs converge on two breaking changes the integration must address:

1. **`connect()` kwarg rename:** `login_methods=` → `login_method=` (singular).
2. **`login_method` value type:** must be a callable (`librouteros.login.plain` or `librouteros.login.token`), not the string `"plain"` / `"token"`.

Our codebase currently passes `login_methods=self._login_method` (line 102 of `mikrotikapi.py`) where `self._login_method` is the string `"plain"` (default from `const.py:21`).

A second class of break has shown up downstream of the pin: `coordinator.py:710` raises `KeyError` when the configured username is missing from the `/user` print result (upstream #487, fork #65 area). That defect is independent of the librouteros migration and is tracked separately (see ISS for new-device-discovery / coordinator hardening) — this ADR scopes only the library migration.

## Decision

Migrate to librouteros 4.x in a single dedicated release (target `v2.4.0`):

1. **Resolve the configured string to a callable at API construction time.**
   - `mikrotikapi.py` imports `from librouteros.login import plain, token`.
   - The `__init__` accepts `login_method: str` unchanged (config-flow contract preserved) and stores a private `self._login_method_fn` mapped via `{"plain": plain, "token": token}[login_method]`.
   - `connect()` passes `login_method=self._login_method_fn` (singular kwarg, callable value).
2. **Keep `DEFAULT_LOGIN_METHOD = "plain"` in `const.py`** — the string is the user-visible/config-stored representation; the callable lives only inside `MikrotikAPI`. No config-flow migration is required.
3. **Bump the floor and drop the cap:** `manifest.json` requirements → `"librouteros>=4.0,<5"`. The `<5` cap is a defensive guard against the next major bump; we'll drop it once we observe 5.x.
4. **Audit other 4.0 breaking changes** before merge — at minimum: `Path.update()` / `Path()` call signatures (used by `set_value`, `execute`, `run_script`); `query()` return shape; exception class names. Add regression tests for any surface that changed.
5. **Cut a `v2.4.0`** release. This is a major-minor bump (not a hotfix) because the dependency floor moves and we expect a soak window.

## Alternatives Considered

- **Hold the `<4.0` pin indefinitely.** Rejected — pip-resolution fragility, locks us out of upstream librouteros bug fixes, and users sharing an environment with another HA component that requires librouteros 4 will fail to install. The stopgap was always meant to be temporary.
- **Vendor a shim that accepts both signatures.** Rejected — adds a permanent compatibility layer for a one-time migration, and the cost of supporting both code paths in tests outweighs the benefit. We control the dep floor; we should just move it.
- **Fork librouteros.** Rejected — adds maintenance burden far outweighing the migration cost.
- **Defer to wait for upstream `tomaae` to merge a fix.** Rejected — upstream is unresponsive (multiple equivalent PRs sitting open since April 2026). The fork's value proposition is shipping fixes upstream won't.

## Consequences

- **New minimum dependency:** `librouteros>=4.0`. Users who somehow have librouteros 3.x pinned by another path will see a resolver conflict on upgrade — acceptable; this is a one-time floor bump and HA/HACS handle it.
- **No config-flow changes.** Existing `login_method` config entries (string `"plain"` or `"token"`) keep working unchanged because the resolution happens inside `MikrotikAPI.__init__`.
- **Test surface grows by ~3 cases:** mapping table covers `"plain"`, `"token"`, and an unknown value (must raise a clear error rather than silently falling through).
- **Release notes must call out the floor bump** so users on librouteros 3.x in pinned environments aren't surprised.
- **Live-validation required** on the same hardware mix used for the v2.3.14 pin (hAP ac2, hAP ax3, RB4011, CRS310) before merging to master. Same matrix gives us a clean before/after.
- **The `<4.0` pin is removed in the same PR** as the code changes — never on its own — so we never ship an installable version that calls the 3.x API against a 4.x library or vice versa.
