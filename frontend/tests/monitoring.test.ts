import assert from 'node:assert/strict';
import { test } from 'node:test';
import { healthTone, monitoringView } from '../src/lib/monitoring.ts';

test('missing and stale receipts cannot be shown as current healthy monitoring', () => {
  assert.equal(monitoringView(undefined).status, 'not configured');
  const view = monitoringView({status: 'stale', checks: [{id:'sensor', state:'ok'}]});
  assert.equal(view.historical, true);
  assert.equal(healthTone(view.status), 'critical');
  assert.equal(healthTone('unknown'), 'warning');
});

test('failures are shown before successful checks and unverified coverage is counted', () => {
  const checks = [{id:'working',state:'ok'}, {id:'coverage',state:'unknown'}, {id:'dmz',state:'failed'}];
  const view = monitoringView({status:'failed',checks});
  assert.deepEqual(view.checks.map(check => check.id), ['dmz','coverage','working']);
  assert.equal(view.failed,1);
  assert.equal(view.unverified,1);
  assert.equal(checks[0].id,'working');
});
