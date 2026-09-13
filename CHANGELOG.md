# Changelog

## 3.2.0

- Integrated the verified Opel Astra G X16XEL / Multec-H KWP2000 Fast-Init profile into the normal application architecture.
- Added verified X16XEL ECU identification, live-data decoding, DTC reading and DTC clearing.
- Added a bilingual repository-backed DTC database and JSON vehicle/live-data presets.
- Added an Easy/Expert mode switch inspired by compact slicer-style mode selectors.
- Added a startup choice between the guided assistant and Expert mode.
- Added a guided connection wizard with adapter selection, vehicle/interface profiles and visible automatic protocol detection.
- Added Windows/Linux Bluetooth-ELM327 setup guidance to the wizard.
- Added simplified Easy fault-memory and live-data tabs with preset-driven live plots, CSV export and PNG export.
- Added portable GitHub-release self-update infrastructure based on a separate updater process.
- Added Linux x86_64 PyInstaller builds and release ZIPs alongside Windows releases.
- Bundled diagnostic JSON data and German/English locale files into packaged applications.
- Added a reproducible PyInstaller build for a standalone Windows x64 executable.
- Added embedded Windows icon and version metadata.
- Added automatic GitHub release creation with SHA-256 checksum assets.
- Kept persistent application settings outside the executable through the portable JSON settings backend.

## 3.1.0

- Added persistent, user-editable PID presets.
- Preserved the selected PID preset while individual PIDs are modified so it can be updated without losing the edits.
- Added persistent application, connection, plot-window and test-assistant settings.
- Added Bluetooth device discovery through `bluetoothctl` and a persistent named adapter list.
- Added editable and persistent multi-stage test routines.
- Added an optional PID preset association for every saved test routine.
- Changed the Linux and Windows launchers to use the 3.1 entry point.

## 3.0.0

- Reworked the complete interface in English.
- Added a dedicated Dashboard and Settings page.
- Moved serial-port, baud-rate, protocol and polling configuration to Settings.
- Added persistent PID selection and lean, balanced and full PID presets.
- Prevented plot acquisition from starting automatically.
- Made temporary CSV recording mandatory for every active plot session.
- Added explicit range and full-session CSV exports.
- Added separate export of the most recent guided test interval.
- Added an RPM step test with idle, 1500 rpm and 2500 rpm phases.
- Added icon-based Start, Pause and Reset plot controls.
- Added an application icon and Linux desktop integration.
- Added an optional Linux Bluetooth RFCOMM serial helper.
- Preserved compatibility with version 2 CSV recordings.

## 2.0.0

- Buffered CSV writer thread.
- Plot timing based on received samples.
- Markers and guided target-RPM tests.
- CSV loading and plotting.
