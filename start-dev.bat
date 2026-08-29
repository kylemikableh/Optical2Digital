@echo off
:: This file is part of Optical2Digital.
::
:: Copyright (C) 2026 Kyle Mikolajczyk
::
:: Optical2Digital is free software; you can redistribute it and/or modify
:: it under the terms of the GNU General Public License as published by
:: the Free Software Foundation; either version 2 of the License, or
:: (at your option) any later version.
::
:: Optical2Digital is distributed in the hope that it will be useful,
:: but WITHOUT ANY WARRANTY; without even the implied warranty of
:: MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
:: GNU General Public License for more details.
::
:: You should have received a copy of the GNU General Public License
:: along with Optical2Digital; if not, write to the Free Software
:: Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-dev.ps1" %*
