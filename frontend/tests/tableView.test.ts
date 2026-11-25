import assert from 'node:assert/strict';
import { test } from 'node:test';
import { selectTableRows } from '../src/lib/tableView.ts';

const source = [
  { name: 'VM 10', state: 'ready', size: 10 },
  { name: 'VM 2', state: 'failed', size: 2 },
  { name: 'VM 1', state: 'ready', size: 1 },
];
const columns = [
  { key: 'name', label: 'Name', value: (item: (typeof source)[number]) => item.name },
  { key: 'state', label: 'State', value: (item: (typeof source)[number]) => item.state },
  { key: 'size', label: 'Size', value: (item: (typeof source)[number]) => item.size },
];

test('table search, exact filter, and ordering compose without changing source', () => {
  assert.deepEqual(
    selectTableRows(source, columns, {}).map((item) => item.name),
    ['VM 10', 'VM 2', 'VM 1'],
  );
  assert.deepEqual(
    selectTableRows(source, columns, {
      search: 'VM',
      filterColumn: 'state',
      filterValue: 'ready',
      sortKey: 'size',
      descending: true,
    }).map((item) => item.name),
    ['VM 10', 'VM 1'],
  );
  assert.deepEqual(
    source.map((item) => item.name),
    ['VM 10', 'VM 2', 'VM 1'],
  );
  assert.deepEqual(
    selectTableRows(source, columns, { sortKey: 'name' }).map((item) => item.name),
    ['VM 1', 'VM 2', 'VM 10'],
  );
});
