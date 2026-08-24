# Windows analog of build-macos.sh: builds the frontend, bundles ffmpeg,
# generates the app icon, runs PyInstaller, then produces both a portable
# zip and an Inno Setup installer for the requested architecture.
param(
    [ValidateSet("x64", "arm64")]
    [string]$Arch = "x64"
)
$ErrorActionPreference = "Stop"

$RootDir = Split-Path -Parent $PSScriptRoot
Set-Location $RootDir

Write-Host "== Building frontend =="
Push-Location frontend
npm install
npm run build
Pop-Location

Write-Host "== Bundling ffmpeg =="
& "$RootDir\packaging\bundle_ffmpeg_windows.ps1" -Arch $Arch

$venvActivate = Join-Path $RootDir ".venv\Scripts\Activate.ps1"
if (-not (Test-Path $venvActivate)) {
    throw "No .venv found at $venvActivate. Create it first:`n" +
          "    python -m venv .venv`n" +
          "    .\.venv\Scripts\Activate.ps1`n" +
          "    pip install --upgrade pip`n" +
          "    pip install opencv-python numpy natsort scipy fastapi uvicorn pydantic pywebview pyinstaller pillow"
}

Write-Host "== Generating icon =="
& $venvActivate
python packaging\make_icon_windows.py

Write-Host "== Running PyInstaller =="
pyinstaller --noconfirm --distpath packaging\dist --workpath packaging\build\pyinstaller `
    packaging\optical2digital.spec

Write-Host "== Zipping portable build =="
$zipName = "Optical2Digital-win-$Arch.zip"
$zipPath = "packaging\dist\$zipName"
Remove-Item -Force $zipPath -ErrorAction SilentlyContinue
Compress-Archive -Path "packaging\dist\Optical2Digital\*" -DestinationPath $zipPath

Write-Host "== Building installer (Inno Setup) =="
iscc "/DAppArch=$Arch" packaging\optical2digital.iss

Write-Host "Done: $zipPath and packaging\dist\Optical2Digital-Setup-$Arch.exe"
