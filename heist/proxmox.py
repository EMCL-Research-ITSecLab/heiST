"""Wait for an asynchronous Proxmox worker before dependent configuration."""
import math
import time
from urllib.parse import quote


def wait_for_task(api, node, response, timeout=900, poll_interval=1, *, clock=time.monotonic, sleep=time.sleep):
    upid = response.get('data') if isinstance(response, dict) else None
    if not isinstance(upid, str) or not upid.startswith('UPID:'):
        raise ValueError('Expected a Proxmox task UPID')
    if not math.isfinite(timeout) or not math.isfinite(poll_interval) or timeout <= 0 or poll_interval <= 0:
        raise ValueError('Task timeout and poll interval must be positive')
    endpoint = f'api2/json/nodes/{quote(node, safe="")}/tasks/{quote(upid, safe="")}/status'
    deadline = clock() + timeout
    while True:
        result = api('GET', endpoint)
        status = result.get('data') if isinstance(result, dict) else None
        if not isinstance(status, dict):
            raise RuntimeError('Missing Proxmox task status')
        if status.get('status') == 'stopped':
            if status.get('exitstatus') != 'OK':
                raise RuntimeError('Proxmox task failed: ' + str(status.get('exitstatus', 'missing exit status')))
            return response
        if status.get('status') != 'running':
            raise RuntimeError('Unexpected Proxmox task status')
        remaining = deadline - clock()
        if remaining <= 0:
            raise TimeoutError('Proxmox task did not complete before its deadline')
        sleep(min(poll_interval, remaining))
