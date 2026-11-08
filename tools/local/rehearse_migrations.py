#!/usr/bin/env python3
"""Rehearse immutable release SQL on a disposable copy of the pilot database.

Never migrates the installed database. Tests an injected failure after real SQL,
restricted-role upgrades, session invalidation and complete scratch DB recovery.
This does not replace whole-platform VM/host rollback acceptance.
"""
from contextlib import closing
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import secrets
import re
import shutil
import sys
import uuid

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(Path(__file__).resolve().parent))

from rehearse_recovery import require_fixture
from heist.files import maintenance_lock,private_directory,sha256,write_json
from heist.maintenance.database import PostgreSQL
from heist.rollout.config import Deployment
from heist.rollout.manifest import Migration,Plan,blob,revision
from heist.rollout.migrations import migrate


class InjectedMigrationFailure(RuntimeError):
    pass


def external_baseline_source(path, digest, source):
    """Bind a private external dump to its reviewed bytes and source identity."""
    if (path.is_symlink() or not path.is_file() or path.stat().st_uid != 0 or path.stat().st_mode & 0o077 or
            not re.fullmatch('[a-f0-9]{64}', digest or '') or sha256(path) != digest or
            not re.fullmatch('[a-f0-9]{40}', source or '')):
        raise RuntimeError('Require a private root-owned dump, exact reviewed checksum and original source commit')
    with path.open('rb') as stream:
        if stream.read(5) != b'PGDMP':
            raise RuntimeError('External baseline is not a PostgreSQL custom archive')
    return source


class FaultCursor:
    def __init__(self,cursor,identifier):self.cursor,self.identifier=cursor,identifier
    def __enter__(self):self.cursor.__enter__();return self
    def __exit__(self,*error):return self.cursor.__exit__(*error)
    def __getattr__(self,name):return getattr(self.cursor,name)
    def execute(self,statement,parameters=None):
        if isinstance(statement,str) and statement.startswith('INSERT INTO public.heist_schema_migrations') and parameters[0]==self.identifier:
            raise InjectedMigrationFailure('Injected failure after the last migration body, before its ledger commit')
        return self.cursor.execute(statement,parameters)


class FaultConnection:
    def __init__(self,connection,identifier):self.connection,self.identifier=connection,identifier
    def __getattr__(self,name):return getattr(self.connection,name)
    def cursor(self,*args,**kwargs):return FaultCursor(self.connection.cursor(*args,**kwargs),self.identifier)


def schema_fingerprint(settings):
    values=[]
    with closing(settings.connect()) as connection,connection.cursor() as cursor:
        for statement in (
            "SELECT n.nspname,c.relname,c.relkind,c.relacl::text FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname IN ('api','public') ORDER BY 1,2,3",
            "SELECT n.nspname,p.proname,pg_get_function_identity_arguments(p.oid),p.proacl::text,pg_get_functiondef(p.oid) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname IN ('api','public') AND p.prokind='f' ORDER BY 1,2,3",
            "SELECT table_schema,table_name,column_name,data_type,is_nullable,column_default FROM information_schema.columns WHERE table_schema IN ('api','public') ORDER BY 1,2,ordinal_position",
            "SELECT n.nspname,c.relname,k.conname,pg_get_constraintdef(k.oid) FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname IN ('api','public') ORDER BY 1,2,3",
        ):
            cursor.execute(statement);values.append(cursor.fetchall())
    return hashlib.sha256(json.dumps(values,default=str,sort_keys=True).encode()).hexdigest()


