export const IPTV_AUTO_SYNC_MAX_AGE_MS = 24 * 60 * 60 * 1000;

export function shouldAutoSyncIPTVCatalog(status, now = Date.now(), maxAgeMs = IPTV_AUTO_SYNC_MAX_AGE_MS) {
  if (!status?.configured || status?.sync?.state === 'running') return false;

  const lastSyncSeconds = Number(status.last_sync || 0);
  if (!Number.isFinite(lastSyncSeconds) || lastSyncSeconds <= 0) return true;

  return now - (lastSyncSeconds * 1000) >= maxAgeMs;
}
