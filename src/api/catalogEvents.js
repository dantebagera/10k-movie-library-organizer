import { observeCatalogGeneration } from './library.js';

export const CATALOG_READY_EVENT = 'cp-catalog-ready';
export const CATALOG_EVENT_STATUS = 'cp-catalog-event-status';

let source = null;
let highestGeneration = 0;

function dispatch(name, detail) {
  if (typeof window !== 'undefined') window.dispatchEvent(new CustomEvent(name, { detail }));
}

function accept(payload) {
  const generation = Number(payload?.generation || 0);
  if (!Number.isFinite(generation) || generation < highestGeneration) return;
  if (payload.type === 'catalog-ready' && generation === highestGeneration) return;
  highestGeneration = Math.max(highestGeneration, generation);
  observeCatalogGeneration(generation);
  dispatch(CATALOG_READY_EVENT, payload);
}

export function startCatalogEvents() {
  if (source || typeof window === 'undefined' || typeof window.EventSource !== 'function') return () => {};
  source = new window.EventSource('/api/catalog/events');
  source.addEventListener('catalog-ready', (event) => {
    try { accept(JSON.parse(event.data)); } catch { /* malformed notifications are ignored */ }
  });
  source.addEventListener('catalog-sync', (event) => {
    try { accept(JSON.parse(event.data)); } catch { /* malformed notifications are ignored */ }
  });
  source.onopen = () => dispatch(CATALOG_EVENT_STATUS, { connected: true });
  source.onerror = () => dispatch(CATALOG_EVENT_STATUS, { connected: false });
  return () => {
    source?.close();
    source = null;
  };
}

export function resetCatalogEventsForTests() {
  source?.close();
  source = null;
  highestGeneration = 0;
}
