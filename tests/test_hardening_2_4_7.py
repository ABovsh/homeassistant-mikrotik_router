"""Hardening tests for the 2.4.7 audit round.

Covers:
* LTE signal fields (rsrp/rsrq/rssi) must read "unknown" (None), not a fake 0,
  when the modem omits them on a dropped/unregistered link.
* The scan-interval option is clamped to a safe lower bound so it can never be
  used as a zero divisor in throughput math nor busy-poll Home Assistant.
"""

from __future__ import annotations

from types import SimpleNamespace

from custom_components.mikrotik_router.coordinator import MikrotikCoordinator
from custom_components.mikrotik_router.const import DEFAULT_SCAN_INTERVAL

from .test_lte import make_lte_coordinator, SAMPLE_IFACE


# ---------------------------------------------------------------------------
# F2: signal sensors must not report a fake 0 on a dropped link
# ---------------------------------------------------------------------------


class TestLteSignalAbsentIsNone:
    """rsrp/rsrq/rssi default to 0 in parse_api; absent must surface as None."""

    def _monitor_without_signal(self):
        # Modem registered-but-searching: signal metrics omitted, sinr present.
        return [
            {
                "status": "searching",
                "registration-status": "searching",
                "current-operator": "unknown",
                "access-technology": "unknown",
                "sinr": "0",
            }
        ]

    def test_absent_rsrp_rsrq_rssi_become_none(self):
        coordinator = make_lte_coordinator(
            iface_source=SAMPLE_IFACE,
            monitor_source=self._monitor_without_signal(),
        )
        coordinator.get_lte()
        data = coordinator.ds["lte"]["lte1"]

        assert data["rsrp"] is None
        assert data["rsrq"] is None
        assert data["rssi"] is None

    def test_valid_sinr_zero_is_preserved(self):
        """0 dB SINR is a legitimate (poor) reading — it must NOT be nulled."""
        coordinator = make_lte_coordinator(
            iface_source=SAMPLE_IFACE,
            monitor_source=self._monitor_without_signal(),
        )
        coordinator.get_lte()
        data = coordinator.ds["lte"]["lte1"]

        assert data["sinr"] == "0"

    def test_real_signal_values_pass_through(self):
        """A registered link with real readings keeps its values untouched."""
        monitor = [
            {
                "registration-status": "registered",
                "earfcn": "1700 (band 3, bandwidth 20Mhz)",
                "rsrp": "-104",
                "rsrq": "-9.5",
                "sinr": "6",
            }
        ]
        coordinator = make_lte_coordinator(
            iface_source=SAMPLE_IFACE,
            monitor_source=monitor,
        )
        coordinator.get_lte()
        data = coordinator.ds["lte"]["lte1"]

        assert data["rsrp"] == "-104"
        assert data["rsrq"] == "-9.5"
        # rssi was absent -> derived to a negative int, not nulled.
        assert isinstance(data["rssi"], int)
        assert data["rssi"] < 0


# ---------------------------------------------------------------------------
# F3: scan-interval option must be clamped so it can never be 0
# ---------------------------------------------------------------------------


def _coordinator_with_options(options):
    coordinator = object.__new__(MikrotikCoordinator)
    coordinator.config_entry = SimpleNamespace(options=options)
    return coordinator


class TestScanIntervalClamp:
    """option_scan_interval must never yield a 0-second (divisor) interval."""

    def test_zero_is_clamped_to_at_least_one_second(self):
        coordinator = _coordinator_with_options({"scan_interval": 0})
        assert coordinator.option_scan_interval.seconds >= 1

    def test_normal_value_passes_through(self):
        coordinator = _coordinator_with_options({"scan_interval": 5})
        assert coordinator.option_scan_interval.seconds == 5

    def test_missing_option_uses_default(self):
        coordinator = _coordinator_with_options({})
        assert coordinator.option_scan_interval.seconds == DEFAULT_SCAN_INTERVAL

    def test_non_numeric_falls_back_to_default(self):
        coordinator = _coordinator_with_options({"scan_interval": "oops"})
        assert coordinator.option_scan_interval.seconds == DEFAULT_SCAN_INTERVAL
