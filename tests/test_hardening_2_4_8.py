"""Hardening tests for the 2.4.8 audit round.

Each test pins one verified defect fixed this round:

* A01 — the optional /interface/lte capability probe must not disconnect a
  non-LTE router (disconnect_on_error=False).
* A02 — RSSI derivation rejects a 0/NaN/inf RSRQ and oversized inputs instead of
  emitting a fake full-strength RSSI or crashing the update.
* A03 — a literal "0"/"0.0" signal string normalises to None like a numeric 0.
* A04 — the scan-interval option is clamped to an upper bound and the throughput
  divisor uses total_seconds() (a multi-day interval would otherwise wrap to 0).
* A07 — uptime parsing handles a millisecond token instead of reading it as minutes.
* B01 — a sensor whose attribute is missing reads None, not KeyError.
* C01 — config-flow connection validation closes its session.
* C02 — diagnostics redacts the router host.
* C06 — release-note version enumeration is capped.
* C08 — firmware install raises when a backup/upgrade command fails.

(A05 — API disconnect on unload — is covered in tests/test_init.py.)
"""

from __future__ import annotations

from time import monotonic
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.mikrotik_router import config_flow
from custom_components.mikrotik_router.config_flow import MikrotikControllerConfigFlow
from custom_components.mikrotik_router.const import (
    MAX_SCAN_INTERVAL,
    TO_REDACT,
)
from custom_components.mikrotik_router.coordinator import (
    MikrotikCoordinator,
    _parse_uptime_to_seconds,
)
from custom_components.mikrotik_router.mikrotikapi import MikrotikAPI
from custom_components.mikrotik_router.sensor import MikrotikSensor
from custom_components.mikrotik_router.update import (
    MAX_CHANGELOG_VERSIONS,
    MikrotikRouterBoardFWUpdate,
    MikrotikRouterOSUpdate,
    generate_version_list,
)

from homeassistant.exceptions import HomeAssistantError

from .test_lte import SAMPLE_IFACE, make_lte_coordinator


# ---------------------------------------------------------------------------
# A01 — LTE probe must not disconnect a non-LTE router
# ---------------------------------------------------------------------------


class _RecordingAPI:
    """Records query kwargs; mimics a router whose /interface/lte path is empty."""

    def __init__(self):
        self.query_kwargs = []

    def query(self, path, **kwargs):
        self.query_kwargs.append(kwargs)
        return []


class TestLteProbeOptional:
    def test_probe_uses_non_disconnecting_query(self):
        coordinator = object.__new__(MikrotikCoordinator)
        coordinator.api = _RecordingAPI()
        coordinator.support_lte = True

        coordinator._detect_lte_support()

        assert coordinator.support_lte is False
        assert coordinator.api.query_kwargs[-1].get("disconnect_on_error") is False


# ---------------------------------------------------------------------------
# A02 — RSSI derivation guards
# ---------------------------------------------------------------------------


class TestDeriveRssiGuards:
    def test_zero_rsrq_returns_none(self):
        # rsrq == 0 means the modem omitted it; deriving would fake a perfect link.
        assert MikrotikCoordinator._derive_rssi(-100, 0, "20Mhz") is None
        assert MikrotikCoordinator._derive_rssi(-100, "0.0", "20Mhz") is None

    def test_non_finite_inputs_return_none(self):
        assert MikrotikCoordinator._derive_rssi("inf", -8, "20Mhz") is None
        assert MikrotikCoordinator._derive_rssi(-100, "nan", "20Mhz") is None

    def test_oversized_input_returns_none(self):
        assert MikrotikCoordinator._derive_rssi("1" * 400, -8, "20Mhz") is None

    def test_valid_inputs_still_derive(self):
        assert MikrotikCoordinator._derive_rssi(-106, -9.5, "20Mhz") == -76


# ---------------------------------------------------------------------------
# A03 — zero-like signal STRINGS normalise to None
# ---------------------------------------------------------------------------


class TestZeroStringSignalNormalised:
    def test_zero_string_rsrp_becomes_none(self):
        monitor = [
            {
                "registration-status": "searching",
                "rsrp": "0",
                "rsrq": "0.0",
                "sinr": "3",
            }
        ]
        coordinator = make_lte_coordinator(iface_source=SAMPLE_IFACE, monitor_source=monitor)
        coordinator.get_lte()
        data = coordinator.ds["lte"]["lte1"]

        assert data["rsrp"] is None
        assert data["rsrq"] is None
        # sinr is a legitimate 0-capable reading and must survive as-is.
        assert data["sinr"] == "3"


# ---------------------------------------------------------------------------
# A04 — scan-interval upper clamp
# ---------------------------------------------------------------------------


def _coordinator_with_options(options):
    coordinator = object.__new__(MikrotikCoordinator)
    coordinator.config_entry = SimpleNamespace(options=options)
    return coordinator


class TestScanIntervalUpperClamp:
    def test_huge_value_is_capped(self):
        coordinator = _coordinator_with_options({"scan_interval": 999999})
        # total_seconds(), not .seconds, so a multi-day value can't wrap to 0.
        assert coordinator.option_scan_interval.total_seconds() == MAX_SCAN_INTERVAL

    def test_one_day_does_not_wrap_to_zero(self):
        coordinator = _coordinator_with_options({"scan_interval": 86400})
        assert coordinator.option_scan_interval.total_seconds() == MAX_SCAN_INTERVAL

    def test_arbitrary_precision_int_is_capped_not_overflowed(self):
        # Python ints are arbitrary precision, so a giant value clamps to MAX
        # rather than raising; either way it never reaches the divisor as 0.
        coordinator = _coordinator_with_options({"scan_interval": 10**400})
        assert coordinator.option_scan_interval.total_seconds() == MAX_SCAN_INTERVAL


