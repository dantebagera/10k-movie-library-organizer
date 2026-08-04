# Gate 1 Dependency and License Review

Status: Gate 1 architecture review completed; Gate 3 installation and packaged qualification passed.

## Watcher decision

The observer dependency is frozen and installed as `watchdog==6.0.0`. The `watchmedo` extra was not installed.

Verified official facts on 2026-08-01:

- PyPI and the upstream releases page identify 6.0.0 as the current release.
- The package requires Python 3.9 or newer and lists Python 3.12 support.
- Windows observation uses 'ReadDirectoryChangesW' with I/O completion ports and worker threads.
- A Windows x86-64 wheel is published and is approximately 79.1 kB.
- The project is Apache License 2.0.
- The base package does not list a mandatory runtime dependency; PyYAML belongs to the optional 'watchmedo' extra.
- Recursive observation is supported.
- The official documentation says CIFS should use 'PollingObserver'. Its own documentation describes polling as slow and not recommended.

Sources:

- https://pypi.org/project/watchdog/
- https://github.com/gorakhargosh/watchdog/releases
- https://github.com/gorakhargosh/watchdog/blob/master/LICENSE

## Scope of use

The dependency is confined to the Gate 3 observer adapter. It does not own stability checks, probing, identity, metadata, artwork, canonical projection, SQL publication, qBittorrent import, or frontend refresh.

The observer emits only normalized path hints to 'LibraryIngestionCoordinator'. A hint is not proof that a file is stable, valid, or ready to publish.

For SMB/CIFS roots, Gate 3 does not enable recursive polling by default because a continuous tree walk conflicts with the approved idle filesystem budget. Such roots stay explicitly degraded and use manual or startup recovery unless later evidence supports a budget-compliant strategy.

## Alternatives rejected

- A handwritten Windows API watcher was rejected because it would duplicate mature OS-adapter behavior, increase shutdown and overflow risk, and create a second low-level subsystem to maintain.
- Poll-only observation was rejected because ordinary idle polling would create global or recursive filesystem walks.
- WebSockets were rejected for catalog notification because this contract needs only one-way post-commit signals; Flask streaming plus browser EventSource is sufficient and adds no dependency.

## Packaging and runtime impact

The current portable build copies 'requirements.txt', and 'run.bat' installs those requirements into the bundled environment. A Gate 3 dependency change therefore affects source installs and portable first-run installation, even though it does not alter the native player, qBittorrent manager, FFmpeg, or media-probing ownership.

Gate 3/8 isolated evidence proved:

- Python 3.12.8 imports watchdog 6.0.0 and the base package does not require PyYAML;
- native recursive observation starts, receives isolated temporary-root events, and stops cleanly;
- the observer starts no child process;
- package plus distribution metadata occupies 535,930 bytes in the verified environment;
- the portable package contains the exact requirements pin and observer module;
- `THIRD-PARTY-NOTICES.md` is present and identifies Apache License 2.0.

## SSE dependency review

No new SSE library is approved. Flask supports generator-based streaming responses, and browser EventSource natively handles named events, event identifiers, and reconnection for 'text/event-stream'.

Official references:

- https://flask.palletsprojects.com/en/stable/patterns/streaming/
- https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events

The material risk is that a long-lived stream occupies a server request worker. Gate 5 must prove the packaged server can keep one Library stream open while preserving existing API latency and shutdown behavior. Failure of that proof stops Gate 5.
