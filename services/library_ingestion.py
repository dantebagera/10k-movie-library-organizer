"""Authoritative reconciliation coordinator.

This module owns work normalization, bounded submission, stability, targeted
traversal, full inventory reconciliation, and retry-loop ordering. Domain
identity and metadata decisions remain injected from their established owners.
"""

import collections
import hashlib
import os
import threading
import time
import uuid
from dataclasses import dataclass


def file_is_readable(path):
    try:
        with open(path, "rb") as stream:
            stream.read(1)
        return True
    except (OSError, PermissionError):
        return False


def file_copy_is_stable(
    file_facts,
    previous=None,
    now=None,
    *,
    stability_seconds=15.0,
    wall_time=time.time,
):
    previous = previous or {}
    now = wall_time() if now is None else float(now)
    size = int(file_facts.get("size") or 0)
    modified_time = float(file_facts.get("modified_time") or 0)
    if modified_time and now - modified_time >= stability_seconds:
        return True
    same_observation = (
        int(previous.get("observed_size") or -1) == size
        and float(previous.get("observed_modified_time") or -1) == modified_time
    )
    observed_at = float(previous.get("observed_at") or 0)
    return bool(
        same_observation
        and observed_at
        and now - observed_at >= stability_seconds
    )


@dataclass(frozen=True)
class LibraryIngestionDependencies:
    store: object
    roots: object
    iter_video_files: object
    metadata_file_facts: object
    stability_check: object
    reconcile_path: object
    active_metadata_provider: object
    migrate_metadata_path: object
    resolve_authoritative_identity: object
    record_has_unresolved_identity: object
    record_needs_metadata_enrichment: object
    accepted_identity_evidence_changed: object
    identity_evidence_fingerprint: object
    record_needs_identity_decision_refresh: object
    plex_data: object
    plex_rescan: object
    auto_sync_plex: object
    inventory_bootstrap_cutoff: object
    clear_library_cache: object
    run_detail_backfill: object
    run_file_facts_backfill: object
    read_state: object
    write_state: object
    mark_complete: object
    identity_decision_version: int
    video_extensions: frozenset
    stability_seconds: float = 15.0
    sleep: object = time.sleep
    wall_time: object = time.time
    monotonic: object = time.monotonic
    readable_check: object = file_is_readable
    final_card_publication: object = lambda paths: []
    publish_catalog_event: object = lambda **kwargs: False
    apply_identity_hint: object = lambda path, identity, facts: False
    prepare_final_card_assets: object = lambda paths: None


