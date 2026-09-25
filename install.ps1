# YaleVPN-PC installer — Windows (PowerShell)
# Copies the client into %LocalAppData%\Programs\YaleVPN and creates a
# `yalevpn.cmd` shim. Requires Python 3.9+ from python.org.
# Run in an elevated PowerShell:  powershell -ExecutionPolicy Bypass -File install.ps1
param(
    [switch]$SkipTools
)

$ErrorActionPreference = "Stop"
$Repo   = Split-Path -Parent $MyInvocation.MyCommand.Path
$Dest   = Join-Path $env:LOCALAPPDATA "Programs\YaleVPN"
$Bin    = Join-Path $env:LOCALAPPDATA "Programs\YaleVPN\yalevpn.cmd"

Write-Host "Installing YaleVPN-PC to $Dest" -ForegroundColor Green
New-Item -ItemType Directory -Force -Path $Dest | Out-Null

# copy package
if (Test-Path (Join-Path $Dest "yalevpn")) { Remove-Item -Recurse -Force (Join-Path $Dest "yalevpn") }
Copy-Item -Recurse (Join-Path $Repo "src\yalevpn") (Join-Path $Dest "yalevpn")

# python resolution
$py = $null
foreach ($cand in @("py", "python", "python3")) {
    $cmd = Get-Command $cand -ErrorAction SilentlyContinue
    if ($cmd) { $py = $cand; break }
}
if (-not $py) {
    Write-Host "error: Python 3.9+ not found. Install from https://www.python.org/downloads/ (tick 'Add to PATH')." -ForegroundColor Red
    exit 1
}

# shim
@"
@echo off
set PYTHONPATH=$Dest
$py -m yalevpn %*
"@ | Set-Content -Encoding Ascii (Join-Path $Dest "yalevpn.cmd")

if (Test-Path "C:\Windows\System32\yalevpn.cmd") { Remove-Item -Force "C:\Windows\System32\yalevpn.cmd" }
Copy-Item (Join-Path $Dest "yalevpn.cmd") "C:\Windows\System32\yalevpn.cmd" -ErrorAction SilentlyContinue

# optional: cryptography (better keygen) + self-contained exe via PyInstaller
if (-not $SkipTools) {
    & $py -m pip install --quiet --upgrade pip
    & $py -m pip install --quiet cryptography
    $pi = & $py -m pip show pyinstaller 2>$null
    if (-not $pi) {
        Write-Host "Installing PyInstaller to build yalevpn.exe …" -ForegroundColor Yellow
        & $py -m pip install --quiet pyinstaller
    }
    & $py -m PyInstaller --onefile --name yalevpn `
        --paths (Join-Path $Dest "yalevpn") `
        --hidden-import yalevpn.cli --hidden-import yalevpn.gui `
        --distpath (Join-Path $Dest "bin") --workpath (Join-Path $env:TEMP "yvbuild") `
        -F (Join-Path $Dest "yalevpn\__main__.py") 2>$null | Out-Null
}

$paths = [Environment]::GetEnvironmentVariable("Path", "Machine")
if ($paths -notlike "*$Dest*") {
    [Environment]::SetEnvironmentVariable("Path", "$paths;$Dest", "Machine")
}

Write-Host ""
Write-Host "Installed. Open a NEW terminal, then:" -ForegroundColor Green
Write-Host "  yalevpn doctor"
Write-Host "  yalevpn add server.conf"
Write-Host "  yalevpn up warp"
Write-Host "  yalevpn gui"
Write-Host ""
Write-Host "Note: the WireGuard backend needs the official client from"
Write-Host "https://www.wireguard.com/install/ (installed separately)." -ForegroundColor Yellow