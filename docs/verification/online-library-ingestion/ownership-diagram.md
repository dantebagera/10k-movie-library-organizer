# Frozen ownership diagram

```mermaid
flowchart LR
    subgraph Triggers["Trigger adapters - hints only"]
        FS["Filesystem observer\nservices/library_observer.py"]
        MAN["Startup and manual routes\napp.py wiring"]
        QBT["qBittorrent completion callback\nexisting manager and journal"]
    end

    LEASE["CatalogWriterLease\nexclusive process writer"]
    COORD["LibraryIngestionCoordinator\nservices/library_ingestion.py"]
    PROBE["Existing media probe owner"]
    ID["Existing identity and metadata owners"]
    ASSET["Existing media-asset service\nposter validation and immutable files"]
    REPO["CatalogRepository\nonly SQL write authority"]
    STORE["CatalogStore\none final-card eligibility query"]
    CANON["CanonicalCatalog\nonly card projection"]
    EVENTS["CatalogEventBroker\npost-commit identifiers only"]
    SSE["GET /api/catalog/events\none SSE connection"]
    APP["Root catalog event subscriber"]
    LIB["LibraryWorkspace\nbounded background SQL refetch"]
    FILE["File View\nphysical, pending, failed facts"]
    MOVIE["Movie View\nfinal cards only"]

    LEASE --> REPO
    FS --> COORD
    MAN --> COORD
    QBT --> COORD
    COORD --> PROBE
    COORD --> ID
    COORD --> ASSET
    COORD --> REPO
    REPO --> STORE
    REPO --> CANON
    STORE --> FILE
    STORE --> MOVIE
    REPO -->|"after commit"| EVENTS
    EVENTS --> SSE
    SSE --> APP
    APP --> LIB
    LIB -->|"current page/filter query"| STORE
```

## Forbidden ownership edges

- observer -> probe/provider/SQL;
- qBittorrent job store -> catalog publication logic;
- browser event payload -> manufactured card;
- route -> route-specific reconciliation or publication rule;
- coordinator -> direct SQL connection outside `CatalogRepository`;
- Movie View -> filesystem `stat`, walk, probe, or provider;
- File View -> final-card publication decision;
- any second CP backend -> catalog write access while the lease is held.

## Existing owners deliberately preserved

The new coordinator does not absorb:

- qBittorrent runtime, submission, job journal, seeding, move/import, cleanup, collision, or restart recovery;
- canonical projection rules;
- SQL connection/transaction authority;
- media probing implementation;
- provider-specific identity matching;
- poster asset storage/serving;
- File View or shared movie-card rendering.
