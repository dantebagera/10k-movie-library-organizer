import { X } from 'lucide-react';
import { cx } from '../utils/appUtils.js';
import { getMovieIdentity } from '../utils/libraryUtils.js';

export function LibraryStat({ icon: Icon, label, value, tone, onClick }) {
  const content = <><Icon size={18} /><strong>{value}</strong><span>{label}</span></>;
  if (onClick) return <button type="button" className={cx('library-stat', 'library-stat-action', `tone-${tone}`)} onClick={onClick}>{content}</button>;
  return <article className={cx('library-stat', `tone-${tone}`)}>{content}</article>;
}

export function LibraryRenameModal({ item, onClose, onSubmit }) {
  const identity = getMovieIdentity(item);
  return <div className="modal-backdrop" role="presentation" onClick={onClose}>
    <form className="small-dialog" onSubmit={onSubmit} role="dialog" aria-modal="true" aria-label="Rename file" onClick={(event) => event.stopPropagation()}>
      <div className="dialog-header"><div><p className="screen-kicker">Rename file</p><h2>{item.filename}</h2></div><button type="button" className="inspector-close" onClick={onClose} aria-label="Close rename dialog"><X size={18} /></button></div>
      <label className="dialog-field"><span>Movie title</span><input name="title" defaultValue={identity.title} /></label>
      <label className="dialog-field"><span>Year</span><input name="year" defaultValue={identity.year} inputMode="numeric" /></label>
      <div className="dialog-actions"><button type="button" className="btn btn-secondary" onClick={onClose}>Cancel</button><button type="submit" className="btn btn-primary">Rename</button></div>
    </form>
  </div>;
}

export function ConfirmDialog({
  title,
  body,
  confirmLabel,
  danger,
  acknowledgementLabel = '',
  acknowledged = false,
  onAcknowledgementChange,
  onCancel,
  onConfirm,
}) {
  return <div className="modal-backdrop" role="presentation" onClick={onCancel}>
    <section className="small-dialog" role="dialog" aria-modal="true" aria-label={title} onClick={(event) => event.stopPropagation()}>
      <div className="dialog-header"><div><p className="screen-kicker">Confirm action</p><h2>{title}</h2></div><button type="button" className="inspector-close" onClick={onCancel} aria-label="Close dialog"><X size={18} /></button></div>
      <p className="dialog-body-path">{body}</p>
      {acknowledgementLabel && (
        <label className="dialog-confirmation-check">
          <input type="checkbox" checked={acknowledged} onChange={(event) => onAcknowledgementChange?.(event.target.checked)} />
          <span>{acknowledgementLabel}</span>
        </label>
      )}
      <div className="dialog-actions"><button type="button" className="btn btn-secondary" onClick={onCancel}>Cancel</button><button type="button" className={cx('btn', danger ? 'btn-danger' : 'btn-primary')} disabled={Boolean(acknowledgementLabel) && !acknowledged} onClick={onConfirm}>{confirmLabel}</button></div>
    </section>
  </div>;
}
