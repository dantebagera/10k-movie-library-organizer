import { cx } from '../utils/appUtils.js';

export default function ExperimentalBadge({ className = '' }) {
  return (
    <span className={cx('experimental-badge', className)} aria-label="Experimental">
      <span className="experimental-badge-label">Experimental</span>
      <span className="experimental-badge-short" aria-hidden="true">X</span>
    </span>
  );
}
