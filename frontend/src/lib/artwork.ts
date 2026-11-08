import { image, text } from './data.ts';

// Original badge artwork from main's database seed. The API's icon is preferred.
const originalIcons: Record<string, string> = {
  '1': '🕸️', '2': '🔐', '3': '👁️', '4': '🕵️', '5': '💣',
  '6': '🧩', '7': '💉', '8': '⚡', '9': '👑',
};
export function achievementIcon(badge: { id?: unknown; icon?: unknown }): string {
  const icon = text(badge.icon).trim();
  return icon && icon.length <= 32 ? icon : originalIcons[text(badge.id)] ?? '🏆';
}
export function avatarImage(value: unknown): string {
  const path = image(value);
  return path === '/assets/images/ctf-default.png' || path === '/assets/avatars/default-avatar.png'
    ? '/assets/avatars/avatar1.png'
    : path;
}
