# Ruuvi Bridge workbook

## Purpose and files

Windows RuuviTag BLE receiver with local history, browser UI, MQTT discovery,
and a numeric notification area icon. See [README.md](README.md) for installation
and [the system specification](docs/system-specification.md) for architecture.

- `ruuvi_bridge/`: runtime Python package and static UI.
- `scripts/install-windows.ps1`: installation and update, invoked by `Install.cmd`.
- `Start.cmd`: launch the installed app.
- `tests/`: decoder/storage/API/tray, MQTT integration, and Playwright checks.
- `ruuvi_bridge/static/assets/`: generated mascot, web PNG, and Windows ICO.
- `docs/logo-prompt.txt`: original mascot generation prompt.
- Installed source: `%LOCALAPPDATA%\RuuviBridge\app`.
- Private state: `%LOCALAPPDATA%\RuuviBridge\data`.
- Local UI: <http://127.0.0.1:8765>.

No cloud hosting, frontend build, DNS, account, or API key is required. MQTT
defaults to `127.0.0.1:1883`; configure optional credentials and TLS in the UI.
Do not put runtime configuration or captured device data in this repository.

## Edit and release workflow

1. Edit source and update operational documentation when behavior changes.
2. Run the Python tests and Ruff checks listed in the README.
3. For UI changes, start the isolated demo on port 8766 and run `npm run test:ui`.
   Inspect desktop and mobile screenshots in ignored `artifacts/`.
4. For MQTT changes, use the disposable test broker and integration script.
5. Run `Install.cmd` on Windows to update the independent installed copy.
   Check Bluetooth reception, tray controls, and Home Assistant on the target PC.
6. Before publishing, review staged files for credentials, local paths, sensor
   identifiers, captured measurements, and screenshots. Use synthetic demo data.

There is no build output directory: installation copies the source package.
Rebuild logo exports with `python scripts/build-icons.py` only when the source
mascot changes. The original was generated with the built-in image generation
tool; its background is transparent.

## Validation coverage

- Official public Ruuvi vectors, invalid and missing values.
- Atomic settings validation, credential redaction, selection before recording,
  history throttle/retention, restart persistence, and stale readings.
- Loopback Host/Origin/token checks, history API, and authenticated shutdown.
- Tray temperature/humidity radio actions, shared browser settings, and persistence.
- Real isolated MQTT discovery/state, HA birth, stale availability, reconnect,
  configuration removal, and shutdown.
- Finnish labels, dialogs, settings persistence, three simultaneous charts,
  shared range, one decimal, CSV, desktop and mobile layout in Playwright.

## Behavior and limits

Release validation (2026-10-19): seven unit/API/tray tests passed on Linux and
Windows; native Windows menu construction and radio actions passed; isolated
MQTT integration and desktop/mobile Playwright checks passed. Ruff and Prettier
checks passed. Gitleaks found no secrets in the staged release export or the
existing repository history. Personal runtime data and screenshots are excluded.

The icon uses integers; the tooltip and UI use one decimal. Right-click choices
and browser settings share the same persisted metric. Startup on login is
optional and disabled by default. No Windows popup notifications are sent.
UI copy is functional; the footer retains `RuuviTag → Windows → Home Assistant`.

RAWv2 only; the PC must be awake and logged in. Local credentials are plaintext
in the user profile. History is limited to 30 days and long ranges use bucketed
values. Windows may initially hide the tray icon in its overflow menu.
