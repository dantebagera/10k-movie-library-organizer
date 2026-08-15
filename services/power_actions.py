"""Durable, at-most-once power actions coordinated with CP download recovery."""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path


class PowerActionError(RuntimeError):
    pass


class PowerActionCoordinator:
    ACTIONS = {"cp", "device", "restart"}
    ACTIVE_PLAN_STATES = {"armed", "draining"}
    TRACKED_JOB_STATES = {
        "downloading", "finalizing", "moving", "payload_imported",
        "cleanup_failed", "move_failed", "destination_conflict",
    }
    WAITING_JOB_STATES = {"downloading", "finalizing", "moving", "payload_imported"}
    CHECKPOINT_HANDOFF_STATES = {"applied", "queued", "failed", "deferred", "not_required"}

    def __init__(self, path, jobs_provider, execute_callback, *, clock=time.time, id_factory=None):
        self.path = Path(path)
        self.jobs_provider = jobs_provider
        self.execute_callback = execute_callback
        self.clock = clock
        self.id_factory = id_factory or (lambda: uuid.uuid4().hex)
        self._lock = threading.RLock()
        self._dispatching = False
        self._plan = self._read()
        if self._plan.get("state") in self.ACTIVE_PLAN_STATES:
            self._plan.update({
                "state": "paused",
                "paused_at": self.clock(),
                "detail": "CP restarted before the power action was dispatched. Recovery continues; resume or cancel the power action.",
            })
            self._write(self._plan)
        elif self._plan.get("state") == "dispatch_claimed":
            if self._plan.get("action") in {"cp", "restart"}:
                self._plan.update({
                    "state": "completed",
                    "completed_at": self.clock(),
                    "updated_at": self.clock(),
                    "detail": "Cinema Paradiso previously completed its lifecycle command.",
                })
            else:
                self._plan.update({
                    "state": "dispatch_unknown",
                    "updated_at": self.clock(),
                    "detail": "CP restarted after claiming the power command. It will not repeat the command automatically; clear this notice when the device state is known.",
                })
            self._write(self._plan)

    def _read(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _write(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{uuid.uuid4().hex}.tmp")
        with open(temporary, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self.path)

    @staticmethod
    def _job_title(job):
        return str(job.get("title") or job.get("release_title") or job.get("hash") or "Download")

    @classmethod
    def _job_is_trackable(cls, job):
        state = str(job.get("state") or "")
        if state in cls.TRACKED_JOB_STATES:
            return True
        if state == "imported":
            handoff_state = str((job.get("identity_handoff") or {}).get("state") or "")
            return bool(job.get("library_scan_pending") or not handoff_state)
        return False

    @classmethod
    def _job_checkpoint(cls, job):
        state = str(job.get("state") or "")
        if state in cls.WAITING_JOB_STATES:
            return False, f"{state.replace('_', ' ')} is still active"
        if state in {"move_failed", "destination_conflict"}:
            evidence = job.get("last_error") or job.get("collision")
            return bool(evidence), str(job.get("last_error") or "The move problem is safely journaled")
        if state in {"cancelled", "abandoned"}:
            return True, str(job.get("terminal_reason") or state)
        if state in {"imported", "cleanup_failed"}:
            handoff_state = str((job.get("identity_handoff") or {}).get("state") or "")
            ready = handoff_state in cls.CHECKPOINT_HANDOFF_STATES
            return ready, (
                f"identity handoff is {handoff_state or 'pending'}"
                if not ready else f"identity handoff checkpoint: {handoff_state}"
            )
        return False, f"download state {state or 'unknown'} is not recoverable yet"

    def _jobs(self):
        return dict(self.jobs_provider() or {})

    def active_jobs(self):
        return [job for job in self._jobs().values() if self._job_is_trackable(job)]

    def request(self, action, *, after_download=False, close_qbittorrent=False):
        action = str(action or "").strip().lower()
        if action not in self.ACTIONS:
            raise PowerActionError("Power action must be cp, restart, or device")
        if action == "restart" and after_download:
            raise PowerActionError("Restart cannot be scheduled after downloads")
        if action != "cp" and close_qbittorrent:
            raise PowerActionError("qBittorrent can be closed only when turning off CP")
        with self._lock:
            if self._plan.get("state") in {"armed", "draining", "dispatch_claimed", "dispatch_unknown"}:
                raise PowerActionError("A power action is already active")
            jobs = self.active_jobs() if after_download else []
            if after_download and not jobs:
                raise PowerActionError("There are no active CP downloads to wait for")
            now = self.clock()
            self._plan = {
                "plan_id": self.id_factory(),
                "action": action,
                "after_download": bool(after_download),
                "close_qbittorrent": bool(close_qbittorrent),
                "state": "armed" if after_download else "draining",
                "created_at": now,
                "updated_at": now,
                "targets": [
                    {"hash": str(job.get("hash") or "").lower(), "title": self._job_title(job)}
                    for job in jobs if job.get("hash")
                ],
                "detail": (
                    "Waiting for recoverable checkpoints"
                    if after_download
                    else "Preparing to restart" if action == "restart" else "Preparing to turn off"
                ),
            }
            self._write(self._plan)
            if not after_download:
                self._start_dispatch_locked()
            return self.snapshot()

    def snapshot(self):
        with self._lock:
            jobs = self._jobs()
            plan = dict(self._plan)
            target_status = []
            for target in plan.get("targets") or []:
                job = jobs.get(str(target.get("hash") or "").lower(), {})
                ready, detail = self._job_checkpoint(job) if job else (False, "Download journal entry is missing; shutdown is blocked")
                target_status.append({
                    **target,
                    "state": str(job.get("state") or "missing"),
                    "checkpointed": bool(ready),
                    "detail": detail,
                })
            return {
                "supported": os.name == "nt",
                "active_downloads": len(self.active_jobs()),
                "plan": {**plan, "target_status": target_status} if plan else {},
            }

    def evaluate(self):
        with self._lock:
            if self._plan.get("state") != "armed":
                return False
            jobs = self._jobs()
            for target in self._plan.get("targets") or []:
                job = jobs.get(str(target.get("hash") or "").lower())
                if not job:
                    return False
                ready, _detail = self._job_checkpoint(job)
                if not ready:
                    return False
            self._plan.update({
                "state": "draining",
                "updated_at": self.clock(),
                "detail": "All target downloads are recoverably checkpointed; draining CP work",
            })
            self._write(self._plan)
            self._start_dispatch_locked()
            return True

    def _start_dispatch_locked(self):
        if self._dispatching:
            return
        self._dispatching = True
        plan_id = self._plan.get("plan_id")
        action = self._plan.get("action")
        close_qbittorrent = bool(self._plan.get("close_qbittorrent"))
        threading.Thread(
            target=self._dispatch,
            args=(plan_id, action, close_qbittorrent),
            name="cinema-power-action",
            daemon=True,
        ).start()

    def _dispatch(self, plan_id, action, close_qbittorrent):
        try:
            self.execute_callback(
                action,
                plan_id,
                self.claim_dispatch,
                close_qbittorrent=close_qbittorrent,
            )
        except Exception as error:
            with self._lock:
                if self._plan.get("plan_id") == plan_id:
                    claimed = self._plan.get("state") == "dispatch_claimed"
                    claimed_detail = (
                        f"Windows rejected the shutdown command: {error}"
                        if action == "device"
                        else f"Cinema Paradiso could not complete the lifecycle action: {error}"
                    )
                    self._plan.update({
                        "state": "dispatch_failed" if claimed else "failed",
                        "updated_at": self.clock(),
                        "detail": claimed_detail if claimed else str(error),
                    })
                    self._write(self._plan)
        finally:
            with self._lock:
                self._dispatching = False

    def claim_dispatch(self, plan_id):
        with self._lock:
            if self._plan.get("plan_id") != plan_id:
                raise PowerActionError("Power action plan changed before dispatch")
            if self._plan.get("state") == "dispatch_claimed":
                return dict(self._plan)
            if self._plan.get("state") != "draining":
                raise PowerActionError("Power action is not ready for dispatch")
            self._plan.update({
                "state": "dispatch_claimed",
                "dispatch_claimed_at": self.clock(),
                "updated_at": self.clock(),
                "detail": "The power command was claimed and will never be repeated automatically",
            })
            self._write(self._plan)
            return dict(self._plan)

    def complete_dispatch(self, plan_id):
        with self._lock:
            if self._plan.get("plan_id") != plan_id:
                raise PowerActionError("Power action plan changed before completion")
            if self._plan.get("state") == "completed":
                return dict(self._plan)
            if self._plan.get("state") != "dispatch_claimed":
                raise PowerActionError("Power action was not claimed before completion")
            self._plan.update({
                "state": "completed",
                "completed_at": self.clock(),
                "updated_at": self.clock(),
                "detail": "Power action completed",
            })
            self._write(self._plan)
            return dict(self._plan)

    def cancel(self):
        with self._lock:
            if self._plan.get("state") not in {"armed", "paused", "failed", "dispatch_failed", "dispatch_unknown"}:
                raise PowerActionError("This power action can no longer be cancelled")
            self._plan.update({
                "state": "cancelled",
                "cancelled_at": self.clock(),
                "updated_at": self.clock(),
                "detail": "Power action cancelled",
            })
            self._write(self._plan)
            return self.snapshot()

    def resume(self):
        with self._lock:
            if self._plan.get("state") != "paused":
                raise PowerActionError("There is no paused power action to resume")
            self._plan.update({
                "state": "armed" if self._plan.get("after_download") else "draining",
                "updated_at": self.clock(),
                "detail": "Power action resumed",
            })
            self._write(self._plan)
            if self._plan["state"] == "draining":
                self._start_dispatch_locked()
        self.evaluate()
        return self.snapshot()

    def submissions_blocked(self):
        with self._lock:
            return self._plan.get("state") in {"draining", "dispatch_claimed"}

    def lifecycle_action_active(self):
        with self._lock:
            return self._plan.get("state") in {
                "armed", "draining", "paused", "failed", "dispatch_claimed",
                "dispatch_failed", "dispatch_unknown",
            }
