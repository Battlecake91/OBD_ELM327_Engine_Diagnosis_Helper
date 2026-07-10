# ELM327 Live Diagnostic 3.0

A professional cross-platform PySide6 application for standard OBD-II live data through a serial ELM327 adapter.

The application is intended for diagnostic measurements, repeatable RPM tests and later analysis of recorded data. It does not control the engine or throttle.

## Highlights

- Live dashboard for selected OBD-II PIDs
- Dedicated Settings page for serial connection and PID configuration
- PID presets for lean, balanced and full measurements
- Plot acquisition starts only when the user presses **Start**
- Every active plot session is automatically written to a temporary CSV file
- Export the complete session or an explicitly selected time range
- Guided multi-stage tests with target RPM, tolerance and phase countdown
- Export the last test period as a separate CSV file
- Manual time markers stored in plots and CSV files
- Open and plot recordings created by version 2 or version 3
- Generic DTC reading and clearing
- Raw Mode 06 access and custom ELM/OBD commands
- Optional Linux Bluetooth RFCOMM helper
- Application icon and GNOME desktop integration

## Screens and workflow

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

Available multi-stage presets include:

- RPM step test: 10 s idle, 20 s at 1500 rpm, 20 s idle, 20 s at 2500 rpm, 20 s idle
- Extended fuel-trim test
- Electrical load test
- Oxygen-sensor response test

During an RPM stage, the countdown advances only while the measured speed is inside the configured tolerance. After completion or an intentional abort, the captured test interval can be exported with **Export last test**.

## PID presets

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

1. Run `setup_windows.bat`.
2. Run `start_windows.bat`.

Pair Bluetooth ELM327 adapters in Windows settings. Select the generated COM port on the application's Settings tab.

## Linux Bluetooth serial helper

The optional helper uses BlueZ tools:

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
elm327_twingo_gui.py
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
