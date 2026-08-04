# Gate 1 Rollback Design

Status: frozen before implementation. No production catalog or media root is used before separately approved live acceptance.

## Global rule

Gates 2 through 8 do not change the SQL schema. Each rollback restores the prior authoritative owner; it must not leave a dormant parallel importer, reconciler, publication rule, catalog source, or frontend card source.

Production data backup, live catalog inspection, and live acceptance remain Gate 10 actions requiring separate approval. All earlier rollback proof uses unique temporary 'CP_TEST_ROOT' directories and isolated catalogs.

## Gate-specific rollback

### Gate 2: ownership extraction and process lease

Revert the coordinator extraction and writer-lease integration together. The existing 'app.py' reconciliation owner resumes. Because Gate 2 does not change schema or publication semantics, no data conversion is required.

The rollback test must prove the old startup and manual routes still operate against the isolated catalog and no second writer remains.

### Gate 3: filesystem observation

Stop and join observer threads, remove the observer adapter and pinned dependency, and keep the shared coordinator for startup and manual triggers. A disabled observer must be reported as unmonitored; it must not pretend coverage exists.

A root-specific circuit breaker may disable one unhealthy observer without disabling healthy roots. That is an operational degradation, not a second observer implementation.

### Gate 4: publication pipeline

Roll back the final-card predicate, repository transaction, and post-commit broker integration as one unit. Partial acceptance of a new contract is forbidden.

Rows that never reached accepted final form remain invisible under the restored predicate. Fully published rows remain valid ordinary SQL catalog rows. An asset created before a failed transaction is an unreferenced candidate; it may be removed only by the existing reference-aware cleanup owner after isolated proof. 'file_generation' may remain ignored as catalog metadata but must not be used as a Movie View generation.

Gate 4 cannot proceed to production, so rollback is proven only on disposable databases.

### Gate 5: frontend event reconciliation

Close the one Library EventSource and restore the prior frontend refresh behavior. SQL publication remains correct and authoritative. No browser-local catalog is retained.

The rollback must prove that removing the subscriber does not clear filters or mutate stored catalog data.

### Gate 6: qBittorrent integration

Restore the existing qBittorrent completion callback only after proving the manager, import job, job journal, recovery, cleanup, and restart behavior are unchanged. Rollback must not edit or discard journal records. It removes only the coordinator handoff and restores the prior callback behavior.

### Gate 7: startup and recovery

Restore the prior startup trigger while preserving the shared coordinator used by other approved triggers. An offline root remains offline and is never pruned merely because rollback occurred.

### Gate 8: regression and performance hardening

Gate 8 introduces no new product behavior. Any hardening change is reverted with its owning gate if it violates an existing contract or budget.

### Gate 9: optional durable Windows file identity

Gate 9 is a separate schema-migration decision and is not approved by this architecture record. It requires its own backup, forward migration, rollback migration, parity, duplicate, move, and rename proofs before implementation.

### Gate 10: live acceptance

Gate 10 requires explicit approval, an exact live-catalog backup and restore procedure, process confirmation, and bounded fixtures. If acceptance fails, stop CP, restore only from the approved backup procedure, preserve diagnostic evidence, and do not touch qBittorrent or real media outside the accepted scope.

## Rollback stop conditions

Rollback fails, and the gate remains blocked, if any of these occur:

- two code paths can write the catalog;
- an observer or worker cannot be joined;
- an offline root would be interpreted as deleted;
- committed final cards become invisible or incomplete cards become visible;
- an event can be sent before its transaction commits;
- a qBittorrent journal or imported file would need destructive repair;
- the isolated rollback changes the live catalog, live roots, or another process;
- a schema change is required before Gate 9.

