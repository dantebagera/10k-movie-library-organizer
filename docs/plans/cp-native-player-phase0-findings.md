# Cinema Paradiso native player - Phase 0 findings

Date: 2026-07-28

Baseline checkpoint: `51a74a7993661afdd49a475050fe76d170a244a8`

Baseline test-fix checkpoint: `1c441f38184501a3b509f7370f84f47f03003e5e`

## Scope held

The spike is isolated under `native/player-spike`. It adds no production player
configuration, backend route, catalog/history state, or portable-release
integration. It does not change IPTV playback or the movie-card Stream button.

## Rendering stack result

- Compiler: MSVC 19.44.35228, x64.
- Qt: official Qt 6.10.3 MSVC 2022 x64 packages, installed with `aqtinstall`
  archive verification.
- Rendering: Qt Quick forced to OpenGL, with libmpv's render API drawing into a
  `QQuickFramebufferObject`.
- Initial render-only libmpv candidate: shinchiro `20260610`, mpv revision
  `304426c`; rejected because its recipe used mpv's GPL-default configuration.
- Accepted candidate: reproduced from shinchiro recipe revision
  `5efd298cb51513c2410e4e9029b5e56b83c2aaac` with the committed LGPL patch.
- Accepted mpv revision:
  `48e6c35c0e056d9e4ff04b98e012416697736d8a`.
- Accepted FFmpeg revision:
  `c6309b5c63add7ad0ec221fafefc32bdcd6f8b91`.
- Accepted `libmpv-2.dll` SHA-256:
  `0A76BD542BBA2D85ABEFCC7CD1005269085E1B5815B4E8BAEC62FF4EA4246675`.

Qt 6.8.3 was rejected after repeated sustained-render shutdown crashes at an
effective 200% scale. Windows Error Reporting identified `qwindows.dll` 6.8.3,
exception `0xC0000005`, offset `0x3fae`. The same source, media, automation, and
scale completed cleanly on Qt 6.10.3.

## Fixture matrix

The isolated matrix covered:

- H.264 SDR, AAC English, AC-3 French, embedded SRT, embedded ASS, and an
  external SRT;
- HEVC 10-bit with BT.2020/PQ HDR headers, DTS Japanese, and TrueHD English;
- FFmpeg's small public `supsample.mkv` fixture with an HDMV PGS subtitle.

Final Qt 6.10.3 desktop results with the accepted LGPL DLL:

| Scenario | Scale | Load | First frame | Seek | Tracks | Fullscreen | Resize | Errors |
| --- | ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: |
| SDR H.264 | 100% | 967 ms | 417 ms after command | passed | AAC to AC-3; SRT/ASS/external SRT | passed | passed | 0 |
| HDR HEVC 10-bit | 200% | 935 ms | 402 ms after command | passed | DTS to TrueHD | passed | passed | 0 |
| PGS | 100% | 901 ms | 390 ms after command | passed | HDMV PGS | not requested | passed | 0 |

All three processes exited with code 0. A cloned package with its
`libmpv-2.dll` removed also exited with code 0, showed
`Native runtime unavailable`, and did not attempt playback.

Windows process metadata confirmed the running helper command line contained
only `--scenario` and `--report` file arguments. It contained no media filename
and no credential-like value. The live report showed the file loaded through
the LGPL DLL with zero errors.

## Desktop evidence

The isolated report directory contains:

- `sdr-100.png`, 1024x576, SHA-256
  `AF6927E87D1C29809407C6DE67D336C9C6D2B0FC58603A20D80ED2CE89E006BB`;
- `hdr-200.png`, 1584x861, SHA-256
  `AF6FE7964019DE0F09341946DE9459F920A48A8311A7526A43481A946D9DF115`;
- `pgs-100.png`, 800x450, SHA-256
  `623135435125303FDD3731295BFF67E8CBCE776A5DAACBA41663AF6E14B63D12`.

## Package measurement

The final trimmed technical package contains 308 files and 212,884,624 bytes
(203.02 MiB). The accepted LGPL DLL is 114,018,318 bytes. Production is
remeasured later because its complete license/source/relinking bundle is
intentionally outside this spike.

The package inventory hashes every deployed file and rejects known CP user-data
files/directories. The Phase 0 package remains marked `DO_NOT_DISTRIBUTE` only
because the production compliance bundle is incomplete.

## Licensing gate

The render path is viable on Qt 6.10.3 and the LGPL libmpv gate is closed.

The committed recipe patch sets mpv to `-Dgpl=false`, sets FFmpeg to
`--disable-gpl --enable-version3`, and removes GPL or unused AviSynth, davs2,
DVD, Rubber Band, x264, x265, and Xvid dependencies. FFmpeg's runtime `-L`
probe reports the GNU Lesser General Public License version 3 or later. The
required decoder probe and complete real-media matrix passed.

Production packaging must still include complete Qt/libmpv/FFmpeg dependency
notices, license texts, corresponding source or offer, relinking material, and
verified runtime hashes.

## Verification

- Native MSVC/CMake release build: passed.
- Reproducible LGPL MinGW libmpv build: passed.
- FFmpeg LGPL license and decoder probes: passed.
- Final packaged SDR/HDR/PGS desktop matrix: passed.
- Missing-libmpv behavior: passed.
- Process-argument and report-redaction checks: passed.
- New isolated Python regression tests: 5 passed.
- Frontend Node tests: 70 passed.
- `npm.cmd run build`: passed, 1647 modules, 2.07 seconds.
- Live catalog, migrations, media modification, media associations, and
  production routes: untouched.
