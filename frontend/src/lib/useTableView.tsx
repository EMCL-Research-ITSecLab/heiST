import { useState } from 'react';
import { Field, Select } from '../components/ui.tsx';
import { useI18n } from './i18n.tsx';
import { selectTableRows, type TableColumn } from './tableView.ts';

export function useTableView<T>(
  source: readonly T[],
  columns: readonly TableColumn<T>[],
  initialSort = '',
  options: { search?: boolean; loadedRowsOnly?: boolean } = {},
) {
  const { t } = useI18n();
  const [search, setSearch] = useState('');
  const [filterColumn, setFilterColumn] = useState('');
  const [filterValue, setFilterValue] = useState('');
  const [sort, setSort] = useState({ key: initialSort, descending: false });
  const selected = columns.find((column) => column.key === filterColumn);
  const values = selected
    ? [...new Set(source.map((item) => String(selected.value(item) ?? '')).filter(Boolean))].sort(
        (a, b) => a.localeCompare(b, undefined, { numeric: true, sensitivity: 'base' }),
      )
    : [];
  const items = selectTableRows(source, columns, {
    search,
    filterColumn,
    filterValue,
    sortKey: sort.key,
    descending: sort.descending,
  });
  return {
    items,
    header: (key: string) => ({
      label: columns.find((column) => column.key === key)?.label ?? key,
      active: sort.key === key,
      descending: sort.descending,
      onSort: () =>
        setSort((previous) => ({
          key,
          descending: previous.key === key && !previous.descending,
        })),
    }),
    controls: (
      <div className="filter-bar table-controls">
        {options.search !== false && (
          <Field
            label={t('tables.search')}
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        )}
        <Select
          label={t('tables.filterBy')}
          value={filterColumn}
          options={[
            ['', t('tables.anyColumn')] as [string, string],
            ...columns.map((column): [string, string] => [column.key, column.label]),
          ]}
          onChange={(event) => {
            setFilterColumn(event.target.value);
            setFilterValue('');
          }}
        />
        {selected && (
          <Select
            label={t('tables.value')}
            value={filterValue}
            options={[
              ['', t('tables.allValues')] as [string, string],
              ...values.map((value): [string, string] => [value, value]),
            ]}
            onChange={(event) => setFilterValue(event.target.value)}
          />
        )}
        {(search || filterColumn) && (
          <button
            type="button"
            className="secondary"
            onClick={() => {
              setSearch('');
              setFilterColumn('');
              setFilterValue('');
            }}
          >
            {t('tables.clear')}
          </button>
        )}
        {options.loadedRowsOnly && (
          <p className="muted table-scope-note">{t('tables.loadedRowsOnly')}</p>
        )}
        <p className="muted table-scope-note" role="status">
          {t('tables.results', { shown: items.length, total: source.length })}
        </p>
      </div>
    ),
  };
}
