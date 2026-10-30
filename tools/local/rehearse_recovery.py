#!/usr/bin/env python3
"""Destructive recovery rehearsal, restricted to the verified disposable pilot.

Run after a successful upgrade. This deliberately rolls that release back,
interrupts service completion after commit, and restores its newer SQL safety
backup into a separate test database. It never runs on an unverified host.
"""
from dataclasses import replace
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from heist.files import sha256
from heist.maintenance.database import PostgreSQL
from heist.rollout.config import Deployment
from heist.rollout.controller import Controller, Transaction
from heist.rollout.pve import PVE


class InjectedFinishFailure(RuntimeError):
    pass


class InterruptFinish(PVE):
    interrupted = False

    def finish(self, transaction):
        if transaction.data.get('committed') and not self.interrupted:
            self.interrupted = True
            raise InjectedFinishFailure('Disposable rehearsal: interrupt after durable commit')
        super().finish(transaction)


def require_fixture():
    if (os.environ.get('HEIST_PRIVILEGED_TESTS') != '1' or os.geteuid() != 0 or
            socket.gethostname().split('.')[0] != 'heist-pilot' or
            not Path('/root/pilot-cloud-init-ready').is_file()):
        raise RuntimeError('Recovery rehearsal requires the explicitly opted-in disposable heist-pilot')
    path = Path('/root/pilot-offline-verified.json')
    if path.is_symlink() or path.stat().st_uid != 0 or path.stat().st_mode & 0o077:
        raise RuntimeError('A private root-owned isolation proof is required')
    proof = json.loads(path.read_text())
    if (proof.get('passed') is not True or
            proof.get('boot_id') != Path('/proc/sys/kernel/random/boot_id').read_text().strip()):
        raise RuntimeError('Rerun the workstation offline verifier for this boot')


def query(settings, statement, parameters=()):
    connection = settings.connect(autocommit=True)
    try:
        with connection.cursor() as cursor:
            cursor.execute(statement, parameters)
            return cursor.fetchall() if cursor.description else None
    finally:
        connection.close()


def main(argv=None):
    import argparse
    from psycopg2 import sql
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--transaction', required=True, help='Currently installed completed upgrade')
    parser.add_argument('--confirm-version', required=True)
    args = parser.parse_args(argv)
    require_fixture()
    config = Deployment.load(args.config)
    operations = InterruptFinish(config, sha256(args.config))
    controller = Controller(config.state_directory, operations)
    identifier = uuid.uuid4().hex
    before = 'heist_before_' + identifier
    after = 'heist_after_' + identifier
    temporary_database = 'heist_recovery_' + identifier
    temporary_created = False
    completed = False
    settings = operations.database
    try:
        query(settings, sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(before)))
        query(settings, sql.SQL('CREATE TABLE {}.probe(value text)').format(sql.Identifier(before)))
        query(settings, sql.SQL('INSERT INTO {}.probe VALUES (%s)').format(sql.Identifier(before)), ('newer-data',))
        try:
            controller.rollback(args.transaction, confirm_version=args.confirm_version)
            raise AssertionError('Expected the injected postcommit interruption')
        except InjectedFinishFailure:
            pass
        state = Path(config.state_directory)
        pointer = json.loads((state/'active.json').read_text())['transaction']
        transaction = Transaction.load(state/'transactions'/pointer)
        if transaction.data['phase'] != 'COMMIT_NEEDS_ATTENTION' or not transaction.data['committed']:
            raise AssertionError('Postcommit interruption was not durably recorded')
        if query(settings, 'SELECT to_regnamespace(%s)', (before,)) != [(None,)]:
            raise AssertionError('Old VM checkpoint did not restore the original database')
        tasks = json.dumps(transaction.data['tasks'], sort_keys=True)
        query(settings, sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(after)))
        query(settings, sql.SQL('CREATE TABLE {}.probe(value text)').format(sql.Identifier(after)))
        query(settings, sql.SQL('INSERT INTO {}.probe VALUES (%s)').format(sql.Identifier(after)), ('after-commit',))
        subprocess.run([sys.executable, '-m', 'heist', 'upgrade', 'resume', '--config', str(args.config)],
                       cwd=ROOT, capture_output=True, check=True)
        resumed = Transaction.load(transaction.path)
        if resumed.data['phase'] != 'COMPLETE' or json.dumps(resumed.data['tasks'], sort_keys=True) != tasks:
            raise AssertionError('Resume changed restore tasks or did not complete')
        if query(settings, sql.SQL('SELECT value FROM {}.probe').format(sql.Identifier(after))) != [('after-commit',)]:
            raise AssertionError('Postcommit data was overwritten during resume')
        query(settings, sql.SQL('CREATE DATABASE {}').format(sql.Identifier(temporary_database)))
        temporary_created = True
        temporary_settings = replace(settings, name=temporary_database)
        PostgreSQL(temporary_settings, config.vm('database').ssh).restore(transaction.data['database_backup'])
        if query(temporary_settings, sql.SQL('SELECT value FROM {}.probe').format(sql.Identifier(before))) != [('newer-data',)]:
            raise AssertionError('Newer safety backup did not preserve pre-rollback data')
        operations.database = temporary_settings
        try:
            if operations.protected_hashes(transaction.plan.protected_tables) != transaction.data['protected_hashes']:
                raise AssertionError('Safety backup student/grade data differs')
        finally:
            operations.database = settings
        completed = True
        print(json.dumps({'transaction': pointer, 'whole_vm_rollback': 'passed',
                          'postcommit_resume': 'passed', 'newer_sql_backup_restore': 'passed',
                          'protected_student_data': 'matched'}))
    finally:
        if temporary_created:
            query(settings, 'SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=%s AND pid<>pg_backend_pid()',
                  (temporary_database,))
            query(settings, sql.SQL('DROP DATABASE {}').format(sql.Identifier(temporary_database)))
        # A pending recovery owns platform state. Leave its probe for diagnosis.
        if completed or not (Path(config.state_directory)/'active.json').exists():
            for schema in (before, after):
                query(settings, sql.SQL('DROP SCHEMA IF EXISTS {} CASCADE').format(sql.Identifier(schema)))


if __name__ == '__main__':
    raise SystemExit(main())
