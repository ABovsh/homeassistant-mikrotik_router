"""Unit tests for LTE coordinator logic (earfcn parsing and get_lte field mapping)."""

from __future__ import annotations

from custom_components.mikrotik_router.coordinator import MikrotikCoordinator

from .conftest import MockMikrotikAPI


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_IFACE = [
    {
        ".id": "*3",
        "name": "lte1",
        "mtu": "1480",
        "apn-profiles": "default",
        "allow-roaming": "true",
        "network-mode": "lte",
        "band": "",
        "running": "true",
        "disabled": "false",
    }
]

SAMPLE_MONITOR = [
    {
        "status": "registered",
        "pin-status": "ok",
        "registration-status": "registered",
        "manufacturer": "MikroTik",
        "model": "R11e-LTE",
        "revision": "MikroTik_CP_2.160.000_v021",
        "current-operator": "Vodafone UA",
        "lac": "1882",
        "current-cellid": "110309408",
        "enb-id": "430896",
        "sector-id": "32",
        "phy-cellid": "54",
        "access-technology": "LTE",
        "session-uptime": "3m29s",
        "earfcn": "1700 (band 3, bandwidth 20Mhz)",
        "cqi": "5",
        "rsrp": "-104",
        "rsrq": "-9.5",
        "sinr": "6",
    }
]


def make_lte_coordinator(iface_source=None, monitor_source=None):
    """Build a minimal coordinator for LTE tests."""
    coordinator = object.__new__(MikrotikCoordinator)
    coordinator.ds = {"lte": {}}

    responses = {}
    if iface_source is not None:
        responses["/interface/lte"] = iface_source
    if monitor_source is not None:
        responses[("/interface/lte", "monitor")] = monitor_source

    coordinator.api = MockMikrotikAPI(responses=responses)
    return coordinator


# ---------------------------------------------------------------------------
# Group L1: _parse_earfcn — pure function
# ---------------------------------------------------------------------------


class TestParseEarfcn:
    """Tests for the earfcn string parser."""

    def test_standard_format(self):
        earfcn, band, bw = MikrotikCoordinator._parse_earfcn("1700 (band 3, bandwidth 20Mhz)")
        assert earfcn == 1700
        assert band == "B3"
        assert bw == "20Mhz"

    def test_band_single_digit(self):
        earfcn, band, bw = MikrotikCoordinator._parse_earfcn("6200 (band 1, bandwidth 5Mhz)")
        assert earfcn == 6200
        assert band == "B1"
        assert bw == "5Mhz"

    def test_band_two_digits(self):
        earfcn, band, bw = MikrotikCoordinator._parse_earfcn("2850 (band 20, bandwidth 10Mhz)")
        assert earfcn == 2850
        assert band == "B20"
        assert bw == "10Mhz"

    def test_raw_string_no_parens(self):
        """If the string has no bracket section, return raw and unknowns."""
        raw = "1700"
        earfcn, band, bw = MikrotikCoordinator._parse_earfcn(raw)
        assert earfcn == raw
        assert band == "unknown"
        assert bw == "unknown"

    def test_empty_string_returns_unknowns(self):
        earfcn, band, bw = MikrotikCoordinator._parse_earfcn("")
        assert earfcn == ""
        assert band == "unknown"
        assert bw == "unknown"

    def test_leading_spaces_tolerated(self):
        earfcn, band, bw = MikrotikCoordinator._parse_earfcn("  1700 (band 3, bandwidth 20Mhz)")
        assert earfcn == 1700
        assert band == "B3"
        assert bw == "20Mhz"


class TestDeriveRssi:
    """Tests for the wideband RSSI fallback derivation."""

    def test_20mhz_known_relation(self):
        # RSSI = RSRP - RSRQ + 10*log10(100) = -106 + 9.5 + 20 = -76.5 -> -76 (round half to even)
        assert MikrotikCoordinator._derive_rssi(-106, -9.5, "20Mhz") == -76

    def test_5mhz_smaller_offset(self):
        # 10*log10(25) ~= 13.98 -> RSSI = -100 + 8 + 13.98 ~= -78
        assert MikrotikCoordinator._derive_rssi(-100, -8, "5Mhz") == -78

    def test_unknown_bandwidth_returns_none(self):
        assert MikrotikCoordinator._derive_rssi(-100, -8, "unknown") is None

    def test_zero_rsrp_returns_none(self):
        assert MikrotikCoordinator._derive_rssi(0, -8, "20Mhz") is None

    def test_non_numeric_inputs_return_none(self):
        assert MikrotikCoordinator._derive_rssi("n/a", -8, "20Mhz") is None


# ---------------------------------------------------------------------------
# Group L2: get_lte — field mapping with recorded sample
# ---------------------------------------------------------------------------


