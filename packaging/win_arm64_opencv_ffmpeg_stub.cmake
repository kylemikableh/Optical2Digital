# This file is part of Optical2Digital.
#
# Copyright (C) 2026 Kyle Mikolajczyk
#
# Optical2Digital is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# Optical2Digital is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Optical2Digital; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA

# Workaround for building opencv-python from source on Windows ARM64.
# Included only by the build-windows-arm64 CI job, via
# -DCMAKE_PROJECT_INCLUDE=<this file> (see release.yml).
#
# opencv-python's own packaging step (setup.py's rearrange_cmake_output_data)
# unconditionally requires a file matching
#   bin/opencv_videoio_ffmpeg\d{3}_64\.dll
# to exist in the CMake install tree for ANY 64-bit Windows build, regardless
# of whether ffmpeg support was actually compiled in. If it's missing,
# packaging hard-fails with "Exception: Not found: 'bin/opencv_videoio_
# ffmpeg\d{3}_64\.dll'" even though the real OpenCV build succeeded.
#
# OpenCV's own 3rdparty/ffmpeg/ffmpeg.cmake only ever defines a precompiled
# ffmpeg videoio plugin for BIN32 (x86) and BIN64 (x64) — there's no arm64
# entry at all, so on Windows ARM64 that plugin genuinely can never be built
# or downloaded. There's nothing real to produce here, so this installs a
# harmless placeholder that satisfies opencv-python's filename check instead.
#
# It is not a valid DLL and is never loaded: OpenCV's ffmpeg videoio backend
# is a lazily-loaded plugin, and cv2.VideoCapture falls back to the built-in
# Windows Media Foundation (MSMF) backend for reading video files — which is
# what this app already relies on (see KylesOpticalDecoder.py's
# cv2.VideoCapture usage) and needs no external plugin to work.
if(WIN32)
  set(_stub_dir "${CMAKE_BINARY_DIR}/win_arm64_ffmpeg_stub")
  file(MAKE_DIRECTORY "${_stub_dir}")
  file(WRITE "${_stub_dir}/opencv_videoio_ffmpeg000_64.dll" "")
  install(FILES "${_stub_dir}/opencv_videoio_ffmpeg000_64.dll" DESTINATION bin)
endif()
