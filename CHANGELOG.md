# Changelog

All notable changes to this fork are documented here. This fork adds LTE
signal/band sensors and an LTE-only mode switch on top of the upstream
`jnctech/homeassistant-mikrotik_router` integration.

## 2.4.9

### Improvements

- Default scan interval raised from 30s to 60s to reduce Home Assistant database write load.

## 2.4.8

### 🐛 Fixed
- Routers **without** an LTE modem are no longer at risk of being marked
  *Unavailable* by the LTE capability check on RouterOS builds that don't expose
  the LTE menu.
- LTE signal sensors now read *Unknown* (instead of a misleading value) in more
  cases where the modem reports no real signal — a literal `0`, or quality
  metrics omitted while the modem is searching/unregistered.
- LTE sensors no longer error out when the modem returns an interface but no
  monitor data (searching/unregistered); they read *Unknown* until it registers.
- **Firmware update** now stops and reports an error if the pre-update backup,
  the RouterOS install, or the RouterBOARD upgrade command fails — instead of
  silently continuing (or rebooting) and reporting success.
- **Release notes** no longer try to download hundreds of non-existent changelog
  pages when the installed and latest RouterOS versions are far apart.
- Router uptime is read correctly right after a reboot when RouterOS briefly
  reports it in milliseconds.
- The integration now reconnects reliably even if the host clock jumps backwards
  (e.g. an NTP correction after boot).

### 🔒 Privacy
- The router's address is now redacted from downloadable diagnostics.

### 🔧 Changed
- RouterOS API sessions are now closed when the integration is reloaded or
  removed, and after the connection test during setup/reauth — preventing slow
  session build-up on routers with a low API session limit.
- A custom **Update interval** that is out of range (from an imported or
  hand-edited configuration) is clamped to the supported 1–3600 s.

## 2.4.7

### 🐛 Fixed
- LTE **RSRP**, **RSRQ** and **RSSI** now read *Unknown* instead of a misleading
  `0` when the modem stops reporting them (e.g. on a dropped or unregistered
  link). History graphs and signal-quality dashboards no longer show a fake
  full-strength reading while the link is actually down.
- The update interval can no longer be set to `0` seconds, which previously
  could make the integration stop refreshing.

### 🔧 Changed
- The **Update interval (seconds)** option is now a proper number field
  (1–3600 s) in the integration Options, so the refresh rate can be changed from
  the UI without hand-editing Home Assistant configuration files.

## 2.4.6

### 🐛 Fixed
- The integration now recovers on its own after the router drops the API
  connection. Previously every LTE/router entity could stay *Unavailable* until
  the integration was reloaded or Home Assistant restarted.

## 2.4.5

### 🐛 Fixed
- Closed the router API session on disconnect so reconnects no longer leak
  sessions, which on a flaky link eventually caused repeated
  *Connection reset by peer* errors.

## 2.4.4

### 🐛 Fixed
- Updated an internal import to the current Home Assistant location so device
  tracker entities keep working on newer Home Assistant releases.

## 2.4.1

### ✨ Added
- LTE signal sensors: RSRP, RSRQ, SINR, RSSI, CQI, plus registration status,
  access technology, operator, band, bandwidth and session uptime —
  auto-discovered for every LTE interface.
- RSSI is derived from RSRP/RSRQ/bandwidth when the modem omits it (e.g. R11e-LTE).
- An **LTE only** switch to lock an interface to LTE (vs. gsm/3g/lte).
- Modem identifiers (IMEI/IMSI/ICCID) are redacted from diagnostics.