class TestGetLte:
    """Tests for get_lte() using fixed sample dicts (no live router)."""

    def test_no_lte_interfaces_leaves_ds_empty(self):
        coordinator = make_lte_coordinator(iface_source=[])
        coordinator.get_lte()
        assert coordinator.ds["lte"] == {}

    def test_full_sample_parsed_correctly(self):
        coordinator = make_lte_coordinator(
            iface_source=SAMPLE_IFACE,
            monitor_source=SAMPLE_MONITOR,
        )
        coordinator.get_lte()

        assert "lte1" in coordinator.ds["lte"]
        data = coordinator.ds["lte"]["lte1"]

        # Interface fields (parse_api returns strings for non-bool fields)
        assert data["name"] == "lte1"
        assert data["mtu"] == "1480"
        # "true"/"false" strings are not in apiparser's TRUTHY/FALSY sets;
        # real RouterOS API returns Python bools, mock returns strings.
        assert data["allow-roaming"] is False
        assert data["network-mode"] == "lte"

        # Monitor fields
        assert data["registration-status"] == "registered"
        assert data["current-operator"] == "Vodafone UA"
        assert data["access-technology"] == "LTE"
        assert data["session-uptime"] == "3m29s"
        assert data["cqi"] == "5"
        assert data["rsrp"] == "-104"
        assert data["sinr"] == "6"
        assert data["model"] == "R11e-LTE"

        # Derived earfcn fields
        assert data["earfcn"] == 1700
        assert data["lte-band"] == "B3"
        assert data["lte-bandwidth"] == "20Mhz"

    def test_missing_rssi_is_derived(self):
        """When the modem omits rssi, it is derived from rsrp/rsrq/bandwidth."""
        monitor_no_rssi = [row for row in SAMPLE_MONITOR]
        # rssi is absent from SAMPLE_MONITOR — verify it is computed, not left 0
        coordinator = make_lte_coordinator(
            iface_source=SAMPLE_IFACE,
            monitor_source=monitor_no_rssi,
        )
        coordinator.get_lte()
        data = coordinator.ds["lte"]["lte1"]
        assert isinstance(data.get("rssi"), int)
        assert data["rssi"] < 0

    def test_missing_ca_band_defaults_to_unknown(self):
        coordinator = make_lte_coordinator(
            iface_source=SAMPLE_IFACE,
            monitor_source=SAMPLE_MONITOR,
        )
        coordinator.get_lte()
        data = coordinator.ds["lte"]["lte1"]
        assert data.get("ca-band") == "unknown"

    def test_no_monitor_response_does_not_crash(self):
        """If monitor query returns [], lte entry is still keyed by iface name."""
        responses = {
            "/interface/lte": SAMPLE_IFACE,
            ("/interface/lte", "monitor"): [],
        }
        coordinator = object.__new__(MikrotikCoordinator)
        coordinator.ds = {"lte": {}}
        coordinator.api = MockMikrotikAPI(responses=responses)
        coordinator.get_lte()
        # Interface still registered; derived fields set to unknown
        assert "lte1" in coordinator.ds["lte"]
        data = coordinator.ds["lte"]["lte1"]
        assert data.get("lte-band") == "unknown"
        assert data.get("lte-bandwidth") == "unknown"

    def test_earfcn_string_without_band_stored_raw(self):
        monitor_raw_earfcn = [
            {
                **SAMPLE_MONITOR[0],
                "earfcn": "1700",
            }
        ]
        coordinator = make_lte_coordinator(
            iface_source=SAMPLE_IFACE,
            monitor_source=monitor_raw_earfcn,
        )
        coordinator.get_lte()
        data = coordinator.ds["lte"]["lte1"]
        assert data["earfcn"] == "1700"
        assert data["lte-band"] == "unknown"
        assert data["lte-bandwidth"] == "unknown"

    def test_imei_imsi_iccid_not_exposed(self):
        """Sensitive modem identifiers must never appear in ds['lte']."""
        monitor_with_secrets = [
            {
                **SAMPLE_MONITOR[0],
                "imei": "123456789012345",
                "imsi": "255010000000001",
                "iccid": "8938600000000000000",
            }
        ]
        coordinator = make_lte_coordinator(
            iface_source=SAMPLE_IFACE,
            monitor_source=monitor_with_secrets,
        )
        coordinator.get_lte()
        data = coordinator.ds["lte"]["lte1"]
        assert "imei" not in data
        assert "imsi" not in data
        assert "iccid" not in data


# ---------------------------------------------------------------------------
# Group L3: _detect_lte_support
# ---------------------------------------------------------------------------


class TestDetectLteSupport:
    """Tests for LTE capability detection."""

    def test_lte_interfaces_present_sets_support_true(self):
        coordinator = make_lte_coordinator(iface_source=SAMPLE_IFACE)
        coordinator.support_lte = False
        coordinator._detect_lte_support()
        assert coordinator.support_lte is True

    def test_no_lte_interfaces_leaves_support_false(self):
        coordinator = make_lte_coordinator(iface_source=[])
        coordinator.support_lte = False
        coordinator._detect_lte_support()
        assert coordinator.support_lte is False

    def test_api_returns_none_leaves_support_false(self):
        coordinator = object.__new__(MikrotikCoordinator)
        coordinator.api = MockMikrotikAPI(responses={})
        coordinator.support_lte = False
        coordinator._detect_lte_support()
        assert coordinator.support_lte is False
