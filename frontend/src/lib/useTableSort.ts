import {useState} from 'react';
import {sortRows, type SortValue} from './sorting.ts';

export function useTableSort<T>(columns: Record<string, (item: T) => SortValue>, initial: string) {
  const [sort, setSort] = useState({key: initial, descending: false});
  return {
    apply: (items: readonly T[]) => sortRows(items, columns[sort.key], sort.descending),
    header: (key: string, label: string) => ({label, active: sort.key === key, descending: sort.descending,
      onSort: () => setSort(previous => ({key, descending: previous.key === key && !previous.descending}))}),
  };
}
