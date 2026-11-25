import { sortRows, type SortValue } from './sorting.ts';

export type TableColumn<T> = {
  key: string;
  label: string;
  value: (item: T) => SortValue;
};

export function selectTableRows<T>(
  source: readonly T[],
  columns: readonly TableColumn<T>[],
  options: {
    search?: string;
    filterColumn?: string;
    filterValue?: string;
    sortKey?: string;
    descending?: boolean;
  },
) {
  const search = options.search?.toLocaleLowerCase() ?? '';
  const filter = columns.find((column) => column.key === options.filterColumn);
  const matching = source.filter(
    (item) =>
      (!search ||
        columns.some((column) =>
          String(column.value(item) ?? '')
            .toLocaleLowerCase()
            .includes(search),
        )) &&
      (!filter || !options.filterValue || String(filter.value(item) ?? '') === options.filterValue),
  );
  const sort = columns.find((column) => column.key === options.sortKey);
  return sort ? sortRows(matching, sort.value, options.descending) : [...matching];
}
