"""Hardening tests for the 2.4.10 audit round.

Each test pins one verified defect fixed this round:

* V1 — concurrent reconnect must not open a second RouterOS session: connect()
  re-checks the connected state inside the lock and returns early.
* V2 — a missing /ip/accounting path returns 0 instead of calling None(...) and
  disconnecting the whole integration.
* V3 — a wireless virtual interface whose master-interface row is absent no
  longer raises KeyError (which aborted the poll).
* V4 — a string accounting threshold is coerced before the numeric comparison
  instead of raising TypeError.
* V5 — a binary sensor whose backing value is a non-bool ("unknown") reports
  None, not a truthy string.
* V6 — the host-tracking timeout is clamped to a sane minimum so 0/negative
  values can't make wired hosts permanently not_home.
* V7 — NaN/Inf LTE signal readings normalise to None (and sinr/cqi keep 0).
* V8 — a setup that fails after the first connection disconnects the API session
  instead of leaking it.
"""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.mikrotik_router import __init__ as mikrotik_init
from custom_components.mikrotik_router.binary_sensor import MikrotikBinarySensor
from custom_components.mikrotik_router.coordinator import MikrotikCoordinator
from custom_components.mikrotik_router.device_tracker import MikrotikHostDeviceTracker
from custom_components.mikrotik_router.mikrotikapi import MikrotikAPI

from .test_lte import SAMPLE_IFACE, make_lte_coordinator


# ---------------------------------------------------------------------------
# V1 — concurrent reconnect must not open a second session
# ---------------------------------------------------------------------------


class TestConnectRechecksUnderLock:
    def test_already_connected_skips_second_connect(self, monkeypatch):
        api = MikrotikAPI("10.0.0.1", "u", "p")
        api._connected = True
        api._connection = object()  # a live session from another job

        calls = []
        monkeypatch.setattr(
            "custom_components.mikrotik_router.mikrotikapi.librouteros.connect",
            lambda *a, **k: calls.append(1) or object(),
        )

        # connect() must see the existing session inside the lock and not open
        # a second one (which would leak the first).
        assert api.connect() is True
        assert calls == []


# ---------------------------------------------------------------------------
# V2 — missing /ip/accounting must not disconnect the integration
# ---------------------------------------------------------------------------


class TestAccountingSnapshotMissingPath:
    def test_missing_accounting_returns_zero_without_disconnect(self):
        api = object.__new__(MikrotikAPI)
        api._connected = True
        api._connection = object()
        api.client_traffic_last_run = None
        disconnects = []
        api.disconnect = lambda *a, **k: disconnects.append(a)
        api.connection_check = lambda: True
        api.query = lambda *a, **k: None  # /ip/accounting path absent

        assert api.take_client_traffic_snapshot(True) == 0
        assert disconnects == []


# ---------------------------------------------------------------------------
# V3 — wireless inheritance survives a missing master interface
# ---------------------------------------------------------------------------


class TestWirelessMissingMaster:
    def test_missing_master_does_not_raise(self):
        coordinator = object.__new__(MikrotikCoordinator)
        coordinator.ds = {"wireless": {}, "interface": {}}
        coordinator._wifimodule = "wireless"
        coordinator.api = SimpleNamespace(
            query=lambda *a, **k: [
                {
                    "name": "wlan2-virtual",
                    "master-interface": "wlan-does-not-exist",
                    "ssid": "guest",
                }
            ]
        )

        # Must not raise KeyError (which previously aborted the whole poll).
        coordinator.get_wireless()

        # Inherited fields stay at their "unknown" default since the master is
        # absent.
        assert coordinator.ds["wireless"]["wlan2-virtual"]["mode"] == "unknown"


# ---------------------------------------------------------------------------
# V4 — string accounting threshold is coerced, not crashed on
# ---------------------------------------------------------------------------