class LibraryIngestionCoordinator:
    QUEUE_CAPACITY = 4096
    COALESCE_SECONDS = 0.5
    MAX_STABILITY_SECONDS = 24 * 60 * 60
    RETRY_DELAYS = (1, 2, 4, 8, 15)
    ASSET_RETRY_DELAYS = (2, 10, 30)

    def __init__(self, dependencies):
        self.dependencies = dependencies
        self._run_lock = threading.RLock()
        self._queue_condition = threading.Condition(threading.RLock())
        self._pending = collections.OrderedDict()
        self._dirty_roots = set()
        self._accepting = True
        self._dispatcher = None
        self._active = None
        self._last_result = {}
        self._last_error = ""
        self._identity_hints = {}

    @staticmethod
    def normalize_path(path):
        return os.path.normcase(os.path.normpath(os.path.abspath(str(path or ""))))

    def _root_for_path(self, path):
        normalized = self.normalize_path(path)
        for configured in self.dependencies.roots():
            root = self.normalize_path(configured)
            try:
                if os.path.commonpath((normalized, root)) == root:
                    return os.path.abspath(str(configured))
            except ValueError:
                continue
        return ""

    def _validate_path(self, path, *, require_directory=False):
        absolute = os.path.abspath(str(path or ""))
        root = self._root_for_path(absolute)
        if not root:
            raise ValueError(f"Path is outside configured library roots: {absolute}")
        if require_directory:
            if not os.path.isdir(absolute):
                raise ValueError(f"Library directory is unavailable: {absolute}")
        elif os.path.splitext(absolute)[1].lower() not in self.dependencies.video_extensions:
            raise ValueError(f"Path is not a supported video file: {absolute}")
        return absolute, root

    @classmethod
    def _contains_path(cls, parent, child):
        parent = cls.normalize_path(parent)
        child = cls.normalize_path(child)
        try:
            return os.path.commonpath((parent, child)) == parent
        except ValueError:
            return False

    def file_copy_is_stable(self, file_facts, previous=None, now=None):
        return self.dependencies.stability_check(file_facts, previous, now)

    def reconcile_path_now(self, path, provider=None, store=None, previous=None):
        store = store or self.dependencies.store()
        previous = previous or {}
        provider = provider or self.dependencies.active_metadata_provider(store)
        observation = self.dependencies.metadata_file_facts(path, probe=False)
        publication_pending = not (
            previous.get("identity_status") == "accepted"
            or bool(previous.get("metadata_accepted"))
        )
        if publication_pending:
            observation["movie_view_publication"] = (
                previous.get("movie_view_publication") or "pending"
            )
        if not self.file_copy_is_stable(observation, previous):
            pending_patch = {
                **observation,
                "ingest_status": "pending",
                "observed_size": observation.get("size", 0),
                "observed_modified_time": observation.get("modified_time", 0),
                "observed_at": self.dependencies.wall_time(),
            }
            if not self.dependencies.resolve_authoritative_identity(previous).get("accepted"):
                pending_patch.update({
                    "metadata_status": "pending",
                    "metadata_accepted": False,
                })
            store.update_file_record(path, pending_patch)
            return "pending"

        if not self.dependencies.readable_check(path):
            store.update_file_record(path, {
                **observation,
                "ingest_status": "pending",
                "observed_size": observation.get("size", 0),
                "observed_modified_time": observation.get("modified_time", 0),
                "observed_at": self.dependencies.wall_time(),
                "probe_error": "file_not_readable",
            })
            return "pending"

        facts = self.dependencies.metadata_file_facts(path, probe=True)
        facts.update({
            "ingest_status": "stable",
            "observed_size": facts.get("size", 0),
            "observed_modified_time": facts.get("modified_time", 0),
            "observed_at": self.dependencies.wall_time(),
        })
        if publication_pending:
            facts["movie_view_publication"] = (
                previous.get("movie_view_publication") or "pending"
            )
        probe_status = str(facts.get("probe_status") or "unprobed")
        if probe_status != "ok":
            retryable = probe_status in {"unprobed", "inaccessible", "file_changed"}
            store.update_file_record(path, {
                **facts,
                "ingest_status": "pending" if retryable else "failed",
                "metadata_status": "pending" if retryable else "failed",
                "metadata_accepted": False,
            })
            return "pending" if retryable else "failed"
        path_key = self.normalize_path(path)
        identity_hint = self._identity_hints.get(path_key)
        if identity_hint:
            try:
                if self.dependencies.apply_identity_hint(path, identity_hint, facts):
                    self._identity_hints.pop(path_key, None)
                    return "matched"
            except Exception:
                return "failed"
        if provider == "filename":
            store.update_file_record(path, {
                **facts,
                "display_provider": "filename",
                "metadata_status": "unmatched",
                "metadata_source": "filename",
                "metadata_accepted": False,
                "ingest_status": "stable",
                "identity_decision_version": self.dependencies.identity_decision_version,
                "observed_size": facts.get("size", 0),
                "observed_modified_time": facts.get("modified_time", 0),
                "observed_at": self.dependencies.wall_time(),
            })
            return "review"

        outcome = self.dependencies.migrate_metadata_path(
            path,
            provider,
            store=store,
            revalidate_accepted=bool(previous.get("_revalidate_identity")),
            facts=facts,
        )
        patch = {
            **facts,
            "ingest_status": "stable",
            "observed_size": facts.get("size", 0),
            "observed_modified_time": facts.get("modified_time", 0),
            "observed_at": self.dependencies.wall_time(),
        }
        if outcome == "review":
            post_migration = store.snapshot().get("files", {}).get(store._key(path), {})
            post_status = str(post_migration.get("identity_status") or "")
            if post_status == "conflict":
                patch.update({
                    "identity_status": "conflict",
                    "metadata_status": "conflict",
                    "metadata_accepted": False,
                    "identity_decision_version": self.dependencies.identity_decision_version,
                })
            elif post_status == "unmatched":
                patch.update({
                    "metadata_status": "unmatched",
                    "metadata_accepted": False,
                    "identity_decision_version": self.dependencies.identity_decision_version,
                })
            else:
                patch.update({
                    "identity_status": "review",
                    "metadata_status": "needs_review",
                    "metadata_accepted": False,
                    "identity_decision_version": self.dependencies.identity_decision_version,
                })
        elif outcome == "failed":
            patch.update({
                "metadata_status": "unmatched",
                "metadata_accepted": False,
                "identity_decision_version": self.dependencies.identity_decision_version,
            })
        store.update_file_record(path, patch)
        return outcome

    @staticmethod
    def _result(provider, removed=0):
        return {
            "checked": 0,
            "matched": 0,
            "review": 0,
            "pending": 0,
            "failed": 0,
            "removed": int(removed),
            "facts_refreshed": 0,
            "provider": provider,
        }

    def _candidate_for_path(
        self,
        path,
        filename,
        fingerprint,
        record,
        snapshot,
        provider,
        *,
        force_unresolved=False,
        enrich_accepted=True,
        inventory_exists=True,
        previous_inventory=None,
        bootstrap_cutoff=0,
    ):
        key = self.dependencies.store()._key(path)
        if record.get("metadata_accepted") or record.get("metadata_status") == "accepted":
            facts_changed = (
                int(record.get("size") or -1) != fingerprint["size"]
                or float(record.get("modified_time") or -1) != fingerprint["modified_time"]
                or (bool(record.get("filename")) and record.get("filename") != filename)
            )
            facts = record
            if facts_changed:
                facts = self.dependencies.metadata_file_facts(path, probe=False)
            plex_data = self.dependencies.plex_data(key, filename, snapshot)
            if provider in {"tmdb", "plex"} and self.dependencies.accepted_identity_evidence_changed(
                path, record, facts, plex_data
            ):
                return {**record, "_revalidate_identity": True}
            if facts_changed:
                return {**record, "_refresh_file_facts": True}
            if enrich_accepted and provider in {"tmdb", "plex"} and self.dependencies.record_needs_metadata_enrichment(
                facts, key, snapshot
            ):
                return facts
            return None
        if force_unresolved and self.dependencies.record_has_unresolved_identity(record):
            return record
        current_identity_fingerprint = ""
        if self.dependencies.record_has_unresolved_identity(record):
            file_facts = self.dependencies.metadata_file_facts(path, probe=False)
            current_identity_fingerprint = self.dependencies.identity_evidence_fingerprint(
                path,
                file_facts,
                self.dependencies.plex_data(key, file_facts.get("filename", filename), snapshot),
            )
        if self.dependencies.record_needs_identity_decision_refresh(
            record, current_identity_fingerprint
        ):
            return record
        if not record or record.get("metadata_status") == "pending":
            return record
        if not inventory_exists:
            changed = (
                bool(record)
                and (
                int(record.get("size") or -1) != fingerprint["size"]
                or float(record.get("modified_time") or -1) != fingerprint["modified_time"]
                )
            )
            try:
                newly_added = os.path.getctime(path) > bootstrap_cutoff
            except OSError:
                newly_added = False
            return record if changed or (not record and newly_added) else None
        previous = (previous_inventory or {}).get(key, {})
        changed = (
            not previous
            or int(previous.get("size") or -1) != fingerprint["size"]
            or float(previous.get("modified_time") or -1) != fingerprint["modified_time"]
        )
        return record if changed else None

    def _prepare_provider(self, provider, candidates):
        if provider == "plex" and candidates:
            self.dependencies.plex_rescan()
            self.dependencies.sleep(1)
            self.dependencies.auto_sync_plex(force=True)

    @staticmethod
    def _inventory_exists(store):
        owner = getattr(store, "has_library_inventory", None)
        if callable(owner):
            return bool(owner())
        return bool(store.library_inventory_file.exists())

    def _process_candidates(self, candidates, provider, store, result):
        matched_paths = []
        for path, previous in candidates:
            if previous.get("_refresh_file_facts"):
                observation = self.dependencies.metadata_file_facts(path, probe=False)
                if not self.file_copy_is_stable(observation, previous):
                    store.update_file_record(path, {
                        **observation,
                        "ingest_status": "pending",
                        "observed_size": observation.get("size", 0),
                        "observed_modified_time": observation.get("modified_time", 0),
                        "observed_at": self.dependencies.wall_time(),
                    })
                    result["pending"] += 1
                    continue
                refreshed = self.dependencies.metadata_file_facts(path, probe=True)
                store.update_file_record(path, {
                    **refreshed,
                    "ingest_status": "stable",
                    "observed_size": refreshed.get("size", 0),
                    "observed_modified_time": refreshed.get("modified_time", 0),
                    "observed_at": self.dependencies.wall_time(),
                })
                result["facts_refreshed"] += 1
                continue
            result["checked"] += 1
            try:
                outcome = self.dependencies.reconcile_path(
                    path, provider, store=store, previous=previous
                )
            except Exception:
                outcome = "failed"
            result[outcome if outcome in result else "failed"] += 1
            if outcome == "matched":
                matched_paths.append(path)
        if result["checked"] or result["removed"]:
            self.dependencies.clear_library_cache()
        result["_matched_paths"] = matched_paths
        return result

    def reconcile_all_now(self, force_unresolved=False, *, enrich_accepted=True):
        with self._run_lock:
            store = self.dependencies.store()
            snapshot = store.snapshot()
            records = snapshot.get("files", {})
            inventory_exists = self._inventory_exists(store)
            previous_inventory = store.get_library_inventory()
            bootstrap_cutoff = (
                self.dependencies.inventory_bootstrap_cutoff(store)
                if not inventory_exists
                else 0
            )
            provider = self.dependencies.active_metadata_provider(store)
            candidates = []
            current_inventory = {}
            for _, _, filename, path in self.dependencies.iter_video_files():
                try:
                    stat_result = os.stat(path)
                except OSError:
                    continue
                key = store._key(path)
                fingerprint = {
                    "path": path,
                    "size": int(stat_result.st_size),
                    "modified_time": float(stat_result.st_mtime),
                }
                current_inventory[key] = fingerprint
                previous = self._candidate_for_path(
                    path,
                    filename,
                    fingerprint,
                    records.get(key, {}),
                    snapshot,
                    provider,
                    force_unresolved=force_unresolved,
                    enrich_accepted=enrich_accepted,
                    inventory_exists=inventory_exists,
                    previous_inventory=previous_inventory,
                    bootstrap_cutoff=bootstrap_cutoff,
                )
                if previous is not None:
                    candidates.append((path, previous))

            removed = 0
            roots = [root for root in self.dependencies.roots() if root]
            if roots and all(os.path.isdir(root) for root in roots):
                removed = store.prune_missing_path_records(current_inventory.keys())
            store.save_library_inventory(current_inventory)
            self._prepare_provider(provider, candidates)
            return self._process_candidates(
                candidates, provider, store, self._result(provider, removed)
            )

    def reconcile_paths_now(
        self,
        paths,
        *,
        force_unresolved=False,
        identity_hints=None,
        enrich_accepted=True,
    ):
        with self._run_lock:
            for path, identity in dict(identity_hints or {}).items():
                self._identity_hints[self.normalize_path(path)] = dict(identity or {})
            validated = []
            for path in paths or ():
                absolute, _root = self._validate_path(path)
                if absolute not in validated:
                    validated.append(absolute)
            store = self.dependencies.store()
            snapshot = store.snapshot()
            records = snapshot.get("files", {})
            inventory_exists = self._inventory_exists(store)
            inventory = store.get_library_inventory()
            bootstrap_cutoff = (
                self.dependencies.inventory_bootstrap_cutoff(store)
                if not inventory_exists
                else 0
            )
            provider = self.dependencies.active_metadata_provider(store)
            candidates = []
            removed = 0
            for path in validated:
                key = store._key(path)
                try:
                    stat_result = os.stat(path)
                except OSError:
                    if os.path.isdir(self._root_for_path(path)):
                        if key in records:
                            store.remove_path_records(path)
                            removed += 1
                        inventory.pop(key, None)
                    continue
                fingerprint = {
                    "path": path,
                    "size": int(stat_result.st_size),
                    "modified_time": float(stat_result.st_mtime),
                }
                previous = self._candidate_for_path(
                    path,
                    os.path.basename(path),
                    fingerprint,
                    records.get(key, {}),
                    snapshot,
                    provider,
                    force_unresolved=force_unresolved,
                    enrich_accepted=enrich_accepted,
                    inventory_exists=inventory_exists,
                    previous_inventory=inventory,
                    bootstrap_cutoff=bootstrap_cutoff,
                )
                inventory[key] = fingerprint
                if previous is not None:
                    candidates.append((path, previous))
            store.save_library_inventory(inventory)
            self._prepare_provider(provider, candidates)
            return self._process_candidates(
                candidates, provider, store, self._result(provider, removed)
            )

    def reconcile_directories_now(
        self,
        directories,
        *,
        force_unresolved=False,
        enrich_accepted=True,
    ):
        validated = []
        paths = []
        for directory in directories or ():
            absolute, _root = self._validate_path(directory, require_directory=True)
            if absolute not in validated:
                validated.append(absolute)
            for current, _dirs, files in os.walk(absolute):
                for filename in files:
                    if os.path.splitext(filename)[1].lower() in self.dependencies.video_extensions:
                        paths.append(os.path.join(current, filename))
        result = self.reconcile_paths_now(
            paths,
            force_unresolved=force_unresolved,
            enrich_accepted=enrich_accepted,
        )
        if not validated:
            return result
        store = self.dependencies.store()
        current_keys = {store._key(path) for path in paths}
        inventory = store.get_library_inventory()
        for key in list(inventory):
            if any(self._contains_path(directory, key) for directory in validated) and key not in current_keys:
                inventory.pop(key, None)
        store.save_library_inventory(inventory)
        removed = store.prune_missing_path_records(current_keys, roots=validated)
        if removed:
            result["removed"] += removed
            self.dependencies.clear_library_cache()
        return result

    def run_reconcile_loop(
        self,
        run_inventory=True,
        run_detail_backfill=False,
        run_file_facts=False,
    ):
        detail_backfill = (
            self.dependencies.run_detail_backfill()
            if run_detail_backfill
            else dict(self.dependencies.read_state().get("detail_backfill") or {})
        )
        if not run_inventory:
            file_facts = (
                self.dependencies.run_file_facts_backfill()
                if run_file_facts
                else dict(self.dependencies.read_state().get("file_facts_backfill") or {})
            )
            self.dependencies.write_state({
                **self.dependencies.read_state(),
                "status": "completed",
                "detail_backfill": detail_backfill,
                "file_facts_backfill": file_facts,
                "updated_at": self.dependencies.wall_time(),
            })
            self.dependencies.mark_complete()
            return
        while True:
            result = self.reconcile_all_now()
            self.dependencies.write_state({
                **result,
                "detail_backfill": detail_backfill,
                "status": "running" if result.get("pending") else "completed",
                "updated_at": self.dependencies.wall_time(),
            })
            if not result.get("pending"):
                file_facts = (
                    self.dependencies.run_file_facts_backfill()
                    if run_file_facts
                    else dict(self.dependencies.read_state().get("file_facts_backfill") or {})
                )
                self.dependencies.write_state({
                    **self.dependencies.read_state(),
                    "file_facts_backfill": file_facts,
                    "updated_at": self.dependencies.wall_time(),
                })
                self.dependencies.mark_complete()
                return
            self.dependencies.sleep(self.dependencies.stability_seconds)

    def _submit(self, work_type, values, reason, correlation_id):
        correlation_id = str(correlation_id or uuid.uuid4())
        entries = []
        if work_type == "all":
            entries = [("all", ())]
        else:
            for value in values or ():
                absolute, root = self._validate_path(
                    value, require_directory=work_type == "directory"
                )
                entries.append((f"{work_type}:{self.normalize_path(absolute)}", (absolute, root)))
        accepted = 0
        coalesced = 0
        rejected = 0
        now = self.dependencies.monotonic()
        with self._queue_condition:
            if not self._accepting:
                rejected = len(entries)
            else:
                for key, payload in entries:
                    first_observed_at = now
                    if work_type == "directory":
                        absolute = payload[0]
                        ancestor = None
                        descendants = []
                        for pending_key, pending_item in self._pending.items():
                            if pending_item.get("type") != "directory":
                                continue
                            pending_path = pending_item.get("value") or ""
                            if self._contains_path(pending_path, absolute):
                                ancestor = pending_item
                                break
                            if self._contains_path(absolute, pending_path):
                                descendants.append(pending_key)
                        if ancestor is not None:
                            ancestor["reason"] = str(reason or ancestor["reason"])
                            ancestor["correlation_id"] = correlation_id
                            ancestor["not_before"] = now + self.COALESCE_SECONDS
                            coalesced += 1
                            continue
                        if descendants:
                            first_observed_at = min(
                                [now]
                                + [
                                    float(self._pending[item].get("first_observed_at") or now)
                                    for item in descendants
                                ]
                            )
                            for descendant in descendants:
                                self._pending.pop(descendant, None)
                            coalesced += len(descendants)
                    existing = self._pending.get(key)
                    if existing:
                        existing["reason"] = str(reason or existing["reason"])
                        existing["correlation_id"] = correlation_id
                        existing["not_before"] = now + self.COALESCE_SECONDS
                        coalesced += 1
                        continue
                    if len(self._pending) >= self.QUEUE_CAPACITY:
                        rejected += 1
                        root = payload[1] if payload else ""
                        if root:
                            self._dirty_roots.add(self.normalize_path(root))
                        continue
                    self._pending[key] = {
                        "type": work_type,
                        "value": payload[0] if payload else "",
                        "reason": str(reason or "manual"),
                        "correlation_id": correlation_id,
                        "not_before": now + self.COALESCE_SECONDS,
                        "first_observed_at": first_observed_at,
                        "retry_count": 0,
                    }
                    accepted += 1
                self._ensure_dispatcher_locked()
                self._queue_condition.notify_all()
            queue_depth = len(self._pending)
        return {
            "correlation_id": correlation_id,
            "accepted": accepted,
            "coalesced": coalesced,
            "rejected": rejected,
            "queue_depth": queue_depth,
        }

    def reconcile_paths(self, paths, reason, correlation_id=None, identity_hints=None):
        with self._run_lock:
            for path, identity in dict(identity_hints or {}).items():
                self._identity_hints[self.normalize_path(path)] = dict(identity or {})
        return self._submit("path", paths, reason, correlation_id)

    def reconcile_directories(self, directories, reason, correlation_id=None):
        return self._submit("directory", directories, reason, correlation_id)

    def reconcile_all(self, reason, correlation_id=None):
        return self._submit("all", (), reason, correlation_id)

    def _ensure_dispatcher_locked(self):
        if self._dispatcher and self._dispatcher.is_alive():
            return
        self._dispatcher = threading.Thread(
            target=self._dispatch,
            name="cinema-library-ingestion",
            daemon=True,
        )
        self._dispatcher.start()

    def _dispatch(self):
        while True:
            with self._queue_condition:
                while not self._pending and self._accepting:
                    self._queue_condition.wait()
                if not self._pending and not self._accepting:
                    return
                key, item = next(iter(self._pending.items()))
                delay = item["not_before"] - self.dependencies.monotonic()
                if delay > 0:
                    self._queue_condition.wait(timeout=delay)
                    continue
                self._pending.pop(key, None)
                self._active = dict(item)
            try:
                if item["type"] == "path":
                    result = self.reconcile_paths_now((item["value"],))
                elif item["type"] == "directory":
                    result = self.reconcile_directories_now((item["value"],))
                else:
                    result = self.reconcile_all_now()
                self._last_result = {
                    **{key: value for key, value in result.items() if not key.startswith("_")},
                    "reason": item["reason"],
                    "correlation_id": item["correlation_id"],
                }
                self._last_error = ""
                asset_retry = False
                matched_paths = result.get("_matched_paths") or (
                    [item["value"]] if item.get("asset_retry") and item.get("value") else []
                )
                if matched_paths:
                    try:
                        self.dependencies.prepare_final_card_assets(matched_paths)
                    except Exception as error:
                        asset_retry = True
                        self._last_error = f"{type(error).__name__}: {error}"
                publications = (
                    []
                    if asset_retry
                    else self.dependencies.final_card_publication(matched_paths)
                )
                if publications:
                    self.dependencies.publish_catalog_event(
                        reason=item["reason"].split(":", 1)[0],
                        movie_keys=[publication["movie_key"] for publication in publications],
                        changed_count=len(publications),
                        correlation_id=item["correlation_id"],
                    )
                if (
                    (int(result.get("pending") or 0) > 0 or asset_retry)
                    and item["type"] in {"path", "directory"}
                    and self._accepting
                ):
                    elapsed = self.dependencies.monotonic() - float(item.get("first_observed_at") or 0)
                    if elapsed < self.MAX_STABILITY_SECONDS:
                        retry_count = int(item.get("retry_count") or 0)
                        retry_delays = self.ASSET_RETRY_DELAYS if asset_retry else self.RETRY_DELAYS
                        if asset_retry and retry_count >= len(retry_delays):
                            for matched_path in matched_paths:
                                self.dependencies.store().update_file_record(matched_path, {
                                    "ingest_status": "failed",
                                    "poster_error": self._last_error,
                                })
                            continue
                        retry_delay = retry_delays[min(retry_count, len(retry_delays) - 1)]
                        retry_key = f"{item['type']}:{self.normalize_path(item['value'])}"
                        retry_item = {
                            **item,
                            "not_before": self.dependencies.monotonic() + retry_delay,
                            "retry_count": retry_count + 1,
                            "asset_retry": asset_retry,
                        }
                        with self._queue_condition:
                            if retry_key not in self._pending:
                                self._pending[retry_key] = retry_item
                            self._queue_condition.notify_all()
                    elif item["type"] == "path":
                        self.dependencies.store().update_file_record(item["value"], {
                            "ingest_status": "failed",
                            "probe_error": "stability_timeout",
                        })
            except Exception as error:
                self._last_error = f"{type(error).__name__}: {error}"
            finally:
                with self._queue_condition:
                    self._active = None
                    self._queue_condition.notify_all()

    def status(self):
        with self._queue_condition:
            active = dict(self._active) if self._active else None
            if active and active.get("value"):
                active["path_id"] = hashlib.blake2b(
                    self.normalize_path(active.pop("value")).encode(
                        "utf-8", errors="surrogatepass"
                    ),
                    digest_size=8,
                ).hexdigest()
            return {
                "accepting": self._accepting,
                "queue_depth": len(self._pending),
                "queue_capacity": self.QUEUE_CAPACITY,
                "active": active,
                "dirty_root_ids": [
                    hashlib.blake2b(
                        root.encode("utf-8", errors="surrogatepass"),
                        digest_size=8,
                    ).hexdigest()
                    for root in sorted(self._dirty_roots)
                ],
                "last_result": dict(self._last_result),
                "last_error": self._last_error,
            }

    def checkpoint_for_shutdown(self, timeout_seconds=30):
        """Stop new ingestion while leaving queued work recoverable at startup.

        A queued retry has already written its current file state to the catalog.
        Waiting for every retry would make a safe shutdown wait for hours. Mark
        affected roots dirty, discard only those in-memory retries, and let the
        active reconciliation finish before exit.
        """
        deadline = time.monotonic() + max(0, float(timeout_seconds))
        with self._queue_condition:
            self._accepting = False
            for item in self._pending.values():
                value = item.get("value")
                if not value or item.get("type") == "all":
                    self._dirty_roots.update(
                        self.normalize_path(root) for root in self.dependencies.roots()
                    )
                    continue
                root = self._root_for_path(value)
                if root:
                    self._dirty_roots.add(self.normalize_path(root))
            self._pending.clear()
            self._queue_condition.notify_all()
            dispatcher = self._dispatcher
        if dispatcher:
            dispatcher.join(timeout=max(0, deadline - time.monotonic()))
        if dispatcher and dispatcher.is_alive():
            return False
        remaining = max(0, deadline - time.monotonic())
        acquired = self._run_lock.acquire(timeout=remaining)
        if not acquired:
            return False
        self._run_lock.release()
        return True

    def resume_after_shutdown_failure(self):
        """Resume background ingestion when an OS power command was rejected."""
        with self._queue_condition:
            self._accepting = True
            self._ensure_dispatcher_locked()
            self._queue_condition.notify_all()

    def shutdown(self, timeout_seconds=10):
        with self._queue_condition:
            self._accepting = False
            self._queue_condition.notify_all()
            dispatcher = self._dispatcher
        if dispatcher:
            dispatcher.join(timeout=max(0, float(timeout_seconds)))
        return not (dispatcher and dispatcher.is_alive())
