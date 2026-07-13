param(
    [switch]$SkipInstall
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Invoke-LoggedNativeCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Label,
        [Parameter(Mandatory = $true)]
        [scriptblock]$Command,
        [Parameter(Mandatory = $true)]
        [string]$LogPath,
        [switch]$Append
    )

    "===== $Label =====" | Out-File -FilePath $LogPath -Encoding utf8 -Append:$Append
    $PreviousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        if ($Append) {
            & $Command *>> $LogPath
        } else {
            & $Command *>> $LogPath
        }
        $ExitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $PreviousErrorActionPreference
    }

    if ($ExitCode -ne 0) {
        Write-Host ""
        Write-Host "Last build log lines:"
        Get-Content -Path $LogPath -Tail 120
        throw "$Label failed with exit code $ExitCode."
    }
}

Push-Location $PSScriptRoot
try {
    if (-not $SkipInstall) {
        python -m pip install --upgrade pip
        if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed." }

        python -m pip install -r requirements-build.txt
        if ($LASTEXITCODE -ne 0) { throw "Build dependency installation failed." }
    }

    $BuildLog = Join-Path $PSScriptRoot "windows-build.log"
    if (Test-Path $BuildLog) {
        Remove-Item -Force $BuildLog
    }

    Invoke-LoggedNativeCommand `
        -Label "Windows resource generation" `
        -Command { python build_tools/generate_windows_resources.py } `
        -LogPath $BuildLog

    Invoke-LoggedNativeCommand `
        -Label "PyInstaller" `
        -Command { python -m PyInstaller --noconfirm --clean ELM327_Engine_Diagnosis_Helper.spec } `
        -LogPath $BuildLog `
        -Append

    Get-Content -Path $BuildLog -Tail 30

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
    Write-Host "  settings.json will be created next to the executable at first start."
}
finally {
    Pop-Location
}
