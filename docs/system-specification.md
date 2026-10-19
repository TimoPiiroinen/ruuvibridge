# System specification

## Purpose and runtime

RuuviTag RAWv2 advertisements are received by the Windows user's own BLE
adapter and displayed locally, stored in SQLite, and forwarded over MQTT to
Home Assistant. Windows 11, Python 3.11+, Bluetooth LE; tested with Python
3.14. No GATT connection or pairing is used.

The app is a per-user background process with a system tray icon, not a
Session 0 Windows service. It does not reserve the adapter exclusively.
An optional HKCU Run entry starts the installed `pythonw.exe` and `run.py`
on login. The Windows app is copied out of WSL into LocalAppData so a Windows
login does not need a running WSL distribution for this app to start.

## Components and ownership

| Path | Responsibility |
| --- | --- |
| `run.py`, `ruuvi_bridge/app.py` | CLI, rotating logs, lifecycle, local listener, tray |
| `decoder.py` | Pure RAWv2 decoder, byte order and unavailable sentinels |
| `bridge.py` | BLE asyncio worker, current readings, freshness, tag selection |
| `mqtt.py` | Paho worker, discovery, reconnects, availability and delivery throttling |
| `storage.py` | Validated settings, atomic JSON replacement, SQLite history |
| `windows.py` | Numeric tray image, menu, HKCU startup |
| `server.py` | Loopback-only HTTP API and fixed static assets |
| `static/` | English/Finnish HTML/CSS/JavaScript UI, canvas plots, dialogs and polling |
| `i18n.py`, `static/i18n.json` | Shared translation catalog for browser, API messages and tray |
| `scripts/` | Windows installation and independent BLE diagnostic |
| `tests/` | Unit/API tests, isolated real MQTT test, Playwright UI checks |

The process owns one `Store`, one `Bridge`, one HTTP listener and one Paho
client. SQLite access and settings writes use a reentrant lock. BLE runs an
asyncio event loop in its own thread (Windows MTA); GUI COM imports do not
run in that thread. Paho owns its own network thread. The tray is the Windows
main loop. HTTP uses short-lived request threads. MQTT settings changes and
reading processing serialize through a settings lock; Paho thread joins do
not hold its callback lock.

## Data flow

1. Ignore advertisements without Ruuvi's company ID `0x0499`.
2. Decode exactly 24 bytes beginning with `5`; prefer the embedded MAC as
   identity, fall back to BLE address only when the embedded MAC is unavailable.
3. Keep latest readings in memory; only explicitly selected tags proceed to
   storage and MQTT.
4. Store one sample per tag per 30 seconds, and forward state at most once per
   10 seconds. Do not deduplicate solely by the sequence counter: timestamps
   and availability must continue refreshing when repeated packets arrive.
5. The UI polls every 5 seconds. Measurements older than 180 seconds become
   stale. The tray becomes grey and Home Assistant availability goes offline.
6. History API aggregates long windows into at most about 1,440 buckets using
   means. UI statistics are over the plotted buckets. CSV exports those same
   buckets with Unix timestamps in seconds, C, %, hPa, V and dBm.
7. Sample retention is 30 days, cleaned hourly during ingestion.

The MQTT namespace is `ruuvi_bridge/<persisted-instance-id>/<tag-mac>/`.
Discovery config topics are
`homeassistant/sensor/ruuvi_<instance-id>_<tag-mac>/<measurement>/config`.
Five sensors share the `ruuvi_<tag-mac>` device identifier. Discovery is retained,
measurement state is not retained, and device availability is retained. Bridge
availability uses a retained Last Will plus a clean-shutdown offline message.
All entity availability requires both the bridge and tag to be online; an
additional 180-second `expire_after` covers tag silence. Initial reconnect
marks tags offline until a new packet is received. MQTT reconnects and Home
Assistant's `homeassistant/status=online` birth message trigger rediscovery.
Disabling a tag removes its retained discovery messages when connected; the
same cleanup is repeated on reconnect for disabled tags.