# ---------------------------------------------------------------------------
# A07 — uptime millisecond token
# ---------------------------------------------------------------------------


class TestUptimeMilliseconds:
    def test_milliseconds_only_is_zero(self):
        assert _parse_uptime_to_seconds("500ms") == 0

    def test_seconds_with_trailing_ms(self):
        assert _parse_uptime_to_seconds("3s500ms") == 3

    def test_full_string_unaffected(self):
        assert _parse_uptime_to_seconds("1w2d3h4m5s") == 604800 + 172800 + 10800 + 240 + 5


# ---------------------------------------------------------------------------
# B01 — missing sensor attribute → None, not KeyError
# ---------------------------------------------------------------------------


class TestSensorMissingAttribute:
    def test_missing_attribute_returns_none(self):
        sensor = object.__new__(MikrotikSensor)
        sensor._data = {"rsrp": "-93"}  # 'sinr' absent (empty LTE monitor row)
        sensor.entity_description = SimpleNamespace(data_attribute="sinr")

        assert sensor.native_value is None

    def test_present_attribute_passes_through(self):
        sensor = object.__new__(MikrotikSensor)
        sensor._data = {"sinr": "6"}
        sensor.entity_description = SimpleNamespace(data_attribute="sinr")

        assert sensor.native_value == "6"


# ---------------------------------------------------------------------------
# C01 — config-flow validation closes its session
# ---------------------------------------------------------------------------


class _FakeValidationAPI:
    instances = []

    def __init__(self, **kwargs):
        self.error = ""
        self.disconnected_with = None
        _FakeValidationAPI.instances.append(self)

    def connect(self):
        return True

    def disconnect(self, location="unknown", error=None):
        self.disconnected_with = location


class TestConfigFlowValidationDisconnect:
    def test_successful_validation_disconnects(self, monkeypatch):
        _FakeValidationAPI.instances.clear()
        monkeypatch.setattr(config_flow, "MikrotikAPI", _FakeValidationAPI)

        flow = object.__new__(MikrotikControllerConfigFlow)
        data = {
            "host": "10.0.0.1",
            "username": "u",
            "password": "p",
            "port": 0,
            "ssl": False,
            "verify_ssl": False,
        }
        result = flow._validate_connection(data)

        assert result is None
        assert _FakeValidationAPI.instances[-1].disconnected_with == "config_flow_validation"


# ---------------------------------------------------------------------------
# C02 — diagnostics redacts the host
# ---------------------------------------------------------------------------


def test_host_is_redacted():
    assert "host" in TO_REDACT


# ---------------------------------------------------------------------------
# C06 — release-note version enumeration is capped
# ---------------------------------------------------------------------------


class TestVersionListCap:
    def test_wide_gap_is_capped(self):
        versions = generate_version_list("7.16.2", "7.17.0")
        assert len(versions) <= MAX_CHANGELOG_VERSIONS

    def test_small_gap_is_exact(self):
        versions = generate_version_list("7.16.0", "7.16.2")
        assert versions == ["7.16.2", "7.16.1", "7.16.0"]


# ---------------------------------------------------------------------------
# C08 — firmware install raises on a failed command
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_routeros_install_aborts_on_failed_backup():
    entity = object.__new__(MikrotikRouterOSUpdate)
    entity.hass = SimpleNamespace(async_add_executor_job=AsyncMock(return_value=False))
    entity.coordinator = SimpleNamespace(execute=lambda *a, **k: False)

    with pytest.raises(HomeAssistantError):
        await entity.async_install("7.17", backup=True)


@pytest.mark.asyncio
async def test_routerboard_install_does_not_reboot_on_failed_upgrade():
    calls = []

    async def fake_exec(func, *args):
        calls.append(args)
        return False  # upgrade command fails

    entity = object.__new__(MikrotikRouterBoardFWUpdate)
    entity.hass = SimpleNamespace(async_add_executor_job=fake_exec)
    entity.coordinator = SimpleNamespace(execute=lambda *a, **k: False)

    with pytest.raises(HomeAssistantError):
        await entity.async_install("7.17", backup=False)

    # Only the upgrade command was issued; reboot was never reached.
    assert len(calls) == 1


def test_monotonic_clock_used_for_reconnect_throttle():
    """A06: the reconnect throttle compares against monotonic(), not wall-clock."""
    api = MikrotikAPI("10.0.0.1", "u", "p")
    api._connected = False
    api._connection = None
    api._connection_retry_sec = 58

    attempts = []
    api.connect = lambda: attempts.append(1) or False  # type: ignore[assignment]

    # Recent epoch (monotonic) → still throttled, connect() not attempted.
    api._connection_epoch = monotonic()
    assert api.connection_check() is False
    assert attempts == []

    # Epoch older than the retry window → connect() is attempted.
    api._connection_epoch = monotonic() - 120
    assert api.connection_check() is False
    assert attempts == [1]
