import { formatCount } from '../utils/appUtils.js';

export default function Pagination({
  total,
  page,
  totalPages,
  pageStart,
  pageEnd,
  summary = '',
  ariaLabel = 'Library pagination',
  onPageChange
}) {
  if (totalPages <= 1 || total <= 0) return null;
  return (
    <nav className="library-pagination" aria-label={ariaLabel}>
      <button type="button" className="btn btn-secondary" onClick={() => onPageChange(page - 1)} disabled={page <= 1}>Previous</button>
      <div className="library-page-status">
        <strong>Page {formatCount(page)} of {formatCount(totalPages)}</strong>
        <span>{summary || `Showing ${formatCount(pageStart + 1)}-${formatCount(pageEnd)} of ${formatCount(total)}`}</span>
      </div>
      <button type="button" className="btn btn-secondary" onClick={() => onPageChange(page + 1)} disabled={page >= totalPages}>Next</button>
    </nav>
  );
}
