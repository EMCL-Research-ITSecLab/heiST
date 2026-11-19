type Props = { label: string; active: boolean; descending: boolean; onSort: () => void };

export function SortableHeader({ label, active, descending, onSort }: Props) {
  return (
    <th scope="col" aria-sort={active ? (descending ? 'descending' : 'ascending') : 'none'}>
      <button type="button" className="table-sort" onClick={onSort}>
        {label} <span aria-hidden="true">{active ? (descending ? '↓' : '↑') : '↕'}</span>
      </button>
    </th>
  );
}
