; This file is part of Optical2Digital.
;
; Copyright (C) 2026 Kyle Mikolajczyk
;
; Optical2Digital is free software; you can redistribute it and/or modify
; it under the terms of the GNU General Public License as published by
; the Free Software Foundation; either version 2 of the License, or
; (at your option) any later version.
;
; Optical2Digital is distributed in the hope that it will be useful,
; but WITHOUT ANY WARRANTY; without even the implied warranty of
; MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
; GNU General Public License for more details.
;
; You should have received a copy of the GNU General Public License
; along with Optical2Digital; if not, write to the Free Software
; Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA

; Inno Setup script for Optical2Digital, shared between x64 and arm64 builds
; via the AppArch preprocessor define (passed as /DAppArch=x64|arm64 from
; build-windows.ps1). Inno Setup resolves relative paths (OutputDir, [Files]
; Source, etc.) against the directory containing this .iss file, not the
; caller's working directory — so paths here are relative to packaging\,
; even though build-windows.ps1 itself runs from the repo root.
#ifndef AppArch
  #define AppArch "x64"
#endif
; AppVersion preprocessor define, passed as /DAppVersion=<version> from
; build-windows.ps1 (which in turn derives it from the release git tag via
; .github/workflows/release.yml). Falls back to a clearly-marked dev
; version for manual/local builds that don't pass one.
#ifndef AppVersion
  #define AppVersion "0.0.0-dev"
#endif

[Setup]
AppId={{49061815-55F2-4CA5-8AD8-2C6561805D5C}
AppName=Optical2Digital
AppVersion={#AppVersion}
AppPublisher=Kyle Mikolajczyk
DefaultDirName={autopf}\Optical2Digital
DefaultGroupName=Optical2Digital
UninstallDisplayIcon={app}\Optical2Digital.exe
OutputDir=dist
OutputBaseFilename=Optical2Digital-Setup-{#AppArch}
Compression=lzma2
SolidCompression=yes
; No code signing — matches the unsigned macOS .dmg; Windows SmartScreen
; will show an "unrecognized publisher" warning, documented in README.md
; the same way the macOS Gatekeeper warning is.
#if AppArch == "arm64"
ArchitecturesAllowed=arm64
ArchitecturesInstallIn64BitMode=arm64
#else
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
#endif

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"

[Files]
Source: "dist\Optical2Digital\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Optical2Digital"; Filename: "{app}\Optical2Digital.exe"
Name: "{group}\Uninstall Optical2Digital"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Optical2Digital"; Filename: "{app}\Optical2Digital.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Optical2Digital.exe"; Description: "Launch Optical2Digital"; Flags: nowait postinstall skipifsilent
