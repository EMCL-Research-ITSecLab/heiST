"""Durable Proxmox task identities and explicit operator reconciliation.

The intent is journalled before POST. An uncertain submission is never retried
without reconciling its UPID; known failed restores require explicit permission.
"""
import hashlib
import json
import os
import time
from urllib.parse import unquote

from heist.proxmox import wait_for_task


class Tasks:
    def __init__(self, node, request, timeout=7200):
        self.node, self.request, self.timeout = node, request, timeout

    def _api(self, method, path):
        return {'data': self.request(method, unquote(path.removeprefix('api2/json')), None)}

    def status(self, upid):
        if not upid.startswith('UPID:' + self.node + ':') or '/' in upid:
            raise ValueError('Task identity must belong to the configured node')
        return self.request('GET', '/nodes/' + self.node + '/tasks/' + upid + '/status', None)

    def reconcile(self, transaction, key, fingerprint, *, upid=None, retry=False):
        if transaction.data.get('committed') or transaction.data.get('recovery_committed'):
            raise RuntimeError('Task reconciliation is forbidden after writers may resume')
        jobs = transaction.data.get('tasks', {})
        job = jobs[key]
        if job['request_sha256'] != fingerprint:
            raise ValueError('Confirm the exact journalled request digest')
        if retry:
            if not key.startswith('restore-') or not job.get('upid'):
                raise ValueError('Only a known failed restore can be explicitly retried')
            status = self.status(job['upid'])
            if status.get('status') != 'stopped' or status.get('exitstatus') in (None, 'OK'):
                raise RuntimeError('Only a stopped, failed restore can be retried')
            job.setdefault('attempts', []).append({'upid': job['upid'], 'exitstatus': status['exitstatus']})
            job.update(upid=None, retry_authorized=True, complete=False)
        else:
            if job.get('upid') or job.get('retry_authorized'):
                raise ValueError('Only an uncertain submission can adopt a task identity')
            status = self.status(upid)
            kind = 'qmrestore' if key.startswith('restore-') else 'vzdump'
            if status.get('type') != kind:
                raise ValueError('Task type does not match the submitted operation')
            if abs(int(status.get('starttime', 0)) - job['submitted_at']) > 10:
                raise ValueError('Task time does not match this submission')
            if str(status.get('id')) != str(job['arguments']['vmid']):
                raise ValueError('Task belongs to another VM')
            job['upid'] = upid
        job.setdefault('reconciliations', []).append({'at': time.time(), 'uid': os.geteuid(),
                                                      'retry': retry, 'upid': upid})
        transaction.save(tasks=jobs)

    def run(self, transaction, key, path, arguments):
        jobs = dict(transaction.data.get('tasks', {}))
        fingerprint = hashlib.sha256(json.dumps([path, arguments], sort_keys=True).encode()).hexdigest()
        if key in jobs:
            job = jobs[key]
            if job['request_sha256'] != fingerprint:
                raise RuntimeError('Recovery task parameters changed')
            if not job.get('upid') and not job.get('retry_authorized'):
                raise RuntimeError('Task submission outcome is unknown; inspect the node log and adopt its UPID: ' + key)
        else:
            job = {'request_sha256': fingerprint, 'path': path, 'arguments': arguments,
                   'upid': None, 'submitted_at': time.time()}
            jobs[key] = job
            transaction.save(tasks=jobs)
        if not job.get('upid'):
            job.update(retry_authorized=False, submitted_at=time.time())
            transaction.save(tasks=jobs)
            response = self.request('POST', path, arguments)
            if not isinstance(response, str) or not response.startswith('UPID:') or '/' in response:
                raise RuntimeError('Proxmox did not return a valid task identity')
            job['upid'] = response
            transaction.save(tasks=jobs)
        wait_for_task(self._api, self.node, {'data': job['upid']}, timeout=self.timeout, poll_interval=2)
        job['complete'] = True
        transaction.save(tasks=jobs)
        return job['upid']

    def settle(self, transaction):
        for key, job in transaction.data.get('tasks', {}).items():
            if job.get('retry_authorized'):
                continue
            if not job.get('upid'):
                raise RuntimeError('Unknown Proxmox task submission; adopt the verified UPID before recovery: ' + key)
            deadline = time.monotonic() + self.timeout
            while True:
                result = self.status(job['upid'])
                if result.get('status') == 'stopped':
                    break
                if result.get('status') != 'running':
                    raise RuntimeError('Unknown Proxmox task status')
                if time.monotonic() >= deadline:
                    raise TimeoutError('Existing Proxmox task has not settled')
                time.sleep(2)
