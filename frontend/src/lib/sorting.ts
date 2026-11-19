export type SortValue = string | number | null | undefined;

/** Missing values stay last in either direction; numeric values stay numeric. */
export function sortRows<T>(
  items: readonly T[],
  value: (item: T) => SortValue,
  descending = false,
): T[] {
  return [...items].sort((a, b) => {
    const left = value(a),
      right = value(b);
    if (left == null || right == null) return left == null ? (right == null ? 0 : 1) : -1;
    const order =
      typeof left === 'number' && typeof right === 'number'
        ? left - right
        : String(left).localeCompare(String(right), undefined, {
            numeric: true,
            sensitivity: 'base',
          });
    return descending ? -order : order;
  });
}