## User interface and shell

No frontend framework, cloud hosting, external font, DNS, analytics or account.
Loopback HTTP defaults to `http://127.0.0.1:8765`. Responsive desktop and narrow
layouts support modern Edge/Chrome/Firefox. English is the default and Finnish
can be selected in Settings. The validated `language` setting persists across
restarts; existing installations without this setting also default to English.
The browser translates labels, status and error messages, chart summaries and
accessible names, using the selected locale for numbers and dates. The Windows
tray menu and tooltip follow the same setting. User-entered sensor names and
existing Home Assistant entity names are preserved. Humidity,
temperature and pressure each have a permanently visible chart, sharing sensor
and time range controls. Visible values and summaries use one decimal; stored
and MQTT values preserve sensor precision. A native
Windows icon shows rounded humidity or temperature and a tooltip with both.
It may be hidden in the Windows tray overflow until the user moves it.
No unsupported Windows taskbar toolbar or Explorer patch is installed.

The tray menu has humidity and temperature radio choices, using the same
validated, persisted setting as the browser UI. Fresh installations default to
humidity; startup on login is disabled by default.
The tray icon uses an integer reading; its tooltip shows one decimal. Clicking
the icon opens measurements and history in the default browser. The app sends
no Windows notifications and installs no notification registration.

## Security and persistence

HTTP binds IPv4 loopback only. Host checking blocks DNS rebinding; mutation
requests require a random per-process token and reject foreign Origin values.
No permissive CORS is provided. Static assets use a restrictive CSP. Tag names
are inserted using textContent, not HTML. No arbitrary file
paths or shell commands are accepted by the UI. Token protection is for web
origins; processes running as the same local user are trusted.

Broker credentials stay in LocalAppData settings, never in HTTP responses or
repo files. The file relies on Windows profile permissions; passwords are not
encrypted at rest. TLS optionally uses the OS/Python certificate trust store.
Broker authentication, firewall rules, and network exposure are managed by the
operator; this project does not change them.

Runtime data path: `%LOCALAPPDATA%\RuuviBridge\data`.
Installed source: `%LOCALAPPDATA%\RuuviBridge\app`.
Dedicated interpreter: `%LOCALAPPDATA%\RuuviBridge\.venv`.
Stop before backing up the whole data directory (including SQLite WAL files
if present). The original transparent mascot PNG was created for this project
with the built-in image generation tool. Its exact prompt is in
`docs/logo-prompt.txt`; web PNG and multi-resolution Windows ICO exports are in
`static/assets/` and are rebuilt with `scripts/build-icons.py`. The header,
browser favicon, Start menu shortcut and initial tray icon use the mascot.
The live tray measurement remains an integer drawn with the installed system
font. No external asset licensing dependency was introduced. Python and npm
dependencies retain their upstream licenses.

README screenshots in `docs/screenshots/` are captured from a fresh isolated
English demo with a synthetic sensor and empty MQTT credentials. They contain
only browser content, not the user's desktop. Review both visible content and
PNG metadata before publishing replacements; normal test captures stay ignored.

## Build, deployment and maintenance

There is no frontend build step. `Install.cmd` invokes
`scripts/install-windows.ps1`, creates/updates the dedicated venv, copies the
source package, creates a Start menu shortcut and launches the app. The script
also supports `-NoLaunch`. Dependencies are declared in `requirements.txt`;
Node dependencies and lockfile are for Playwright tests and Prettier formatting.

Before uninstalling, disable automatic startup in settings and exit using
the tray menu. The LocalAppData app/venv can then be removed while preserving
the data directory if history is wanted. Delete the Start menu shortcut if
completely removing it.

Known limits: only RAWv2 tags; no historical download from tag memory; no
measurements during PC sleep; no remote UI access; no MQTT offline replay;
30-day history and bounded chart aggregation.
