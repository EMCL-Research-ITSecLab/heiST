"""A persisted state machine. Adapters own host/VM effects; this owns recovery policy."""
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from typing import Protocol
import traceback
import uuid

from heist.files import maintenance_lock, private_directory, write_file, write_json
from .manifest import Plan


class Operations(Protocol):
    def preflight(self, plan: Plan): ...
    def quiesce(self, transaction): ...
    def checkpoint(self, transaction): ...
    def deploy(self, transaction): ...
    def migrate(self, transaction): ...
    def verify(self, transaction, *, target: bool): ...
    def restore(self, transaction, *, checkpoint=None): ...
    def abort_before_deploy(self, transaction): ...
    def finish(self, transaction): ...


class Transaction:
    def __init__(self, path, data):
        self.path, self.data = Path(path), data

    @property
    def plan(self):
        return Plan.from_dict(self.data['plan'])

    def save(self, phase=None, **values):
        self.data.update(values)
        if phase is not None:
            logging.getLogger(__name__).info('%s: %s', self.path.name, phase)
            self.data['phase'] = phase
            self.data.setdefault('events', []).append({'phase': phase,
                'at': datetime.now(timezone.utc).isoformat()})
        write_json(self.path / 'transaction.json', self.data)

    def failure(self, error):
        reports = list(self.data.get('failures', []))
        name = 'failure-' + str(len(reports) + 1) + '.log'
        details = traceback.format_exc()
        stderr = getattr(error, 'stderr', None)
        if stderr:
            details += '\nCaptured stderr:\n' + (stderr.decode(errors='replace') if isinstance(stderr, bytes) else str(stderr))
        write_file(self.path/name, details)
        reports.append({'phase': self.data.get('phase'), 'type': type(error).__name__, 'report': name})
        self.save(failures=reports)
        logging.getLogger(__name__).error('%s: %s failed (%s); private diagnostics: %s',
            self.path.name, self.data.get('phase'), type(error).__name__, self.path/name)

    @classmethod
    def load(cls, path):
        return cls(path, json.loads((Path(path) / 'transaction.json').read_text()))


class Controller:
    def __init__(self, state_directory, operations):
        self.directory, self.operations = Path(state_directory), operations

    def _new(self, plan, kind='upgrade'):
        active = self.directory / 'active.json'
        if active.exists():
            raise RuntimeError('An unfinished transaction exists; inspect status and resume it')
        name = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:12]
        transaction = Transaction(private_directory(self.directory / 'transactions' / name),
            {'schema': 1, 'kind': kind, 'plan': plan.to_dict(), 'committed': False,
             'checkpoint_ready': False})
        transaction.save('PREPARED')
        write_json(active, {'transaction': name})
        return transaction

    def _complete(self, transaction):
        transaction.save('COMPLETE')
        write_json(self.directory / 'installed.json', {'commit': transaction.plan.target,
            'version': transaction.plan.version, 'transaction': transaction.path.name})
        (self.directory / 'active.json').unlink(missing_ok=True)

    def _recover(self, transaction):
        try:
            transaction.save('RECOVERING')
            if transaction.data.get('checkpoint_ready'):
                self.operations.restore(transaction)
            else:
                self.operations.abort_before_deploy(transaction)
            self.operations.verify(transaction, target=False)
            transaction.save('RECOVERY_VERIFIED', recovery_committed=True)
            self.operations.finish(transaction)
            transaction.save('ROLLED_BACK')
            write_json(self.directory / 'installed.json', {'commit': transaction.plan.source,
                'version': transaction.plan.source_version, 'transaction': transaction.path.name})
            (self.directory / 'active.json').unlink(missing_ok=True)
        except Exception as error:
            transaction.failure(error)
            transaction.save('RECOVERY_REQUIRED')
            raise

    def _execute(self, transaction, restore_checkpoint=None):
        try:
            transaction.save('QUIESCING')
            self.operations.quiesce(transaction)
            transaction.save('CHECKPOINTING')
            self.operations.checkpoint(transaction)
            transaction.save('CHECKPOINTED', checkpoint_ready=True)
            transaction.save('DEPLOYING')
            if restore_checkpoint is None:
                self.operations.deploy(transaction)
                transaction.save('MIGRATING')
                self.operations.migrate(transaction)
            else:
                self.operations.restore(transaction, checkpoint=restore_checkpoint)
            transaction.save('VERIFYING')
            self.operations.verify(transaction, target=True)
            # This boundary must be durable before any writer/public access resumes.
            transaction.save('COMMITTED', committed=True)
            self.operations.finish(transaction)
            self._complete(transaction)
        except Exception as error:
            transaction.failure(error)
            if transaction.data.get('committed'):
                transaction.save('COMMIT_NEEDS_ATTENTION')
            else:
                self._recover(transaction)
            raise
        return transaction

    def apply(self, plan):
        with maintenance_lock(self.directory):
            self.operations.preflight(plan)
            return self._execute(self._new(plan))

    def resume(self):
        with maintenance_lock(self.directory):
            pointer = json.loads((self.directory / 'active.json').read_text())['transaction']
            if pointer in ('.','..') or Path(pointer).name != pointer:
                raise ValueError('Invalid transaction pointer')
            transaction = Transaction.load(self.directory / 'transactions' / pointer)
            if transaction.data.get('recovery_committed'):
                self.operations.finish(transaction)
                transaction.save('ROLLED_BACK')
                write_json(self.directory / 'installed.json', {'commit': transaction.plan.source,
                    'version': transaction.plan.source_version, 'transaction': transaction.path.name})
                (self.directory / 'active.json').unlink(missing_ok=True)
            elif transaction.data.get('committed'):
                # Never restore a pre-upgrade DB after the write boundary.
                self.operations.finish(transaction)
                self._complete(transaction)
            else:
                self._recover(transaction)
            return transaction

    def rollback(self, name, *, confirm_version):
        with maintenance_lock(self.directory):
            if name in ('.','..') or Path(name).name != name:
                raise ValueError('Invalid transaction identifier')
            original = Transaction.load(self.directory / 'transactions' / name)
            if original.data['phase'] != 'COMPLETE' or confirm_version != original.plan.version:
                raise ValueError('Confirm the completed release version to authorize reverting later data')
            installed = json.loads((self.directory / 'installed.json').read_text())
            if installed['transaction'] != name:
                raise ValueError('Only the currently installed release can be rolled back')
            # The safety checkpoint protects all data written since the upgrade.
            previous = original.plan
            reverse = Plan(previous.schema, previous.installation, previous.target, previous.source,
                previous.source_version, previous.manifest_path, previous.manifest_sha256,
                previous.config_sha256, (), previous.web_after, previous.web_before, previous.protected_tables, previous.version, True)
            self.operations.preflight(reverse)
            transaction = self._new(reverse, kind='rollback')
            transaction.save(restore_from=original.path.name)
            return self._execute(transaction, restore_checkpoint=original)
