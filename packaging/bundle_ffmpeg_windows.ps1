# Produces a self-contained ffmpeg.exe for the packaged Windows app by
# downloading a static build from BtbN/FFmpeg-Builds' latest GitHub release
# (queried via the API rather than a pinned version, so this doesn't go
# stale) and staging it where packaging/optical2digital.spec expects it.
#
# This is a build-time-only step — nothing here is shipped as-is; only the
# resulting packaging/build/ffmpeg-bundle/ffmpeg.exe is (via the spec's
# `datas`). Windows analog of bundle_ffmpeg_macos.sh — unlike that script,
# there's no dylibbundler-equivalent step here: BtbN's static builds have no
# external DLL dependencies to carry alongside ffmpeg.exe, so no libs/
# subdirectory is produced (verify this holds by running the extracted
# ffmpeg.exe standalone, off PATH, before trusting it in a real release).
param(
    [ValidateSet("x64", "arm64")]
    [string]$Arch = "x64"
)
$ErrorActionPreference = "Stop"

$RootDir = Split-Path -Parent $PSScriptRoot
$OutDir = Join-Path $RootDir "packaging\build\ffmpeg-bundle"

# BtbN's asset names embed "win64" / "winarm64" rather than our "x64" / "arm64".
$BtbnArchTag = if ($Arch -eq "x64") { "win64" } else { "winarm64" }

Write-Host "Looking up latest BtbN/FFmpeg-Builds release for $BtbnArchTag..."
$release = Invoke-RestMethod -Uri "https://api.github.com/repos/BtbN/FFmpeg-Builds/releases/latest" -Headers @{ "User-Agent" = "Optical2Digital-build" }

# BtbN publishes multiple flavors per arch (gpl/lgpl x shared/static); prefer
# the static gpl build. This regex is intentionally loose about the version
# segment (asset names churn, e.g. "ffmpeg-master-latest-win64-gpl.zip" vs a
# dated/tagged variant) but should be reconfirmed against the actual release
# listing if this ever stops matching.
$asset = $release.assets |
    Where-Object { $_.name -match $BtbnArchTag -and $_.name -match "gpl" -and $_.name -notmatch "shared" -and $_.name -match "\.zip$" } |
    Select-Object -First 1
if (-not $asset) {
    throw "No matching BtbN ffmpeg asset found for arch tag '$BtbnArchTag' in release '$($release.tag_name)'. Available assets: $($release.assets.name -join ', ')"
}

Write-Host "Downloading $($asset.name)..."
$zipPath = Join-Path $env:TEMP "ffmpeg-$Arch.zip"
Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $zipPath

$extractDir = Join-Path $env:TEMP "ffmpeg-$Arch-extract"
Remove-Item -Recurse -Force $extractDir -ErrorAction SilentlyContinue
Expand-Archive -Path $zipPath -DestinationPath $extractDir -Force

$ffmpegExe = Get-ChildItem -Path $extractDir -Recurse -Filter "ffmpeg.exe" | Select-Object -First 1
if (-not $ffmpegExe) {
    throw "ffmpeg.exe not found inside downloaded archive $($asset.name)"
}

Remove-Item -Recurse -Force $OutDir -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path $OutDir | Out-Null
Copy-Item $ffmpegExe.FullName -Destination (Join-Path $OutDir "ffmpeg.exe")

Write-Host "Bundled ffmpeg.exe ($Arch, from $($release.tag_name)) at $OutDir"
