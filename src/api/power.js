import { fetchJson } from './client.js';

export function fetchPowerStatus() {
  return fetchJson('/api/power/status');
}

export function requestPowerAction(action, afterDownload, closeQbittorrent = false) {
  return fetchJson('/api/power/actions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      action,
      after_download: Boolean(afterDownload),
      close_qbittorrent: Boolean(closeQbittorrent)
    })
  });
}

export function cancelPowerAction() {
  return fetchJson('/api/power/cancel', { method: 'POST' });
}

export function resumePowerAction() {
  return fetchJson('/api/power/resume', { method: 'POST' });
}
