function plural(count, singular, pluralForm = `${singular}s`) {
  return count === 1 ? singular : pluralForm;
}

export function deletionPlanSummary(plan) {
  const actions = Array.isArray(plan?.actions) ? plan.actions : [];
  const folderActions = actions.filter((action) => action.target_type === 'folder');
  const fileActions = actions.filter((action) => action.target_type === 'file');
  const sidecarCount = folderActions.reduce((total, action) => total + Number(action.sidecar_count || 0), 0);
  const lines = [];

  if (folderActions.length) {
    lines.push(
      `${folderActions.length} complete movie ${plural(folderActions.length, 'folder')} will move to the Recycle Bin, including ${sidecarCount} ${plural(sidecarCount, 'sidecar file')}.`
    );
  }
  if (fileActions.length) {
    lines.push(
      `${fileActions.length} individual movie ${plural(fileActions.length, 'file')} will move to the Recycle Bin. Their folders will stay because they contain another movie or an unrecognized file.`
    );
  }

  const targets = actions.slice(0, 5).map((action) => action.target);
  if (actions.length > 5) targets.push(`...and ${actions.length - 5} more`);
  return [...lines, ...(targets.length ? ['', ...targets] : [])].join('\n');
}
