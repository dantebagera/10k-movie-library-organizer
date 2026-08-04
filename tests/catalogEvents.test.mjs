import assert from 'node:assert/strict';
import test from 'node:test';

const dispatched = [];
class FakeSource {
  constructor(url) { this.url = url; this.listeners = new Map(); FakeSource.instance = this; }
  addEventListener(name, handler) { this.listeners.set(name, handler); }
  emit(name, payload) { this.listeners.get(name)?.({ data: JSON.stringify(payload) }); }
  close() { this.closed = true; }
}

globalThis.CustomEvent = class CustomEvent { constructor(type, options) { this.type = type; this.detail = options.detail; } };
globalThis.window = {
  EventSource: FakeSource,
  dispatchEvent(event) { dispatched.push(event); }
};

const { CATALOG_READY_EVENT, resetCatalogEventsForTests, startCatalogEvents } = await import('../src/api/catalogEvents.js');

test('one catalog EventSource ignores duplicate generations and emits authoritative refresh signals', () => {
  resetCatalogEventsForTests();
  dispatched.length = 0;
  const stop = startCatalogEvents();
  assert.equal(FakeSource.instance.url, '/api/catalog/events');
  FakeSource.instance.emit('catalog-ready', { type: 'catalog-ready', generation: 4 });
  FakeSource.instance.emit('catalog-ready', { type: 'catalog-ready', generation: 4 });
  FakeSource.instance.emit('catalog-ready', { type: 'catalog-ready', generation: 3 });
  const ready = dispatched.filter((event) => event.type === CATALOG_READY_EVENT);
  assert.equal(ready.length, 1);
  assert.equal(ready[0].detail.generation, 4);
  stop();
  assert.equal(FakeSource.instance.closed, true);
});
