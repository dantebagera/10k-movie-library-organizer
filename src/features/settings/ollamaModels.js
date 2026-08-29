export const CUSTOM_OLLAMA_MODEL_VALUE = '__custom_ollama_model__';

function normalizeModels(items, seen) {
  const result = [];
  for (const item of items || []) {
    const model = String(item?.model || '').trim();
    const key = model.toLocaleLowerCase();
    if (!model || seen.has(key)) continue;
    seen.add(key);
    result.push({
      model,
      description: String(item?.description || '').trim(),
      requiredPlan: String(item?.required_plan || '').trim(),
      accessStatus: String(item?.access_status || '').trim()
    });
  }
  return result;
}

export function buildOllamaModelGroups(catalog, configuredModel = '') {
  const seen = new Set();
  const accessScan = catalog?.access_scan || null;
  const cloudSource = accessScan
    ? (catalog?.cloud_models || []).filter((item) => item?.access_status === 'accessible')
    : (catalog?.cloud_models || []);
  const cloud = normalizeModels(cloudSource, seen);
  const local = normalizeModels(catalog?.local_models, seen);
  const currentModel = String(catalog?.configured_model || '').trim();
  const current = currentModel && !seen.has(currentModel.toLocaleLowerCase())
    ? { model: currentModel, description: 'Current model' }
    : null;
  if (current) seen.add(current.model.toLocaleLowerCase());

  const selectedModel = String(configuredModel || '').trim();
  const selected = selectedModel && !seen.has(selectedModel.toLocaleLowerCase())
    ? { model: selectedModel, description: 'Selected model' }
    : null;

  return { cloud, local, current, selected, accessScan };
}
