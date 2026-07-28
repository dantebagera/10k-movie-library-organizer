import { RefreshCcw } from 'lucide-react';

export default function WorkspacePathBar({
  history = [],
  currentLabel,
  resetLabel,
  ariaLabel = 'Navigation path',
  onBack,
  onReset,
  onCrumb
}) {
  if (!history.length && !currentLabel) return null;
  return (
    <div className="workspace-path-bar" aria-label={ariaLabel}>
      <button type="button" className="mini-action" onClick={onBack} disabled={!history.length}>
        Back
      </button>
      <div className="workspace-path-crumbs">
        {history.map((item, index) => (
          <button type="button" key={`${item.label}-${index}`} onClick={() => onCrumb(index)}>
            {item.label}
          </button>
        ))}
        {currentLabel && <span>{currentLabel}</span>}
      </div>
      <button type="button" className="mini-action" onClick={onReset}>
        <RefreshCcw size={13} /> {resetLabel}
      </button>
    </div>
  );
}
