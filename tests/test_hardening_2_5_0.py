"""Recorder-churn hardening.

Home Assistant writes a history row when the state OR ANY ATTRIBUTE changes.
This integration copies raw router telemetry into `extra_state_attributes` on
entities whose own state almost never moves — a device_tracker that says
"home", a UPS binary_sensor that says "online" — so a value that ticks on every
poll forces a database row per poll, per entity, forever.

The same defect class cost a sibling router integration 40,000 rows a day.
The fix lives in `copy_attrs`, the shared call site every entity type routes
through, rather than in each entity.
"""

from __future__ import annotations

import pytest

from custom_components.mikrotik_router.entity import copy_attrs, publishable_value


class TestPublishableValue:
    """The deadband itself."""

    def test_first_reading_always_publishes(self) -> None:
        assert publishable_value("signal-strength", -60, None) == -60

    def test_small_move_is_held_at_the_previous_value(self) -> None:
        # Wi-Fi RSSI wanders a couple of dB continuously while a laptop sits
        # still on a desk. Nobody automates on 1 dB.
        assert publishable_value("signal-strength", -62, -60) == -60

    def test_real_move_gets_through(self) -> None:
        assert publishable_value("signal-strength", -75, -60) == -75

    def test_rates_use_a_relative_band(self) -> None:
        # Link rates span three orders of magnitude, so a fixed step cannot
        # serve both a 1 Mbps and a 1 Gbps link.
        assert publishable_value("tx-rate", 144_500_000, 144_000_000) == 144_000_000
        assert publishable_value("tx-rate", 300_000_000, 144_000_000) == 300_000_000

    def test_zero_always_publishes(self) -> None:
        """A link going quiet is information, not noise."""
        assert publishable_value("tx-rate", 0, 144_000_000) == 0

    @pytest.mark.parametrize("value", ["54Mbps", None, "unknown", True])
    def test_non_numeric_values_pass_straight_through(self, value) -> None:
        """A deadband must never mangle or drop a value it cannot compare."""
        assert publishable_value("tx-rate", value, 100) == value

    def test_unregistered_attributes_are_untouched(self) -> None:
        """Only attributes known to churn are damped; nothing else changes."""
        assert publishable_value("comment", 5, 4) == 5


class TestCopyAttrs:
    """The shared call site, which is where the fix has to live."""

    def test_deadband_state_holds_a_dithering_attribute_steady(self) -> None:
        state: dict = {}
        attributes: dict = {}

        copy_attrs(
            attributes,
            {"signal-strength": -60},
            ["signal-strength"],
            deadband_state=state,
        )
        first = attributes["signal_strength"]

        # Three more polls of ordinary RSSI wander must not change the value,
        # because each changed value is a database row.
        for reading in (-61, -59, -62):
            attributes = {}
            copy_attrs(
                attributes,
                {"signal-strength": reading},
                ["signal-strength"],
                deadband_state=state,
            )
            assert attributes["signal_strength"] == first

        attributes = {}
        copy_attrs(
            attributes,
            {"signal-strength": -80},
            ["signal-strength"],
            deadband_state=state,
        )
        assert attributes["signal_strength"] == -80

    def test_without_deadband_state_behaviour_is_unchanged(self) -> None:
        """Callers that pass no state must behave exactly as before."""
        attributes: dict = {}
        copy_attrs(attributes, {"signal-strength": -60}, ["signal-strength"])
        assert attributes["signal_strength"] == -60

    def test_skip_junk_still_works_alongside_the_deadband(self) -> None:
        attributes: dict = {}
        copy_attrs(
            attributes,
            {"signal-strength": None},
            ["signal-strength"],
            skip_junk=True,
            deadband_state={},
        )
        assert "signal_strength" not in attributes


class TestVolatileAttributesRemoved:
    """Countdowns cannot be damped — they carry no steady value to hold."""

    def test_dhcp_lease_countdown_is_not_an_attribute(self) -> None:
        """`expires-after` decrements on every poll by construction.

        The sensor's own state is the IP address, which changes only on lease
        renewal, so this attribute alone forced a row per poll.
        """
        from custom_components.mikrotik_router.sensor_types import (
            DEVICE_ATTRIBUTES_DHCP_CLIENT,
        )

        assert "expires-after" not in DEVICE_ATTRIBUTES_DHCP_CLIENT
        # The stable lease context stays.
        assert "address" in DEVICE_ATTRIBUTES_DHCP_CLIENT
        assert "dhcp-server" in DEVICE_ATTRIBUTES_DHCP_CLIENT

    def test_ups_runtime_countdown_is_not_an_attribute(self) -> None:
        from custom_components.mikrotik_router.binary_sensor_types import (
            DEVICE_ATTRIBUTES_UPS,
        )

        assert "runtime-left" not in DEVICE_ATTRIBUTES_UPS
        # The analog readings stay — they are damped, not dropped.
        assert "battery-voltage" in DEVICE_ATTRIBUTES_UPS
        assert "model" in DEVICE_ATTRIBUTES_UPS


class TestChurnyAttributesAreRegistered:
    """Every measured churn source must actually be covered by the map."""

    @pytest.mark.parametrize(
        "attribute",
        [
            "signal-strength",
            "tx-ccq",
            "tx-rate",
            "rx-rate",
            "battery-voltage",
            "line-voltage",
            "battery-charge",
            "load",
            "speed",
            "satellites",
            "horizontal-dilution",
        ],
    )
    def test_attribute_has_a_deadband(self, attribute) -> None:
        from custom_components.mikrotik_router.entity import ATTRIBUTE_DEADBANDS

        assert attribute in ATTRIBUTE_DEADBANDS
