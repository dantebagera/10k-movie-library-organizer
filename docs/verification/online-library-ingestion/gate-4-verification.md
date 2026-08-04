# Gate 4 verification — passed with one required plan correction

## Outcome

Newly observed media is written with `movie_view_publication=pending`. Both SQL Movie View query paths exclude pending rows. `CatalogRepository.final_card_publication(paths)` is the sole transition to `ready`; it validates stable current probe facts, accepted identity, complete selected-provider projection, canonical contract version, people terminal state, and checksum-verified local poster or explicit no-poster state.

The ready marker and one media-generation advance occur in one SQLite transaction. A broker event is emitted only after that transaction returns successfully. Duplicate ready work does not bump generation again or emit another event.

## Required correction to the frozen design

Gate 1 named a hypothetical `publish_final_card(bundle)` transaction that would write every probe, identity, metadata, asset, mapping, and visibility fact at once. Current authoritative owners persist those fallible stage results separately. Holding SQLite open across file probing, provider work, or asset download would contradict those owners and increase lock risk.

The implemented contract stages incomplete facts in SQL but hides them from Movie View. The atomic publication transaction contains the only visibility change plus generation advance. This preserves the user-visible all-or-nothing invariant without creating a second metadata/catalog pipeline. `CatalogRepository`, not `CatalogStore`, owns predicate validation; `CatalogStore` owns the SQL visibility clause and canonical page query.

## Proof

- `tests.test_final_card_publication`: strict negative predicate matrix, local/no-poster terminal states, remote-poster cache preparation, pending invisibility, one generation bump, idempotence, and injected rollback.
- `tests.test_library_ingestion_queue`: assets → commit → event ordering; poster failure never calls publication or notification and ends in a File View diagnostic after bounded retry.
- `tests.test_catalog_events`: replay, stale cursor sync, slow-client coalescing, payload, and shutdown.
- SQL page integration proves zero rows before publication, one row after commit, and zero rows after injected transaction failure.

No schema migration was introduced; schema remains v10.
