import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { countGridTemplateColumns, fullRowPageSize } from '../utils/cardGrid.js';

export default function useCardGridMetrics({
  target,
  min = 1,
  max = Number.POSITIVE_INFINITY,
  bias = 'lower'
}) {
  const cleanupRef = useRef(() => {});
  const [columns, setColumns] = useState(1);
  const [measured, setMeasured] = useState(false);

  const gridRef = useCallback((node) => {
    cleanupRef.current();
    cleanupRef.current = () => {};
    if (!node) return;

    const view = node.ownerDocument?.defaultView;
    const measure = () => {
      if (!view || node.getBoundingClientRect().width <= 0) return;
      const nextColumns = countGridTemplateColumns(
        view.getComputedStyle(node).gridTemplateColumns
      );
      if (nextColumns > 0) {
        setColumns((current) => current === nextColumns ? current : nextColumns);
        setMeasured(true);
      }
    };

    measure();
    if (typeof view?.ResizeObserver === 'function') {
      const observer = new view.ResizeObserver(measure);
      observer.observe(node);
      cleanupRef.current = () => observer.disconnect();
      return;
    }

    view?.addEventListener('resize', measure);
    cleanupRef.current = () => view?.removeEventListener('resize', measure);
  }, []);

  useEffect(() => () => cleanupRef.current(), []);

  const pageSize = useMemo(() => fullRowPageSize(target, columns, {
    min,
    max,
    bias
  }), [bias, columns, max, min, target]);

  return { columns, gridRef, measured, pageSize };
}