def verify_personalized_flags(settings):
    """Exercise existing personalized flags against the restored SQL grader.

    Use one existing account and every personalized flag. No flag, secret or
    account identity is included in the receipt; locking SELECTs are rolled back.
    An empty fixture is recorded as untested rather than a compatibility pass.
    """
    from heist.platform.challenges.launch import resolve_user_specific_flag
    with closing(settings.connect()) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT id,email,unique_id FROM public.users WHERE email IS NOT NULL AND unique_id IS NOT NULL ORDER BY id LIMIT 1")
        user = cursor.fetchone()
        cursor.execute('SELECT id,challenge_template_id,flag FROM public.challenge_flags WHERE user_specific ORDER BY id')
        flags = cursor.fetchall()
        if not user or not flags:
            return {'tested': False, 'flags_checked': 0}
        for identifier, template, secret in flags:
            resolve_user_specific_flag(connection, template_id=template,
                flag={'id': identifier, 'flag': secret}, user_id=user[0], user_email=user[1], user_unique_id=user[2])
        return {'tested': True, 'flags_checked': len(flags)}


def main(argv=None):
    import argparse
    from psycopg2 import sql
    from types import SimpleNamespace
    from heist.api.public.repository import Repository
    from heist.security.sessions import Sessions
    from heist.rollout.pve import PVE
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',required=True,type=Path)
    parser.add_argument('--manifest',default='releases/0.4.0-rc.1.json')
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--baseline-dump',type=Path,help='Private external PG dump; restored only into a new scratch database')
    parser.add_argument('--baseline-sha256',help='Reviewed digest of the external archive')
    parser.add_argument('--baseline-source',help='Original installation commit for the external archive')
    parser.add_argument('--audit-unsupported-source',action='store_true',help='Scratch SQL compatibility audit only; never approves platform admission')
    args=parser.parse_args(argv)
    require_fixture()
    if args.output.exists():raise ValueError('Use a new evidence directory')
    config=Deployment.load(args.config)
    adapter=PVE(config,sha256(args.config))
    source,target=revision(adapter.installation,'HEAD'),revision(ROOT,'HEAD')
    if args.baseline_dump:
        source=external_baseline_source(args.baseline_dump,args.baseline_sha256,args.baseline_source)
    elif args.baseline_sha256 or args.baseline_source or args.audit_unsupported_source:
        raise RuntimeError('External baseline options require --baseline-dump')
    release=json.loads(blob(ROOT,target,args.manifest))
    supported=source in release['supported_from']
    if release.get('schema')!=3 or (not supported and not (args.baseline_dump and args.audit_unsupported_source)):
        raise RuntimeError('The candidate must explicitly declare this legacy source')
    migrations=tuple(Migration(item['id'],item['path'],item['sha256']) for item in release['migrations'])
    for item in migrations:
        if hashlib.sha256(blob(ROOT,target,item.path)).hexdigest()!=item.sha256:raise RuntimeError('Migration checksum differs')
    if not migrations:raise RuntimeError('The rehearsal requires pending release migrations')
    plan=Plan(3,str(ROOT),source,target,release['version'],args.manifest,
              hashlib.sha256(blob(ROOT,target,args.manifest)).hexdigest(),sha256(args.config),migrations,(),(),tuple(release['protected_tables']))
    identifier=uuid.uuid4().hex[:12]
    name='heist_migration_'+identifier
    roles=['heist_web_migration_'+identifier+'a','heist_web_migration_'+identifier+'b']
    baseline_settings=adapter.database
    settings=replace(baseline_settings,name=name)
    owner=adapter.database.connect(autocommit=True)
    created=False
    with maintenance_lock(adapter.state),closing(owner):
        if adapter.marker.exists() or (adapter.state/'active.json').exists():raise RuntimeError('Finish the active platform transaction first')
        adapter.assert_idle(allow_ready=True)
        output=private_directory(args.output)
        receipt={'source_commit':target,'baseline_source':source,'manifest_sha256':plan.manifest_sha256,
                 'starting_commit_declared_supported':supported,
                 'external_baseline':bool(args.baseline_dump),
                 'whole_platform_upgrade_approved':False,'checks':{}}
        write_json(output/'receipt.json',receipt)
        try:
            original=PostgreSQL(adapter.database,config.vm('database').ssh)
            archive=output/'baseline.dump'
            if args.baseline_dump:
                shutil.copyfile(args.baseline_dump,archive)
            else:
                with archive.open('xb') as stream:original.dump(stream)
            archive.chmod(0o600);original.validate(archive)
            receipt['dump_sha256']=sha256(archive)
            with owner.cursor() as cursor:cursor.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
            created=True
            database=PostgreSQL(settings,config.vm('database').ssh)
            database.restore(archive)
            adapter.database=settings
            protected=adapter.protected_hashes(plan.protected_tables)
            fingerprint=schema_fingerprint(settings)
            with closing(settings.connect()) as connection,connection.cursor() as cursor:
                cursor.execute("SELECT to_regclass('public.heist_schema_migrations')")
                if cursor.fetchone()[0]:
                    cursor.execute('SELECT id FROM public.heist_schema_migrations WHERE id=%s',(migrations[-1].identifier,))
                    if cursor.fetchone():raise RuntimeError('Last migration already applied; use a fresh legacy clone')
            failing=SimpleNamespace(connect=lambda:FaultConnection(settings.connect(),migrations[-1].identifier))
            try:migrate(failing,plan,web_role=roles[0],web_password=secrets.token_urlsafe(48))
            except InjectedMigrationFailure:pass
            else:raise AssertionError('Expected the injected migration failure')
            assert schema_fingerprint(settings)==fingerprint
            assert adapter.protected_hashes(plan.protected_tables)==protected
            with owner.cursor() as cursor:
                cursor.execute('SELECT count(*) FROM pg_roles WHERE rolname=%s',(roles[0],));assert cursor.fetchone()==(0,)
            receipt['checks']['failed_upgrade_preserves_rows_schema_and_roles']=True
            passwords=[secrets.token_urlsafe(48),secrets.token_urlsafe(48)]
            migrate(settings,plan,web_role=roles[0],web_password=passwords[0])
            assert adapter.protected_hashes(plan.protected_tables)==protected
            restricted=replace(settings,user=roles[0],password=passwords[0])
            repo=Repository(restricted.connect)
            try:
                repo.call('web_disk_files',-1)
                sessions=Sessions(repo,'a'*64);token=sessions.rotate();assert sessions.load(token)
            finally:repo.close()
            receipt['checks']['legacy_migrations_and_restricted_role']=True
            receipt['personalized_flags']=verify_personalized_flags(settings)
            assert adapter.protected_hashes(plan.protected_tables)==protected
            migrate(settings,plan,web_role=roles[1],web_password=passwords[1],previous_web_role=roles[0])
            with closing(settings.connect()) as connection,connection.cursor() as cursor:
                cursor.execute('SELECT count(*) FROM public.web_sessions');assert cursor.fetchone()==(0,)
                cursor.execute('SELECT rolcanlogin FROM pg_roles WHERE rolname=%s',(roles[0],));assert cursor.fetchone()==(False,)
            repo=Repository(replace(settings,user=roles[1],password=passwords[1]).connect)
            try:repo.call('web_disk_files',-1)
            finally:repo.close()
            receipt['checks']['later_release_grants_and_session_invalidation']=True
            # Whole database replacement removes post-upgrade objects; pg_restore
            # --clean by itself cannot remove objects absent from its old archive.
            with owner.cursor() as cursor:
                cursor.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
                created=False
                for role in roles:cursor.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(role)))
                cursor.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
                created=True
            database.restore(archive)
            assert schema_fingerprint(settings)==fingerprint
            assert adapter.protected_hashes(plan.protected_tables)==protected
            receipt['checks']['complete_scratch_database_recovery']=True
            receipt['passed']=True
            write_json(output/'receipt.json',receipt)
            print(json.dumps(receipt))
        finally:
            adapter.database=baseline_settings
            with owner.cursor() as cursor:
                if created:cursor.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
                for role in roles:cursor.execute(sql.SQL('DROP ROLE IF EXISTS {}').format(sql.Identifier(role)))


if __name__=='__main__':
    main()
