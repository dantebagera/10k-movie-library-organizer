import os
import time
from pathlib import Path

from .iptv_metadata_settings import IPTVMetadataSettings
from .iptv_movie_service import IPTVMovieService, classify_enrichment_error
from .iptv_service import IPTVService


MAX_DIAGNOSTIC_BATCH = 100
MIN_SOURCE_INTERVAL_SECONDS = 0.35
PREPARATION_BATCH_SIZE = 100
MAX_CLUSTER_MEMBERS = 8


def run_worker(movie_service, *, max_jobs=0, lease_token=""):
    store = movie_service.store
    completed = 0
    token = str(lease_token or store.current_worker_token() or "")
    store.worker_started(os.getpid(), token)
    try:
        while True:
            store.worker_heartbeat(token)
            status = store.worker_command_state(token)
            command = status["command"]
            if command == "pause":
                store.worker_finished("paused", token=token)
                return "paused"
            if command == "cancel":
                store.cancel_enrichment()
                return "cancelled"
            remaining_budget = max_jobs - completed if max_jobs else MAX_CLUSTER_MEMBERS
            cluster = store.claim_next_cluster(token, limit=min(MAX_CLUSTER_MEMBERS, remaining_budget))
            if cluster is None:
                preparation = movie_service.classify_catalog_batch(limit=PREPARATION_BATCH_SIZE)
                staged = store.stage_enrichment_batch(PREPARATION_BATCH_SIZE)
                cluster = store.claim_next_cluster(
                    token, limit=min(MAX_CLUSTER_MEMBERS, remaining_budget)
                )
            if cluster is None:
                if preparation.get("processed") or staged:
                    time.sleep(MIN_SOURCE_INTERVAL_SECONDS)
                    continue
                store.worker_finished("complete", token=token)
                return "complete"
            outcomes = movie_service.enrich_work_cluster(
                cluster["source_keys"],
                should_continue=lambda: store.worker_run_requested(token),
            )
            pause_reason = None
            for outcome in outcomes:
                source_key_value = outcome["source_key"]
                error = outcome.get("_error")
                if error is None:
                    store.finish_job(source_key_value, status="done")
                    completed += 1
                    continue
                state, code, retryable, retry_after = classify_enrichment_error(error)
                message = movie_service.metadata_settings.redact(error)
                store.set_match_state(
                    [source_key_value], state, method="worker", error_code=code, error_message=message
                )
                store.finish_job(
                    source_key_value,
                    status="pending" if retryable else "failed",
                    retry_after=retry_after,
                    error=message,
                )
                if code == "authentication":
                    pause_reason = "IPTV TMDB authentication failed"
                if code == "rate-limit":
                    store.worker_backoff(token, "IPTV TMDB rate limit reached", time.time() + retry_after)
                    pause_reason = "IPTV TMDB rate limit reached"
                completed += 1
            if len(outcomes) < len(cluster["source_keys"]):
                store.release_cluster(cluster["work_key"], token)
            else:
                store.finish_cluster(cluster["work_key"], token)
            if pause_reason:
                store.worker_finished("paused", pause_reason, token=token)
                return "paused"
            if max_jobs and completed >= int(max_jobs):
                store.worker_finished("paused", token=token)
                return "paused"
            time.sleep(MIN_SOURCE_INTERVAL_SECONDS)
    except BaseException as error:
        store.worker_finished("crashed", movie_service.metadata_settings.redact(error), token=token)
        raise


def main():
    provider_id = str(os.environ.get("CP_IPTV_WORKER_PROVIDER_ID") or "")
    provider_root = Path(os.environ.get("CP_IPTV_WORKER_PROVIDER_ROOT") or "").resolve()
    user_data_dir = Path(os.environ.get("CP_IPTV_WORKER_USER_DATA_DIR") or "").resolve()
    if not provider_id or not provider_root.name == provider_id or not user_data_dir:
        raise RuntimeError("IPTV metadata worker configuration is invalid")
    expected_root = (user_data_dir / "iptv" / "providers" / provider_id).resolve()
    if provider_root != expected_root:
        raise RuntimeError("IPTV metadata worker provider path escaped its data root")
    raw_service = IPTVService(provider_root, provider_id)
    settings = IPTVMetadataSettings(user_data_dir)
    # Worker-only clients use finite conservative network waits. A control
    # command stops further source claims; the one in-flight source is bounded.
    from .iptv_tmdb import IPTVTMDBClient
    movie_service = IPTVMovieService(
        provider_root,
        provider_id,
        raw_service,
        settings,
        tmdb_client_factory=lambda: IPTVTMDBClient(
            settings, timeout=8, min_request_interval=MIN_SOURCE_INTERVAL_SECONDS
        ),
    )
    lease_token = str(os.environ.get("CP_IPTV_WORKER_LEASE_TOKEN") or "")
    scheduler_path = Path(os.environ.get("CP_IPTV_WORKER_SCHEDULER_PATH") or "")
    try:
        requested_limit = int(os.environ.get("CP_IPTV_WORKER_MAX_JOBS") or 0)
        if requested_limit:
            requested_limit = max(1, min(MAX_DIAGNOSTIC_BATCH, requested_limit))
        run_worker(movie_service, max_jobs=requested_limit, lease_token=lease_token)
    finally:
        raw_service.close()
        if scheduler_path.name == "metadata-worker-scheduler.json" and scheduler_path.parent == (user_data_dir / "iptv").resolve():
            try:
                import json
                current = json.loads(scheduler_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                current = {}
            if current.get("provider_id") == provider_id and current.get("token") == lease_token:
                try:
                    scheduler_path.unlink()
                except FileNotFoundError:
                    pass


if __name__ == "__main__":
    main()
