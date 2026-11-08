import { achievementIcon } from '../lib/artwork.ts';
import type { Row } from '../lib/data.ts';

export function AchievementIcon({ badge, compact = false }: { badge: Row; compact?: boolean }) {
  return <span className={'achievement-glyph' + (compact ? ' compact' : '')} aria-hidden="true">
    {achievementIcon(badge)}
  </span>;
}
