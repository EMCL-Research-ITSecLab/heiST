import { row, rows, text } from './data.ts';

export function healthTone(state: string) {
  if (state === 'ok') return 'active';
  if (['failed', 'stale', 'unavailable'].includes(state)) return 'critical';
  return 'warning';
}

export function monitoringView(value: unknown) {
  const data = row(value), status = text(data.status, 'not configured');
  const order = ['failed', 'warning', 'unknown', 'ok'];
  const checks = rows(data.checks).sort((a, b) => order.indexOf(text(a.state)) - order.indexOf(text(b.state)));
  return { status, checks, checkedAt: data.checked_at,
    failed: checks.filter(check => check.state === 'failed').length,
    unverified: checks.filter(check => check.state === 'unknown').length,
    historical: ['stale', 'unavailable'].includes(status) };
}
