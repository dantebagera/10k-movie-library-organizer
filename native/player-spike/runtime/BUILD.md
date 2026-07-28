# Reproducing the Phase 0 LGPL libmpv runtime

The authoritative inputs and output hash are in `../runtime-lock.json`.

1. Use Ubuntu 22.04 under WSL2 and install the build prerequisites documented
   by the pinned `mpv-winbuild-cmake` repository. The successful build used
   CMake 3.31.10, Meson 1.11.2, `pkgconf` 1.8.0, and Python Jinja2.
2. Clone `https://github.com/shinchiro/mpv-winbuild-cmake.git`, check out
   revision `5efd298cb51513c2410e4e9029b5e56b83c2aaac`, and apply
   `mpv-winbuild-cmake-lgpl.patch`.
3. Configure for `x86_64-w64-mingw32` with `GCC_ARCH=x86-64`. Do not raise the
   CPU baseline.
4. Build the `gcc` target once, then build the `mpv` target.
5. Verify `ffmpeg.exe -L` reports the GNU Lesser General Public License,
   verify the required decoder list, and verify the produced `libmpv-2.dll`
   SHA-256 equals
   `0A76BD542BBA2D85ABEFCC7CD1005269085E1B5815B4E8BAEC62FF4EA4246675`.
6. Run the complete real-media matrix before accepting any rebuilt DLL.

The patch intentionally disables scripting, DVD navigation, Rubber Band, and
GPL codec libraries. Do not re-enable them without a new license review and a
full runtime regression pass.
