export type Row = Record<string, unknown>;
export const row = (value: unknown): Row => value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Row : {};
export const rows = (value: unknown): Row[] => Array.isArray(value) ? value.map(row) : [];
export const text = (value: unknown, fallback = ''): string => typeof value === 'string' || typeof value === 'number' ? String(value) : fallback;
export const number = (value: unknown): number => Number.isFinite(Number(value)) ? Number(value) : 0;
export const truth = (value: unknown): boolean => value === true || value === 1 || value === '1' || value === 'true' || value === 't';
export const payload = (value: Row): Row => value.data && typeof value.data === 'object' ? row(value.data) : value;
export const date = (value: unknown): string => {
    const parsed = new Date(text(value));
    return Number.isNaN(parsed.getTime()) ? '—' : parsed.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
};
export const duration = (value: unknown): string => {
    const seconds = Math.max(0, Math.floor(number(value)));
    return [Math.floor(seconds / 3600), Math.floor(seconds / 60) % 60, seconds % 60].map(n => String(n).padStart(2, '0')).join(':');
};
export function safeNext(value: string | null): string {
    if (!value || !value.startsWith('/') || value.startsWith('//') || /[\\\u0000-\u001f]/.test(value))
        return '/dashboard';
    const url = new URL(value, 'https://heist.invalid');
    return url.origin === 'https://heist.invalid' && !['/login', '/signup'].includes(url.pathname) ? url.pathname + url.search : '/dashboard';
}
export function image(value: unknown): string {
    const path = text(value);
    return path.startsWith('/') && !path.startsWith('//') && !/[\\\u0000-\u001f]/.test(path) ? path : '/assets/images/ctf-default.png';
}
export function external(value: unknown): string | undefined {
    try {
        const url = new URL(text(value));
        return ['https:', 'http:'].includes(url.protocol) ? url.href : undefined;
    }
    catch {
        return undefined;
    }
}
export const categories = ['crypto', 'forensics', 'pwn', 'reverse', 'web', 'misc'];
export const difficulties = ['easy', 'medium', 'hard'];
