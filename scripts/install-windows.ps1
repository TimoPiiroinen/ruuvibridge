param([switch]$NoLaunch)
$ErrorActionPreference = 'Stop'
$source = Split-Path -Parent $PSScriptRoot
$install = Join-Path $env:LOCALAPPDATA 'RuuviBridge'
$app = Join-Path $install 'app'
$venv = Join-Path $install '.venv'
New-Item -ItemType Directory -Force -Path $app | Out-Null
if (-not (Test-Path (Join-Path $venv 'Scripts\python.exe'))) {
    & py -3 -m venv $venv
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.11 or later is required. Install Python and try again.' }
}
$python = Join-Path $venv 'Scripts\python.exe'
& $python -m pip install -r (Join-Path $source 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
# Stop only this application's authenticated local API before replacing its source.
try {
    $state = Invoke-RestMethod 'http://127.0.0.1:8765/api/state' -TimeoutSec 3
    if ($state.settings.instance_id -and $state.token) {
        Invoke-RestMethod 'http://127.0.0.1:8765/api/shutdown' -Method Post -Headers @{'X-Ruuvi-Token'=$state.token} -ContentType 'application/json' -Body '{}' | Out-Null
        Start-Sleep -Seconds 3
    }
} catch { Write-Host 'No running Ruuvi Bridge to stop.' }
Copy-Item (Join-Path $source 'ruuvi_bridge') $app -Recurse -Force
Copy-Item (Join-Path $source 'run.py') $app -Force
$pythonw = Join-Path $venv 'Scripts\pythonw.exe'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Programs')) 'Ruuvi Bridge.lnk'))
$shortcut.TargetPath = $pythonw
$shortcut.Arguments = '"' + (Join-Path $app 'run.py') + '"'
$shortcut.WorkingDirectory = $app
$shortcut.Description = 'RuuviTag measurements and history'
$shortcut.IconLocation = (Join-Path $app 'ruuvi_bridge\static\assets\ruuvi-bridge.ico') + ',0'
$shortcut.Save()
Write-Host "Installed: $app"
Write-Host 'UI: http://127.0.0.1:8765'
Write-Host 'Start menu: Ruuvi Bridge'
if (-not $NoLaunch) {
    Start-Process -FilePath $pythonw -ArgumentList ('"' + (Join-Path $app 'run.py') + '"') -WorkingDirectory $app
}
