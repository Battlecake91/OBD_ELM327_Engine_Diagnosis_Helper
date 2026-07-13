param(
    [switch]$SkipInstall
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Push-Location $PSScriptRoot
try {
    if (-not $SkipInstall) {
        python -m pip install --upgrade pip
        if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed." }

        python -m pip install -r requirements-build.txt
        if ($LASTEXITCODE -ne 0) { throw "Build dependency installation failed." }
    }

    python build_tools/generate_windows_resources.py
    if ($LASTEXITCODE -ne 0) { throw "Windows resource generation failed." }

    python -m PyInstaller --noconfirm --clean ELM327_Engine_Diagnosis_Helper.spec
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed." }

    $ExePath = Join-Path $PSScriptRoot "dist\OBD_ELM327_Engine_Diagnosis_Helper.exe"
    if (-not (Test-Path $ExePath)) {
        throw "Expected executable was not created: $ExePath"
    }

    $HashPath = Join-Path $PSScriptRoot "dist\OBD_ELM327_Engine_Diagnosis_Helper.sha256.txt"
    $Hash = (Get-FileHash -Path $ExePath -Algorithm SHA256).Hash.ToLowerInvariant()
    "$Hash  OBD_ELM327_Engine_Diagnosis_Helper.exe" | Set-Content -Path $HashPath -Encoding ascii

    Write-Host ""
    Write-Host "Build completed:"
    Write-Host "  $ExePath"
    Write-Host "  $HashPath"
}
finally {
    Pop-Location
}
