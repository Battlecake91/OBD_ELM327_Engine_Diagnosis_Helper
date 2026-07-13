# Standalone Windows release

The Windows release is a single 64-bit executable:

```text
OBD_ELM327_Engine_Diagnosis_Helper.exe
```

It bundles Python, PySide6/Qt, pyserial, pyqtgraph, NumPy and the application assets. Python and the packages from `requirements.txt` are not required on the target computer.

Windows still needs the normal serial or Bluetooth driver that exposes the ELM327 as a COM port.

## Portable JSON settings

The executable stores all persistent settings in:

```text
settings.json
```

The file is created next to the executable at first start. It contains connection settings, PID presets, test routines, Bluetooth adapter entries and interface state. No application settings are written to the Windows registry.

To move the configured application to another computer, copy both files:

```text
OBD_ELM327_Engine_Diagnosis_Helper.exe
settings.json
```

The directory must be writable. Do not place the executable in `C:\Program Files` unless the user has write permission there. A normal folder such as Documents, Downloads or a dedicated tools directory is suitable.

For source installations, the same JSON backend is used in the platform-specific user configuration directory. The location can be overridden on any platform with `ELM327_SETTINGS_PATH`.

## Creating a GitHub release

1. Open **Actions** in the repository.
2. Select **Windows executable and release**.
3. Select **Run workflow**.
4. Enter a tag such as `v3.1.0`.
5. Run the workflow.

The workflow runs tests, builds the one-file executable, performs a startup smoke test, generates a SHA-256 checksum and uploads both files.

## Building locally

Python is needed only on the Windows build computer:

```powershell
powershell -ExecutionPolicy Bypass -File .\build_windows.ps1
```

The output is written to `dist`.

## SmartScreen and code signing

The executable is not digitally signed. Windows SmartScreen may therefore show an unknown-publisher warning. Removing that warning reliably requires an Authenticode code-signing certificate.
