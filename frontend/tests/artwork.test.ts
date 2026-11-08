import assert from 'node:assert/strict';
import { test } from 'node:test';
import { achievementIcon, avatarImage } from '../src/lib/artwork.ts';

test('original badge icons remain distinct and API artwork takes precedence', () => {
  const icons = ['🕸️', '🔐', '👁️', '🕵️', '💣', '🧩', '💉', '⚡', '👑'];
  assert.deepEqual(icons.map((_, index) => achievementIcon({ id: index + 1 })), icons);
  assert.equal(achievementIcon({ id: 1, icon: '🐱' }), '🐱');
  assert.equal(achievementIcon({ id: 99 }), '🏆');
});
test('original illustrated fallback preserves selected and uploaded user avatars', () => {
  for (const value of [undefined, '', '/assets/avatars/default-avatar.png', 'https://example.invalid/avatar.png'])
    assert.equal(avatarImage(value), '/assets/avatars/avatar1.png');
  assert.equal(avatarImage('/assets/avatars/avatar2.png'), '/assets/avatars/avatar2.png');
  assert.equal(avatarImage('/media/avatars/uploaded.png'), '/media/avatars/uploaded.png');
});
