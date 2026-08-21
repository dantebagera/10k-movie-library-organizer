import { formatCount } from '../utils/appUtils.js';

export default function Pagination({
  total,
  page,
  totalPages,
  pageStart,
  pageEnd,
  summary = '',
  hasPrevious,
  hasNext,
  ariaLabel = 'Library pagination',
  onPageChange
}) {
  const knownTotal = Number.isFinite(Number(totalPages)) && totalPages != null;
  const canPrevious = hasPrevious ?? page > 1;
  const canNext = hasNext ?? (knownTotal && page < totalPages);
  if (!canPrevious && !canNext && (!knownTotal || totalPages <= 1)) return null;
  return (
    <nav className="library-pagination" aria-label={ariaLabel}>
      <button type="button" className="btn btn-secondary" onClick={() => onPageChange(page - 1)} disabled={!canPrevious}>Previous</button>
      <div className="library-page-status">
        <strong>{knownTotal ? `Page ${formatCount(page)} of ${formatCount(totalPages)}` : `Page ${formatCount(page)}`}</strong>
        <span>{summary || (total == null
          ? `Showing ${formatCount(pageStart + 1)}-${formatCount(pageEnd)}`
          : `Showing ${formatCount(pageStart + 1)}-${formatCount(pageEnd)} of ${formatCount(total)}`)}</span>
      </div>
      <button type="button" className="btn btn-secondary" onClick={() => onPageChange(page + 1)} disabled={!canNext}>Next</button>
    </nav>
  );
}
