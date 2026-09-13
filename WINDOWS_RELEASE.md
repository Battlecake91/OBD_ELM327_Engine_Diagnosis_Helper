# Standalone Windows release

Version 3.2 ships as a portable Windows x64 release folder/ZIP. The two program files belong together:

~~~text
OBD_ELM327_Engine_Diagnosis_Helper.exe
OBD_ELM327_Updater.exe
~~~

The main executable bundles Python, PySide6/Qt, pyserial, pyqtgraph, NumPy, diagnostic JSON data and locale files. Python is not required on the target computer.

Windows still needs the normal serial or Bluetooth driver that exposes the ELM327 as a COM port.

## Portable JSON settings

Persistent settings are stored in settings.json next to the executable. It contains connection settings, PID presets, test routines, Bluetooth adapter entries and interface state. Application settings are not written to the Windows registry.

The self-updater preserves settings.json, update logs and downloaded update data.

## Self-updater

The application can check the latest GitHub release from **Hilfe / Nach Updates suchen**.

For a packaged installation it:

1. reads the latest GitHub release metadata,
2. selects the Windows x64 ZIP,
3. downloads it to the local updates directory,
4. starts OBD_ELM327_Updater.exe from a temporary copy,
5. closes the main application,
6. replaces program files while preserving local settings,
7. restarts the application.

A source checkout is never overwritten by the self-updater.

## Creating a GitHub release

1. Open **Actions** in the repository.
2. Select **Windows executable and release**.
3. Select **Run workflow** or push a v-prefixed release tag.
4. Use a tag such as v3.2.0.

The workflow runs tests, builds both executables, signs the Windows executables through Microsoft Artifact Signing when the configured release job is used, verifies Authenticode, creates the portable ZIP and SHA-256 checksums, and uploads the release assets.

## Building locally

Python is needed only on the Windows build computer:

~~~powershell
powershell -ExecutionPolicy Bypass -File .\\build_windows.ps1
~~~

The output is written to dist.

## Release assets

~~~text
OBD_ELM327_Engine_Diagnosis_Helper.exe
OBD_ELM327_Updater.exe
OBD_ELM327_Engine_Diagnosis_Helper-windows-x64.zip
OBD_ELM327_Engine_Diagnosis_Helper.sha256.txt
~~~

The ZIP is the preferred end-user download because it keeps the application and updater together.
