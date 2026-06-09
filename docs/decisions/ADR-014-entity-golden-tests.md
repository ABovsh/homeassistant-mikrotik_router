# ADR-014 — Entity-golden test framework (syrupy snapshots over a mocked API boundary)

**Status:** Accepted — framework decision; implementation lands incrementally (syrupy wiring + first platform exemplar, then per-platform). Established by a multi-agent design panel (two senior architects + an adversarial senior reviewer) on 2026-06-08.
**Date:** 2026-06-08
**Relates:** `ADR-007` (helper extraction — this is its testing counterpart), `ENH-260608-test-suite-hardening`. Sets the *durable destination* for entity tests that the spec'd-MagicMock factory work (`make_mock_coordinator → spec=`) was only a bridge toward.
**Numbering note:** ADR-013's note tentatively reserved **014** for the `proto/fw-version-sot` prototype. That prototype's purpose — sourcing the firmware version for read-only users — was **achieved by #82** (`_parse_fw_version_from_resource`, on `dev`), so the prototype is obsolete and needs no ADR. **014 is therefore taken here.**

## Context

Entity-level tests (`tests/test_binary_sensor.py`, `test_button.py`, `test_device_tracker.py`, `test_entity.py`, `test_switch.py`, `test_update.py`, plus `test_sensor.py`) build the coordinator as a hand-mocked `MagicMock` (`tests/conftest.py:72-129`) and patch `CoordinatorEntity.__init__`. This has three problems:

