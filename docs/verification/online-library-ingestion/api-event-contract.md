# Gate 1 API and Event Contract

Status: frozen for later gated implementation. Gate 1 does not add routes or runtime behavior.

## Existing reconciliation API

The existing 'GET /api/library/reconcile' and 'POST /api/library/reconcile' routes remain backward compatible. Gate 2 may move their implementation behind 'LibraryIngestionCoordinator', but it must preserve their current response contract unless a separately approved gate changes it.

Manual reconciliation must call the same coordinator as startup, external-file, observer, and qBittorrent triggers. It must not become a second reconciliation or publication pipeline.

## Diagnostics API

Gate 2 introduces a read-only 'GET /api/library/ingestion/status' endpoint. Reading it must not walk the filesystem, stat media files, invoke ffprobe, call a metadata provider, change a queue, or write SQL.

The response contract includes:

- writer lease ownership and process identity;
- queue depth, capacity, oldest age, and dirty-root backpressure state;
- worker counts and current stage counts;
- configured roots with local, removable, network, online, degraded, and last-observed status;
- last successful publication generation and timestamp;
- last failed item stage, redacted path identifier, correlation identifier, and failure category;
- observer implementation and health;
- no credentials, provider tokens, raw journal data, or full media paths.

## Server-sent events

Gate 5 may add 'GET /api/catalog/events'. The endpoint is a notification channel only. SQL remains authoritative, and the browser must refetch the canonical SQL library page after receiving a notification.

Required response headers:

~~~text
Content-Type: text/event-stream; charset=utf-8
Cache-Control: no-cache, no-transform
Connection: keep-alive
X-Accel-Buffering: no
~~~

Flask request-bound data must be captured before the streaming generator begins. The stream emits a comment heartbeat every 15 seconds and advertises 'retry: 2000'.

### catalog-ready event

The only ordinary publication notification is 'catalog-ready'. Its event identifier is the committed media generation.

~~~text
id: <media_generation>
event: catalog-ready
data: {
  "type": "catalog-ready",
  "generation": <integer>,
  "reason": "startup|manual|external|observer|qbittorrent|recovery",
  "movie_keys": [<at most 100 identifiers>],
  "changed_count": <integer>,
  "truncated": <boolean>,
  "correlation_id": <opaque identifier>,
  "published_at": <UTC timestamp>
}
~~~

The payload does not contain cards, filesystem paths, metadata-provider responses, or intermediate state. It is emitted only after 'publish_final_card' commits successfully.

### catalog-sync event

'catalog-sync' tells the client to make one authoritative quiet refetch without assuming a specific delta. It is used for:

- initial connection;
- server restart;
- a 'Last-Event-ID' older than the retained ring;
- an invalid event identifier;
- client-queue overflow or coalescing where individual generations cannot be replayed safely.

### Replay, pressure, and shutdown

- The broker retains the newest 256 committed publication events in memory.
- 'Last-Event-ID' replays strictly newer retained generations.
- Each connected client has a bounded queue of 32 items.
- A full client queue is coalesced to the newest safe state and a 'catalog-sync' instruction; publication workers never block on a slow browser.
- Shutdown places a sentinel in each client queue, closes the generator, and does not abandon an in-flight SQL transaction.
- Reconnects and duplicate events must be idempotent.

## Browser subscriber

'src/api/catalogEvents.js' is the one frontend EventSource owner. The mounted Library workspace owns one subscription and closes it on unmount.

The subscriber:

- records the highest observed generation and ignores duplicate or decreasing generations;
- permits one quiet refetch in flight and at most one coalesced follow-up refetch;
- never calls the foreground loading path for a background event;
- leaves the existing grid mounted while the request is pending or fails;
- preserves filters, sorting, page, search, scroll, focus, selection, and expanded-card state;
- inserts or replaces cards only after the authoritative refetch succeeds and poster readiness has been validated;
- reports a persistent disconnection after 30 seconds through the existing Library status surface, without replacing the grid.

## Failure contract

- No pre-commit state may emit 'catalog-ready'.
- A successful commit followed by notification failure leaves SQL correct; the broker records the fault and a later 'catalog-sync' repairs the browser.
- A failed browser refetch retains the old grid and state and reports a non-blocking status.
- A failed poster preload does not insert a placeholder or partial card.
- If Gate 5 cannot prove correct post-commit streaming and quiet reconciliation, Gate 5 fails. It must not silently fall back to polling.

