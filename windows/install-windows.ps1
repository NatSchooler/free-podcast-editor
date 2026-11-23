# Media Hub: Free Podcast Editing Software - Windows installer
# Installs WSL with Ubuntu 24.04 if needed, then runs the Ubuntu installer inside it.
# MIT licence. No support is provided: if something breaks, it is yours to fix.
$ErrorActionPreference = "Stop"
$Distro = "Ubuntu-24.04"
$Pack = Split-Path -Parent $PSScriptRoot

Write-Host "`n== Media Hub for Windows ==" -ForegroundColor Yellow

$list = (wsl.exe --list --quiet 2>$null) -replace "`0", ""
if (-not ($list -match [regex]::Escape($Distro))) {
    Write-Host "Installing WSL and $Distro. This can take a while."
    wsl.exe --install -d $Distro
    Write-Host "`nWhen Ubuntu opens, choose a username and password."
    Write-Host "If Windows asks you to restart, please restart, then run INSTALL-ON-WINDOWS.bat again." -ForegroundColor Yellow
    exit 0
}

# Work on a Linux-side copy of the pack (much faster than running from the Windows drive)
$WslPack = (wsl.exe -d $Distro -- wslpath -a "$Pack").Trim()
Write-Host "Copying the pack into Ubuntu and running the installer..."
wsl.exe -d $Distro -- bash -lc "rm -rf ~/free-podcast-editor && cp -r '$WslPack' ~/free-podcast-editor && sed -i 's/\r$//' ~/free-podcast-editor/install.sh && bash ~/free-podcast-editor/install.sh"

Write-Host "`nDone. Open http://localhost:8080 in your browser." -ForegroundColor Green
Write-Host "To start Media Hub after a restart, open Ubuntu from the Start menu and run: bash ~/mediahub/mediahub_restart.sh"
