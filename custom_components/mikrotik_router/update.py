"""Support for the Mikrotik Router update service."""

from __future__ import annotations

import asyncio
from logging import getLogger
from time import monotonic
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from homeassistant.components.update import (
    UpdateEntity,
    UpdateDeviceClass,
    UpdateEntityFeature,
)

from .coordinator import MikrotikCoordinator
from .entity import MikrotikEntity, async_add_entities
from .update_types import SENSOR_TYPES, SENSOR_SERVICES  # noqa: F401
from packaging.version import Version

_LOGGER = getLogger(__name__)

# This platform exposes an install action (firmware update); serialise commands
# so concurrent installs can't be issued to the router at once.
PARALLEL_UPDATES = 1
DEVICE_UPDATE = "device_update"

# Safety cap on synthesised changelog fetches. A wide installed→latest gap would
# otherwise enumerate hundreds of (mostly non-existent) patch versions and fire
# them all at the MikroTik CDN at once.
MAX_CHANGELOG_VERSIONS = 60

# An install downloads the package (slow on LTE backhaul) and reboots the
# router; keep async_install running until the device comes back on the target
# version so HA's in-progress state reflects the whole upgrade, not just the
# API call.
INSTALL_TIMEOUT = 900
INSTALL_POLL_INTERVAL = 20


class MikrotikInstallWaitMixin:
    """Shared post-install completion handling for MikroTik update entities."""

    async def _async_finish_install(self, target: str, command_ok: bool, what: str) -> None:
        """Wait through download+reboot until the router reports the target version.

        A False from execute() with the API connection gone is expected — the
        install/reboot kills the session — and must not be reported as failure.
        """
        if not command_ok:
            if self.coordinator.api.connected():
                raise HomeAssistantError(f"MikroTik {what} command failed")
            _LOGGER.info(
                "MikroTik %s: API connection dropped during install — router is likely rebooting",
                what,
            )

        deadline = monotonic() + INSTALL_TIMEOUT
        while monotonic() < deadline:
            await asyncio.sleep(INSTALL_POLL_INTERVAL)
            await self.coordinator.async_request_refresh()
            if self.installed_version == target:
                _LOGGER.info("MikroTik %s completed: now on %s", what, target)
                return

        raise HomeAssistantError(
            f"MikroTik {what}: router did not report version {target} "
            f"within {INSTALL_TIMEOUT}s — check the device manually"
        )


