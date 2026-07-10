# Changelog

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
