import assert from 'node:assert/strict';
import test from 'node:test';

import {
  buildOllamaModelGroups,
  CUSTOM_OLLAMA_MODEL_VALUE
} from '../src/features/settings/ollamaModels.js';

test('Ollama model groups preserve free cloud, local, and unknown current models', () => {
  const groups = buildOllamaModelGroups({
    configured_model: 'gemma4:31b-cloud',
    free_cloud_models: [
      { model: 'minimax-m3:cloud', description: 'Free cloud' },
      { model: 'MINIMAX-M3:CLOUD', description: 'Duplicate' }
    ],
    local_models: [
      { model: 'gemma3:12b', description: '12B' },
      { model: 'minimax-m3:cloud', description: 'Duplicate across groups' }
    ]
  });

  assert.deepEqual(groups.freeCloud, [
    { model: 'minimax-m3:cloud', description: 'Free cloud' }
  ]);
  assert.deepEqual(groups.local, [
    { model: 'gemma3:12b', description: '12B' }
  ]);
  assert.deepEqual(groups.current, {
    model: 'gemma4:31b-cloud',
    description: 'Current model'
  });
});

test('Ollama model groups do not duplicate a configured discovered model', () => {
  const groups = buildOllamaModelGroups({
    configured_model: 'minimax-m3:cloud',
    free_cloud_models: [{ model: 'minimax-m3:cloud' }],
    local_models: []
  });

  assert.equal(groups.current, null);
  assert.equal(groups.freeCloud[0].model, 'minimax-m3:cloud');
  assert.equal(CUSTOM_OLLAMA_MODEL_VALUE, '__custom_ollama_model__');
});

test('Ollama model groups keep the saved model available while another choice is unsaved', () => {
  const groups = buildOllamaModelGroups({
    configured_model: 'gemma4:31b-cloud',
    free_cloud_models: [{ model: 'minimax-m3:cloud' }],
    local_models: []
  }, 'minimax-m3:cloud');

  assert.equal(groups.current.model, 'gemma4:31b-cloud');
  assert.equal(groups.freeCloud[0].model, 'minimax-m3:cloud');
  assert.equal(groups.selected, null);
});

test('Ollama model groups expose a verified exact model before it is saved', () => {
  const groups = buildOllamaModelGroups({
    configured_model: 'minimax-m3:cloud',
    free_cloud_models: [{ model: 'minimax-m3:cloud' }],
    local_models: []
  }, 'gemma4:31b-cloud');

  assert.equal(groups.current, null);
  assert.deepEqual(groups.selected, {
    model: 'gemma4:31b-cloud',
    description: 'Selected model'
  });
});
