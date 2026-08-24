# This file is part of Kyle's Optical Decoder.
#
# Copyright (C) 2026 Kyle Mikolajczyk
#
# Kyle's Optical Decoder is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# Kyle's Optical Decoder is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Kyle's Optical Decoder; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA

$ErrorActionPreference = 'Stop'

$RootDir = $PSScriptRoot
$FrontendDir = Join-Path $RootDir 'frontend'

if (-not (Test-Path -LiteralPath $FrontendDir -PathType Container)) {
    Write-Host "Error: frontend directory not found at $FrontendDir"
    exit 1
}

$StartDevScript = Join-Path $RootDir 'start-dev.ps1'
if (-not (Test-Path -LiteralPath $StartDevScript -PathType Leaf)) {
    Write-Host "Error: start-dev.ps1 not found at $RootDir"
    exit 1
}

if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    Write-Host "Error: npm is not installed or not in PATH."
    exit 1
}

$VenvPython = Join-Path $RootDir '.venv\Scripts\python.exe'
if (Test-Path -LiteralPath $VenvPython -PathType Leaf) {
    $PythonCmd = $VenvPython
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $PythonCmd = 'python'
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $PythonCmd = 'py'
} else {
    Write-Host "Error: Python not found. Create .venv or install Python."
    exit 1
}

Write-Host "Installing backend dependencies..."
& $PythonCmd -m pip install -r (Join-Path $RootDir 'requirements.txt')
if ($LASTEXITCODE -ne 0) {
    throw "pip install failed with exit code $LASTEXITCODE"
}

Write-Host "Installing frontend dependencies..."
Push-Location -LiteralPath $FrontendDir
try {
    npm install
    if ($LASTEXITCODE -ne 0) {
        throw "npm install failed with exit code $LASTEXITCODE"
    }
} finally {
    Pop-Location
}

Write-Host "Starting backend + frontend dev servers..."
& $StartDevScript
