import assert from 'node:assert/strict';
import test from 'node:test';

import {
  buildOllamaModelGroups,
  CUSTOM_OLLAMA_MODEL_VALUE
} from '../src/features/settings/ollamaModels.js';

test('Ollama model groups preserve cloud metadata, local models, and unknown current models', () => {
  const groups = buildOllamaModelGroups({
    configured_model: 'gemma4:31b-cloud',
    cloud_models: [
      { model: 'minimax-m3:cloud', description: 'Free cloud', required_plan: 'free' },
      { model: 'MINIMAX-M3:CLOUD', description: 'Duplicate' }
    ],
    local_models: [
      { model: 'gemma3:12b', description: '12B' },
      { model: 'minimax-m3:cloud', description: 'Duplicate across groups' }
    ],
    access_scan: null
  });

  assert.deepEqual(groups.cloud, [{
    model: 'minimax-m3:cloud',
    description: 'Free cloud',
    requiredPlan: 'free',
    accessStatus: ''
  }]);
  assert.deepEqual(groups.local, [{
    model: 'gemma3:12b',
    description: '12B',
    requiredPlan: '',
    accessStatus: ''
  }]);
  assert.deepEqual(groups.current, {
    model: 'gemma4:31b-cloud',
    description: 'Current model'
  });
});

test('Ollama model groups show only accessible cloud models after a scan', () => {
  const groups = buildOllamaModelGroups({
    configured_model: 'minimax-m3:cloud',
    cloud_models: [
      { model: 'minimax-m3:cloud', access_status: 'accessible', required_plan: 'free' },
      { model: 'glm-5.2:cloud', access_status: 'blocked', required_plan: 'pro' },
      { model: 'unknown-model:cloud', access_status: 'unknown' }
    ],
    local_models: [],
    access_scan: { catalog_count: 3, accessible_count: 1, blocked_count: 1, unknown_count: 1 }
  });

  assert.deepEqual(groups.cloud.map((item) => item.model), ['minimax-m3:cloud']);
  assert.equal(groups.current, null);
  assert.equal(groups.accessScan.accessible_count, 1);
  assert.equal(CUSTOM_OLLAMA_MODEL_VALUE, '__custom_ollama_model__');
});

test('Ollama model groups keep the saved model available while another choice is unsaved', () => {
  const groups = buildOllamaModelGroups({
    configured_model: 'gemma4:31b-cloud',
    cloud_models: [{ model: 'minimax-m3:cloud' }],
    local_models: [],
    access_scan: null
  }, 'minimax-m3:cloud');

  assert.equal(groups.current.model, 'gemma4:31b-cloud');
  assert.equal(groups.cloud[0].model, 'minimax-m3:cloud');
  assert.equal(groups.selected, null);
});

test('Ollama model groups expose a verified exact model before it is saved', () => {
  const groups = buildOllamaModelGroups({
    configured_model: 'minimax-m3:cloud',
    cloud_models: [{ model: 'minimax-m3:cloud' }],
    local_models: [],
    access_scan: null
  }, 'gemma4:31b-cloud');

  assert.equal(groups.current, null);
  assert.deepEqual(groups.selected, {
    model: 'gemma4:31b-cloud',
    description: 'Selected model'
  });
});