# ---------------------------
#   async_setup_entry
# ---------------------------
async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    _async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up entry for component"""
    dispatcher = {
        "MikrotikRouterOSUpdate": MikrotikRouterOSUpdate,
        "MikrotikRouterBoardFWUpdate": MikrotikRouterBoardFWUpdate,
    }
    await async_add_entities(hass, config_entry, dispatcher)


# ---------------------------
#   MikrotikRouterOSUpdate
# ---------------------------
class MikrotikRouterOSUpdate(MikrotikEntity, UpdateEntity, MikrotikInstallWaitMixin):
    """Define an Mikrotik Controller Update entity."""

    def __init__(
        self,
        coordinator: MikrotikCoordinator,
        entity_description,
        uid: str | None = None,
    ):
        """Set up device update entity."""
        super().__init__(coordinator, entity_description, uid)

        self._attr_supported_features = UpdateEntityFeature.INSTALL
        self._attr_supported_features |= UpdateEntityFeature.BACKUP
        self._attr_supported_features |= UpdateEntityFeature.RELEASE_NOTES
        self._attr_title = self.entity_description.title

    @property
    def is_on(self) -> bool:
        """Return true if device is on."""
        return self._data[self.entity_description.data_attribute]

    @property
    def installed_version(self) -> str:
        """Version installed and in use."""
        return self._data["installed-version"]

    @property
    def latest_version(self) -> str:
        """Latest version available for install."""
        return self._data["latest-version"]

    async def options_updated(self) -> None:
        """No action needed."""

    async def async_install(self, version: str, backup: bool, **kwargs: Any) -> None:
        """Install an update."""
        if backup:
            backup_ok = await self.hass.async_add_executor_job(self.coordinator.execute, "/system/backup", "save", None, None)
            if not backup_ok:
                # Never proceed into the (rebooting) install when the requested
                # pre-update backup did not succeed.
                raise HomeAssistantError("MikroTik backup before update failed; install aborted")

        target = self.latest_version
        install_ok = await self.hass.async_add_executor_job(self.coordinator.execute, "/system/package/update", "install", None, None)
        await self._async_finish_install(target, bool(install_ok), "RouterOS update install")

    async def async_release_notes(self) -> str:
        """Return the release notes."""
        try:
            session = async_get_clientsession(self.hass)
            """Get concatenated changelogs from installed_version to latest_version in reverse order."""
            versions_to_fetch = generate_version_list(self._data["installed-version"], self._data["latest-version"])

            tasks = [fetch_changelog(session, version) for version in versions_to_fetch]
            changelogs = await asyncio.gather(*tasks)

            # Combine all non-empty changelogs, maintaining reverse order
            combined_changelogs = "\n\n".join(filter(None, changelogs))
            return combined_changelogs.replace("*) ", "- ")

        except Exception as e:
            _LOGGER.warning("Failed to download release notes (%s)", e)

        return "Error fetching release notes."

    @property
    def release_url(self) -> str:
        """URL to the full release notes of the latest version available."""
        return "https://mikrotik.com/download/changelogs"


# ---------------------------
#   MikrotikRouterBoardFWUpdate
# ---------------------------
class MikrotikRouterBoardFWUpdate(MikrotikEntity, UpdateEntity, MikrotikInstallWaitMixin):
    """Define an Mikrotik Controller Update entity."""

    TYPE = DEVICE_UPDATE
    _attr_device_class = UpdateDeviceClass.FIRMWARE

    def __init__(
        self,
        coordinator: MikrotikCoordinator,
        entity_description,
        uid: str | None = None,
    ):
        """Set up device update entity."""
        super().__init__(coordinator, entity_description, uid)

        self._attr_supported_features = UpdateEntityFeature.INSTALL
        self._attr_title = self.entity_description.title

    @property
    def is_on(self) -> bool:
        """Return true if device is on."""
        return self.data["routerboard"]["current-firmware"] != self.data["routerboard"]["upgrade-firmware"]

    @property
    def installed_version(self) -> str:
        """Version installed and in use."""
        return self._data["current-firmware"]

    @property
    def latest_version(self) -> str:
        """Latest version available for install."""
        return self._data["upgrade-firmware"]

    async def options_updated(self) -> None:
        """No action needed."""

    async def async_install(self, version: str, backup: bool, **kwargs: Any) -> None:
        """Install an update."""
        upgrade_ok = await self.hass.async_add_executor_job(self.coordinator.execute, "/system/routerboard", "upgrade", None, None)
        if not upgrade_ok:
            # Don't reboot the router for an upgrade that wasn't staged.
            raise HomeAssistantError("MikroTik RouterBOARD firmware upgrade command failed; not rebooting")
        target = self.latest_version
        reboot_ok = await self.hass.async_add_executor_job(self.coordinator.execute, "/system", "reboot", None, None)
        await self._async_finish_install(target, bool(reboot_ok), "RouterBOARD firmware upgrade")


async def fetch_changelog(session, version: str) -> str:
    """Asynchronously fetch the changelog for a given version."""
    url = f"https://cdn.mikrotik.com/routeros/{version}/CHANGELOG"
    try:
        async with session.get(url) as response:
            if response.status == 200:
                text = await response.text()
                return text.replace("*) ", "- ")
    except Exception:
        _LOGGER.debug("Failed to fetch changelog for version %s", version)
    return ""


def generate_version_list(start_version: str, end_version: str) -> list:
    """Generate a list of version strings from start_version to end_version in reverse order."""
    start = Version(start_version)
    end = Version(end_version)
    versions = []

    current = end
    while current >= start:
        versions.append(str(current))
        if current == start:
            break
        if len(versions) >= MAX_CHANGELOG_VERSIONS:
            # Stop synthesising patch versions once the cap is hit; a gap this wide
            # would otherwise fire hundreds of mostly-404 requests at the CDN.
            break
        current = decrement_version(current, start)

    return versions


def decrement_version(version: Version, start_version: Version) -> Version:
    """Decrement version by the smallest possible step without going below start_version."""
    if version <= start_version:
        return start_version
    if version.micro > 0:
        next_patch = version.micro - 1
        return Version(f"{version.major}.{version.minor}.{next_patch}")
    elif version.minor > 0:
        next_minor = version.minor - 1
        return Version(f"{version.major}.{next_minor}.999")  # Assuming .999 as max patch version
    else:
        next_major = version.major - 1
        return Version(f"{next_major}.999.999")  # Assuming .999 as max minor and patch version