1. **Yes-man mocks hide drift.** A bare `MagicMock` returns a truthy child for *any* attribute, so a renamed/removed coordinator member passes silently. (#95 fixed the *description* factory this way; `make_mock_coordinator → spec=` was the planned coordinator counterpart.)
2. **The entity-enumeration funnel is untested.** Every platform's `async_setup_entry` delegates to `entity.async_add_entities` (`entity.py:223`), which is `# pragma: no cover` — and `sonar-project.properties` excludes all platform files from coverage with the justification "require a running HA instance."
3. **A coordinator decomposition is on the roadmap** (`refactor-strategy` Phase 2; deferred — see the descope below). Any test scaffolding coupled to today's coordinator *shape* becomes churn the moment the god-object is split.

A spec'd-`MagicMock` factory addresses (1) but not (2) or (3): `spec=` pins the *method* surface, not the `.data`/`.config_entry` *value* surface that entity tests actually read, and it stays coupled to the current class shape. The adversarial reviewer's evidence (234 existing coordinator tests already cover logic via `object.__new__`; the gap is entity-surface, not logic) confirmed the spec'd factory is a low-yield bridge, not the destination.

HA's own testing guide and `pytest-homeassistant-custom-component` (already a dependency) recommend testing entities through the **real setup path** — `MockConfigEntry` + `async_setup_entry` + the client mocked at the boundary + **syrupy** snapshots asserting `hass.states` — which is *shape-agnostic*: it survives the decomposition without test edits because the tests never name the coordinator.

## Decision

Adopt a **layered test taxonomy** with **entity-golden (snapshot) tests** as the entity-surface layer:

- **L0 — pure-logic unit tests** (keep as-is): parsing, dedup, uptime, the §2.1 fall-through fixes. Built via `object.__new__(MikrotikCoordinator)` (`test_coordinator.py:34`) or, post-decomposition, by constructing the extracted fetcher/state-machine classes directly. Snapshots are **not** used here — a snapshot would entrench whatever the parser emits without asserting it is *correct*.
- **L1 — entity-golden tests** (new, the subject of this ADR): set up the integration with a `MockConfigEntry`, patch the API at the single boundary seam `coordinator.MikrotikAPI` with the existing `MockMikrotikAPI` (`conftest.py:132-165`) fed deterministic per-path RouterOS fixtures, run `async_setup_entry`, then assert every produced entity's **state + attributes + registry entry** with syrupy `snapshot_platform`. `.ambr` snapshots live in `tests/snapshots/`.
- **L2 — flow tests** (already partly present): config/options/reauth via `MockConfigEntry` (`test_config_flow.py`).

**Hard scoping rules (from the adversarial review):**

1. **Goldens assert ENTITY OUTPUT ONLY — never the 38-key `self.ds`.** A `ds`-level snapshot diff is unreviewable during a refactor (a reviewer cannot tell "reordered a merge and dropped a host's `is_wireless`" from expected churn); the golden would *become* the bug.
2. **Determinism is mandatory, not optional.** Snapshots are non-deterministic theater unless the data path's non-determinism is frozen: `AsyncMacLookup` (`coordinator.py:327`), `utcnow`/`dt_now` (`:198`, `:606`, `:1658`), and host/registry ordering. Each golden run must pin these (patched lookup, frozen time, sorted enumeration).
3. **The setup fixture is the unit of reuse.** Entity tests call a `setup_integration` / `mock_config_entry` fixture pair, never an inline mock. The fixture's *internals* (today: spec-able mocks; tomorrow: real coordinator behind `MockConfigEntry`) can change without editing a single test body — this is what makes the layer survive the decomposition.

## Alternatives Considered

- **Spec'd `MagicMock` coordinator factory (`make_mock_coordinator → spec=`).** Pins the method surface and catches renames, but not the `.data` value surface entity code reads, and stays coupled to the current shape. **Kept only as an optional short-lived bridge**, not the destination; superseded by L1 goldens for entity tests.
- **Hand-asserted entity tests** (the status quo, expanded). Brittle and verbose; every new attribute means editing many asserts. Rejected — snapshots collapse that to one reviewed `.ambr`.
- **`create_autospec(MikrotikCoordinator, instance=True)`.** More faithful (async-aware, signature-checked) than `MagicMock(spec=)`, but *still* doesn't model the instance `.data`/`.config_entry` surface, and is throwaway at decomposition. Rejected for the same shape-coupling reason.
- **Coordinator/`ds`-level snapshots.** Rejected outright — unreviewable diffs (rule 1).
- **Do nothing / proceed straight to the decomposition.** Rejected: the decomposition is exactly when a shape-agnostic safety net is most valuable; building it first de-risks the refactor.

## Consequences

- **New dev dependency: `syrupy`** (+ `HomeAssistantSnapshotExtension` conftest wiring). `.ambr` files become reviewed artifacts under `tests/snapshots/`.
- **Coverage win:** goldens exercise the `# pragma: no cover` entity funnel (`entity.py:223`) through real `hass`, letting the `sonar-project.properties` platform-coverage exclusions shrink — concrete progress toward the Silver ≥95% bar.
- **Review discipline required:** `--snapshot-update` must never be a reflex. A golden diff during the decomposition is a signal to *read*, not rubber-stamp; the entity-output scoping (rule 1) is what keeps diffs reviewable.
- **Fixture investment:** the make-or-break work is realistic, deterministic per-path `MockMikrotikAPI` fixtures. This is the bulk of the effort and must not be rushed.
- **Bridge retirement:** once a platform has golden coverage, its hand-mocked entity tests (and any spec'd-factory scaffolding) can be retired. The L0 logic tests stay.
- **Portability (maintainer directive — full playbook):** the framework is repo-agnostic. Extract a reusable template (syrupy wiring, `setup_integration` skeleton, boundary-mock + determinism-freeze conventions, the L0/L1/L2 taxonomy) to `config/docs/templates/hacs-testing/` for the maintainer's other HACS integrations. The *pattern* ports to any HA integration regardless of coordinator shape; the MikroTik-specific part is only the per-path RouterOS fixtures.

## Implementation plan (incremental)

1. Add `syrupy` to `requirements_tests.txt` / `requirements_dev.txt`; wire `HomeAssistantSnapshotExtension` + a `snapshot` fixture in `conftest.py`.
2. Add the `setup_integration` / `mock_config_entry` fixture pair (`MockConfigEntry(domain="mikrotik_router", data=…, options=…)` + `patch("…coordinator.MikrotikAPI", …MockMikrotikAPI)` + `async_setup` + `async_block_till_done`), with the determinism freezes (rule 2) centralised in the fixture.
3. Extend `MockMikrotikAPI` with realistic per-path RouterOS response fixtures (the bulk of the work).
4. Land **one platform exemplar** first (sensor — pairs with the #86 `test_sensor.py` reference) using `snapshot_platform`; review the `.ambr`; establish the pattern.
5. Expand per platform (binary_sensor, switch, button, update, device_tracker), retiring each platform's hand-mocked entity tests as its golden lands.
6. Remove the now-covered `sonar-project.properties` platform exclusions.
7. Extract the portable template to `config/docs/templates/hacs-testing/`.

## Testing / verification

Run on the WSL2-on-`twentyone` runner under `python:3.13` **and** `python:3.14` (CI is authoritative on both). The first golden must be reviewed by hand (not `--snapshot-update`-generated blind) to validate the fixture produces the *correct* entity surface, not merely a stable one.

## Provenance

Facts cite code `file:line` on `dev`. The taxonomy, the entity-output scoping rule, and the determinism freezes are the synthesis of a design panel: two senior architects (decomposition-aligned + test-framework) and an adversarial senior reviewer whose code-grounded dissent (234 existing logic tests; `ds`-snapshots unreviewable; goldens are the durable/portable win) shaped the scoping rules above. HA-documented recommendations (`MockConfigEntry` + `async_setup` + `snapshot_platform`) are distinguished from project judgment (layer boundaries, fixture naming, exclusion removal) in the panel record.
