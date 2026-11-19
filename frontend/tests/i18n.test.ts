import assert from 'node:assert/strict';
import { test } from 'node:test';
import fs from 'node:fs';
import { translate } from '../src/lib/translation.ts';
import { german } from '../src/lib/messages/de.ts';
import { english, type MessageKey } from '../src/lib/messages/en.ts';
import { optionLabel, noticeMessage } from '../src/lib/localizedValues.ts';

test('semantic keys select English and German text with safe interpolation', () => {
  assert.equal(translate('de', 'common.actions.edit'), 'Bearbeiten');
  assert.equal(translate('en', 'common.actions.edit'), 'Edit');
  assert.equal(translate('de', 'constructor' as MessageKey), 'constructor');
  assert.equal(
    translate('de', 'users.confirmUsername', { username: '<student>$&' }),
    'Zur Bestätigung <student>$& eingeben',
  );
  assert.equal(
    translate('en', 'pools.manualCapacityEstimate', { count: 0, ram: 0 }),
    '0 copies require about 0 GiB of configured guest RAM.',
  );
});
test('English and German catalogs have identical semantic keys and placeholders', () => {
  assert.deepEqual(Object.keys(english).sort(), Object.keys(german).sort());
  for (const key of Object.keys(english) as MessageKey[]) {
    assert.match(key, /^[a-z][a-zA-Z0-9]*(\.[a-z][a-zA-Z0-9]*)+$/);
    assert.deepEqual(
      english[key].match(/\{[a-zA-Z_]+\}/g)?.sort() ?? [],
      german[key].match(/\{[a-zA-Z_]+\}/g)?.sort() ?? [],
      key,
    );
  }
});
test('domain values and unknown server or authored content are not translation keys', () => {
  assert.equal(optionLabel('de', 'READY'), 'Bereit');
  assert.equal(optionLabel('en', 'READY'), 'READY');
  assert.equal(
    optionLabel('de', 'Student-authored exercise title'),
    'Student-authored exercise title',
  );
  assert.equal(noticeMessage('de', 'Incorrect flag'), 'Falsche Flag');
  assert.equal(
    noticeMessage('de', 'Opaque infrastructure evidence'),
    'Opaque infrastructure evidence',
  );
});
test('literal translation calls use catalog keys rather than English sentences', () => {
  const root = new URL('../src/', import.meta.url),
    missing = new Set<string>();
  let checked = 0;
  for (const file of fs
    .readdirSync(root, { recursive: true })
    .filter((file) => file.endsWith('.tsx'))) {
    const source = fs.readFileSync(new URL(file, root), 'utf8');
    for (const match of source.matchAll(/\bt\(("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')/g)) {
      const literal = match[1];
      const message = (
        literal[0] === '"' ? JSON.parse(literal) : literal.slice(1, -1).replace(/\\(['\\])/g, '$1')
      ).trim();
      if (!/[a-zA-Z]/.test(message)) continue;
      checked++;
      if (!Object.hasOwn(english, message)) missing.add(message);
    }
  }
  assert.ok(checked > 500);
  assert.deepEqual([...missing], []);
});
