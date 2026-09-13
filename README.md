# ELM327 Live Diagnostic 3.2

A cross-platform PySide6 diagnostic application for standard OBD-II and supported manufacturer-specific protocols through a serial ELM327-compatible adapter.

The application is intended for diagnostic measurements, repeatable RPM tests and later analysis of recorded data. It does not control the engine or throttle.

## Highlights

- Easy/Expert mode switch with a guided startup and connection assistant
- Visible automatic interface detection with standard OBD-II and known vehicle profiles
- Verified Opel Astra G X16XEL / Multec-H KWP2000 Fast-Init diagnostics
- Repository-backed bilingual DTC database and JSON vehicle/live-data presets
- Beginner-friendly Easy fault-memory and live-data tabs
- Preset-driven Easy live plots with CSV and PNG export
- Portable GitHub-release self-updater for packaged Windows and Linux builds
- Windows x64 and Linux x86_64 release pipelines
- Live dashboard for selected OBD-II PIDs
- Dedicated Settings page for serial connection and PID configuration
- Persistent, editable PID presets for lean, balanced, full and user-defined measurements
- Plot acquisition starts only when the user presses **Start**
- Every active plot session is automatically written to a temporary CSV file
- Export the complete session or an explicitly selected time range
- Persistent, editable multi-stage tests with target RPM, tolerance, phase countdown and an optional PID preset
- Export the last test period as a separate CSV file
- Manual time markers stored in plots and CSV files
- Open and plot recordings created by version 2 or version 3
- Generic DTC reading and clearing
- Raw Mode 06 access and custom ELM/OBD commands
- Optional Linux Bluetooth RFCOMM helper with paired-device discovery and a persistent adapter list
- Application icon and GNOME desktop integration

## Screens and workflow

### Easy and Expert modes

At startup the application asks whether to open the guided Easy workflow or the complete Expert interface. A compact **Easy | Expert** switch remains visible at the top of the main window.

Easy mode intentionally exposes only:

- **Fault memory**: connect, read DTCs, show localized meanings and clear the fault memory after confirmation.
- **Live data**: select a vehicle-specific measurement preset, view current values and individual plots, record a CSV session and export a PNG image.

The guided connection wizard explains Bluetooth ELM327 setup and can either use a selected JSON vehicle profile or try supported interfaces automatically while showing every attempted protocol.

German implementation details and the profile format are documented in [docs/EASY_MODE.md](docs/EASY_MODE.md).

### Dashboard

The Dashboard shows only the measurements enabled on the Settings page. Live values update as soon as the ECU connection is active.

### Plot

Plot history does **not** start automatically. Press **Start** to begin a measurement session.

While a plot session is active:

- all received measurements are added to the plots;
- all received measurements are written to a temporary CSV file;
- pausing freezes only the visual plot refresh;
- acquisition and temporary CSV writing continue during a plot pause;
- markers are included in both the plots and CSV output.

The temporary file is deleted during a normal application shutdown. Export any data that should be retained.

### Range export

The Plot tab provides explicit start and end times in seconds. Use **Use visible range**, adjust the values if required, then select **Export range**. **Export all** writes the complete plot session.

### Test assistant

Test routines and their stages can be created, edited, reordered, saved and deleted. Each routine can optionally select a PID preset before it starts. The selected routine, stage definitions and PID association survive application restarts.

Available built-in multi-stage presets include:

- RPM step test: 10 s idle, 20 s at 1500 rpm, 20 s idle, 20 s at 2500 rpm, 20 s idle
- Extended fuel-trim test
- Electrical load test
- Oxygen-sensor response test

During an RPM stage, the countdown advances only while the measured speed is inside the configured tolerance. After completion or an intentional abort, the captured test interval can be exported with **Export last test**.

## PID presets

PID presets are stored persistently. Selecting a preset applies it immediately. After changing individual PID checkboxes, use **Save / update** to overwrite the selected preset or **New** to create another one. The **Balanced** fallback can be edited but not deleted.

- **Lean diagnostics**: RPM, coolant temperature, STFT, LTFT, MAP, throttle position and oxygen sensor B1S1
- **Balanced**: common diagnostic values enabled by default
- **Full scan**: all implemented standard PIDs
- **Custom**: any manually selected combination

Unsupported PIDs are marked after the ECU reports its support bitmap. They remain visible in Settings but are not polled.

## CSV format

Version 3 writes semicolon-separated UTF-8 CSV files with these columns:

```text
Timestamp;Elapsed_s;Key;Measurement;Value;Unit;Comment
```

Markers use:

```text
Key = __marker__
```

The loader also accepts the German column names used by version 2.

## Linux installation

Tested for Xubuntu/Ubuntu 24.04 with Python 3.

```bash
chmod +x setup_linux.sh start_linux.sh
./setup_linux.sh
./start_linux.sh
```

The setup script creates a local virtual environment and installs a desktop entry plus the application icon for GNOME and other freedesktop-compatible desktops.

Serial-port access normally requires membership in the `dialout` group:

```bash
sudo usermod -aG dialout "$USER"
```

Log out and back in after changing group membership.

## Windows installation

For end users, use the portable Windows release ZIP. It contains the main application and OBD_ELM327_Updater.exe. Keep both files together so the in-app updater can replace a running installation safely. Pair Bluetooth ELM327 adapters in Windows settings and select the generated COM port in the guided assistant or Expert settings.

For source/development installations, setup_windows.bat and start_windows.bat remain available. See [WINDOWS_RELEASE.md](WINDOWS_RELEASE.md) for release details.

## Packaged Linux release

GitHub Actions also produces a portable Linux x86_64 ZIP containing the main binary and updater. See [LINUX_RELEASE.md](LINUX_RELEASE.md).

## Linux Bluetooth serial helper

The optional helper can list paired BlueZ devices, lets the user save named adapters and remembers the selected MAC address, RFCOMM channel and serial device. It uses:

- `bluetoothctl connect <address>`
- `rfcomm bind <device> <address> <channel>`

`rfcomm bind` creates the serial binding; the actual RFCOMM connection is established when the application opens the serial device. Administrative authentication may be requested through `pkexec`.

Install the required tools if they are missing:

```bash
sudo apt install bluez policykit-1
```

The adapter must already be paired and trusted. Channel 1 is common for ELM327 SPP adapters, but some devices use a different channel.

## Safety

- Do not clear DTCs with an unstable vehicle supply voltage.
- Investigate fuel smell or a possible leak before extended engine tests.
- Perform stationary RPM tests only in a ventilated area with the vehicle secured.
- The software only displays a target RPM. The driver remains responsible for throttle control.

## Project files

```text
elm327_app.py                 # version 3.2 application entry point
elm327_twingo_gui.py          # generic diagnostic and plotting core
guided_mode.py                # Easy/Expert UI and guided connection wizard
opel_kwp2000.py               # verified Opel KWP2000 transport integration
opel_multec_profile.py        # X16XEL parsing and live-data decoding
diagnostic_data.py            # JSON vehicle/DTC/locale loader
update_service.py             # GitHub release update service
updater_ui.py                 # in-app updater UI
scripts/portable_updater.py   # standalone replacement/restart process
data/dtc_codes.json
data/vehicles/
locales/
assets/io.github.open-diagnostics.elm327-live-diagnostic.svg
elm327-live-diagnostic.desktop.in
requirements.txt
setup_linux.sh
start_linux.sh
setup_windows.bat
start_windows.bat
README.md
CHANGELOG.md
LICENSE
```

## License

MIT License. See `LICENSE`.
