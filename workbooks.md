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
- `docs/screenshots/`: reviewed English demo captures for the README.
- `ruuvi_bridge/static/i18n.json`: shared English translations of Finnish message keys.
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
existing repository history. Personal runtime data and live screenshots are excluded.

Language and README update: English is now the default; Settings → Language
persists English or Finnish for the UI and tray. Extend the shared catalog when
adding user-facing messages; keep user-entered sensor names unchanged. Run the
UI checks in both languages after changing copy or layout. Tests cover saved
language, upgrade defaults, translated validation/status/tray text, and decimal
formatting as well as desktop/mobile interactions.
Validation passed: eight Python tests on Linux and Windows, native Windows tray
labels/actions in both languages, English/Finnish Playwright checks, Ruff and
Prettier. All three public English PNGs were visually reviewed and contain no
PNG metadata; sensor data is synthetic and credential fields are empty.

For public screenshots, start `run.py --demo --no-open --no-tray --port 8767
--data-dir <fresh-temporary-directory>`, then run the UI checks with
`RUUVI_URL=http://127.0.0.1:8767 npm run test:ui`. Use a fresh browser page in
English to capture the full desktop and mobile views plus the settings dialog.
Verify demo mode, the synthetic sensor address `020000000001`, and empty
credentials before capture. Inspect the PNGs and metadata, then publish only
the three approved files in `docs/screenshots/`. Stop the temporary demo after use.

The icon uses integers; the tooltip and UI use one decimal. Right-click choices
and browser settings share the same persisted metric. Startup on login is
optional and disabled by default. No Windows popup notifications are sent.
UI copy is functional; the footer retains `RuuviTag → Windows → Home Assistant`.

RAWv2 only; the PC must be awake and logged in. Local credentials are plaintext
in the user profile. History is limited to 30 days and long ranges use bucketed
values. Windows may initially hide the tray icon in its overflow menu.
