# Standalone Windows release

The Windows release is a single 64-bit executable:

```text
OBD_ELM327_Engine_Diagnosis_Helper.exe
```

It bundles Python, PySide6/Qt, pyserial, pyqtgraph, NumPy and the application assets. Python and the packages from `requirements.txt` are not required on the target computer.

Windows still needs the normal serial or Bluetooth driver that exposes the ELM327 as a COM port. Hardware drivers cannot sensibly be embedded in the application executable because apparently even dependency-free software must still communicate with reality somehow.

## Persistent settings

Application settings are intentionally stored outside the executable through Qt's native settings backend. On Windows they are stored for the current user below:

```text
HKEY_CURRENT_USER\Software\Open Diagnostics\ELM327 Live Diagnostic
```

This includes connection settings, PID presets, test routines, Bluetooth adapter entries and interface state.

## Creating a GitHub release

1. Open **Actions** in the repository.
2. Select **Windows executable and release**.
3. Select **Run workflow**.
4. Enter a tag such as `v3.1.0`.
5. Run the workflow.

The workflow:

- installs the pinned build environment on a Windows x64 runner;
- runs the automated tests;
- builds one executable with PyInstaller;
- embeds the program icon and Windows version metadata;
- generates a SHA-256 checksum;
- creates or updates the matching GitHub release;
- uploads the executable and checksum as release assets.

Pushing a tag beginning with `v` performs the same release build automatically.

## Building locally

Python is needed only on the Windows build computer:

```powershell
powershell -ExecutionPolicy Bypass -File .\build_windows.ps1
```

The output is written to:

```text
dist\OBD_ELM327_Engine_Diagnosis_Helper.exe
dist\OBD_ELM327_Engine_Diagnosis_Helper.sha256.txt
```

Use `-SkipInstall` when the build dependencies have already been installed:

```powershell
.\build_windows.ps1 -SkipInstall
```

## SmartScreen and code signing

The executable is not digitally signed. Windows SmartScreen may therefore show an unknown-publisher warning even when the SHA-256 checksum matches the published checksum. Removing that warning reliably requires an Authenticode code-signing certificate and signing step; merely renaming the file or glaring at Windows will not accomplish it.
