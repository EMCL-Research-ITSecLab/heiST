"""Record intent before infrastructure changes; never replay uncertain effects.

A resource lease covers the complete synchronous operation. After worker death,
the lease is released but the RUNNING receipt remains durable and blocks a new
operation. Only an explicit maintenance recovery may resolve it. This is an
operation journal, not a claim of exactly-once execution by external services.
"""
from datetime import datetime, timezone
import hashlib
import json
import re
import uuid

from heist.files import maintenance_lock, private_directory, write_json


class RecoveryRequired(RuntimeError):
    pass


class Journal:
    def __init__(self, directory):
        self.directory = private_directory(directory)

    def resource(self, scope, identifier):
        if scope not in ('user', 'template', 'pool') or type(identifier) is not int or identifier <= 0:
            raise ValueError('Invalid operation resource')
        return private_directory(self.directory/f'{scope}-{identifier}')

    @staticmethod
    def request_id(value=None):
        if value is None:
            return uuid.uuid4().hex
        if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{32}', value):
            raise ValueError('Invalid operation identifier')
        return value

    def execute(self, scope, identifier, action, payload, function, *, request_id=None):
        request_id = self.request_id(request_id)
        if not isinstance(action, str) or not re.fullmatch('[a-z_]{1,64}', action):
            raise ValueError('Invalid operation action')
        fingerprint = hashlib.sha256(json.dumps({'action': action, 'payload': payload}, sort_keys=True, allow_nan=False).encode()).hexdigest()
        directory = self.resource(scope, identifier)
        with maintenance_lock(directory):
            receipt = directory/(request_id+'.json')
            if receipt.exists():
                previous = json.loads(receipt.read_text())
                if previous['fingerprint'] != fingerprint:
                    raise RecoveryRequired('Operation identifier was already used for different input')
                if previous['state'] == 'SUCCEEDED':
                    return previous['result']
                raise RecoveryRequired('The previous operation requires reconciliation')
            current = directory/'current.json'
            if current.exists():
                previous = json.loads(current.read_text())
                if previous['state'] in ('RUNNING', 'NEEDS_REVIEW'):
                    raise RecoveryRequired('An earlier operation requires reconciliation')
            value = {'schema': 1, 'id': request_id, 'scope': scope, 'resource': identifier,
                     'action': action, 'fingerprint': fingerprint, 'state': 'RUNNING',
                     'started': datetime.now(timezone.utc).isoformat()}
            # Writing intent and the current pointer precedes ALL side effects.
            write_json(receipt, value)
            write_json(current, value)
            try:
                result = function()
                # Keep receipts bounded and serializable before committing success.
                if len(json.dumps(result, allow_nan=False).encode()) > 1024**2:
                    raise ValueError('Operation result exceeds receipt limit')
                value.update(state='SUCCEEDED', result=result)
                write_json(receipt, value)
                write_json(current, value)
                return result
            except BaseException:
                # If disk I/O prevents recording failure, the original RUNNING
                # intent still blocks new work after the process lease is lost.
                value.pop('result', None)
                value['state'] = 'NEEDS_REVIEW'
                write_json(receipt, value)
                write_json(current, value)
                raise

    def inspect(self, scope, identifier):
        directory = self.resource(scope, identifier)
        current = directory/'current.json'
        if not current.exists():
            return None
        # Atomic receipts allow observers to read an active operation without
        # taking its lease. RUNNING with a free lease is explicitly uncertain.
        value = json.loads(current.read_text())
        if value['state'] == 'RUNNING':
            try:
                with maintenance_lock(directory):
                    value = json.loads(current.read_text())
                    if value['state'] == 'RUNNING':
                        value['state'] = 'NEEDS_REVIEW'
            except BlockingIOError:
                pass
        return {key: value[key] for key in ('id', 'scope', 'resource', 'action', 'state', 'started')}

    def resolve(self, scope, identifier, operation_id, reason):
        """Local maintenance action after independent resource reconciliation."""
        self.request_id(operation_id)
        if not isinstance(reason, str) or not 10 <= len(reason.strip()) <= 500:
            raise ValueError('Record the independent recovery checks in 10..500 characters')
        directory = self.resource(scope, identifier)
        with maintenance_lock(directory):
            current = directory/'current.json'
            value = json.loads(current.read_text())
            if value['id'] != operation_id or value['state'] not in ('RUNNING', 'NEEDS_REVIEW'):
                raise RecoveryRequired('The current unresolved operation does not match')
            value.update(state='RESOLVED', resolution=reason.strip(), resolved_at=datetime.now(timezone.utc).isoformat())
            write_json(directory/(operation_id+'.json'), value)
            write_json(current, value)