class TestAccountingThresholdCoercion:
    def test_string_threshold_does_not_raise(self):
        coordinator = object.__new__(MikrotikCoordinator)
        coordinator.api = SimpleNamespace(query=lambda *a, **k: [{"threshold": "256"}])

        # entry_count just under 90% of 256 → no exception, no warning path hit.
        coordinator._check_accounting_threshold(10)

    def test_non_numeric_threshold_is_ignored(self):
        coordinator = object.__new__(MikrotikCoordinator)
        coordinator.api = SimpleNamespace(query=lambda *a, **k: [{"threshold": "n/a"}])

        # Must return cleanly rather than raising.
        coordinator._check_accounting_threshold(10)


# ---------------------------------------------------------------------------
# V5 — binary sensor rejects non-bool backing values
# ---------------------------------------------------------------------------


class TestBinarySensorNonBool:
    def test_unknown_string_reads_none(self):
        sensor = object.__new__(MikrotikBinarySensor)
        sensor._data = {"status": "unknown"}
        sensor.entity_description = SimpleNamespace(data_attribute="status")

        assert sensor.is_on is None

    def test_real_bool_passes_through(self):
        sensor = object.__new__(MikrotikBinarySensor)
        sensor._data = {"status": True}
        sensor.entity_description = SimpleNamespace(data_attribute="status")

        assert sensor.is_on is True


# ---------------------------------------------------------------------------
# V6 — host-tracking timeout is clamped
# ---------------------------------------------------------------------------


def _host_tracker_with_timeout(value):
    tracker = object.__new__(MikrotikHostDeviceTracker)
    tracker._config_entry = SimpleNamespace(options={"track_network_hosts_timeout": value})
    return tracker


class TestTrackTimeoutClamp:
    def test_zero_is_clamped_to_minimum(self):
        tracker = _host_tracker_with_timeout(0)
        assert tracker.option_track_network_hosts_timeout == timedelta(seconds=1)

    def test_negative_is_clamped_to_minimum(self):
        tracker = _host_tracker_with_timeout(-30)
        assert tracker.option_track_network_hosts_timeout == timedelta(seconds=1)

    def test_valid_value_is_preserved(self):
        tracker = _host_tracker_with_timeout(300)
        assert tracker.option_track_network_hosts_timeout == timedelta(seconds=300)


# ---------------------------------------------------------------------------
# V7 — non-finite LTE signal readings normalise to None
# ---------------------------------------------------------------------------


class TestLteNonFiniteSignals:
    def test_nan_inf_signals_become_none(self):
        monitor = [
            {
                "registration-status": "registered",
                "rsrp": "nan",
                "rsrq": "inf",
                "rssi": "-60",
                "sinr": "inf",
                "cqi": "12",
            }
        ]
        coordinator = make_lte_coordinator(iface_source=SAMPLE_IFACE, monitor_source=monitor)
        coordinator.get_lte()
        data = coordinator.ds["lte"]["lte1"]

        assert data["rsrp"] is None
        assert data["rsrq"] is None
        assert data["rssi"] == "-60"
        # sinr non-finite → None, but a legitimate cqi value survives.
        assert data["sinr"] is None
        assert data["cqi"] == "12"


# ---------------------------------------------------------------------------
# V8 — a setup that fails after connecting disconnects the session
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_setup_failure_disconnects_api(monkeypatch):
    disconnects = []
    fake_api = SimpleNamespace(disconnect=lambda *a, **k: disconnects.append(a))

    class _FailingCoordinator:
        def __init__(self, hass, config_entry):
            self.api = fake_api

        async def async_config_entry_first_refresh(self):
            raise RuntimeError("first refresh failed")

    monkeypatch.setattr(mikrotik_init, "MikrotikCoordinator", _FailingCoordinator)
    monkeypatch.setattr(mikrotik_init, "_async_register_services", lambda hass: None)

    hass = SimpleNamespace(async_add_executor_job=AsyncMock())
    config_entry = SimpleNamespace()

    with pytest.raises(RuntimeError):
        await mikrotik_init.async_setup_entry(hass, config_entry)

    # The open session was closed instead of leaking across HA's setup retries.
    hass.async_add_executor_job.assert_awaited_once()
    assert hass.async_add_executor_job.await_args.args[0] == fake_api.disconnect
