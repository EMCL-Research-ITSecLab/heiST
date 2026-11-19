import assert from 'node:assert/strict';
import { test } from 'node:test';
import { sortRows } from '../src/lib/sorting.ts';

test('numeric sorting uses magnitude and never mutates the source', () => {
  const source = [10, 2, 100];
  assert.deepEqual(
    sortRows(source, (item) => item),
    [2, 10, 100],
  );
  assert.deepEqual(
    sortRows(source, (item) => item, true),
    [100, 10, 2],
  );
  assert.deepEqual(source, [10, 2, 100]);
});
test('natural names, equal keys and missing values have predictable ordering', () => {
  assert.deepEqual(
    sortRows(['VM 10', 'vm 2'], (item) => item),
    ['vm 2', 'VM 10'],
  );
  for (const descending of [false, true]) {
    assert.deepEqual(
      sortRows([null, 2, undefined, 1], (item) => item, descending),
      descending ? [2, 1, null, undefined] : [1, 2, null, undefined],
    );
  }
  const same = [{ id: 1 }, { id: 2 }];
  assert.deepEqual(
    sortRows(same, () => 'equal'),
    same,
  );
});
