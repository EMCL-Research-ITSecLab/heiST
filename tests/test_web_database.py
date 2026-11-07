"""Real restricted-role session/auth checks in a newly created disposable database."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
import os
import re
from pathlib import Path
import secrets
import unittest
import uuid

from heist.api.public.repository import Repository
from heist.security.sessions import Sessions


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'), 'Disposable PostgreSQL administrator connection required')
class WebDatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg2
        from psycopg2 import sql
        from psycopg2.extensions import parse_dsn
        cls.psycopg2 = psycopg2
        cls.settings = parse_dsn(os.environ['TEST_DATABASE_URL'])
        cls.database = 'heist_web_test_'+uuid.uuid4().hex[:12]
        cls.role = cls.database+'_api'
        cls.observer_role = cls.database+'_observer'
        cls.password = secrets.token_hex(24)
        admin = psycopg2.connect(**cls.settings)
        admin.autocommit = True
        try:
            with admin.cursor() as cursor:
                cursor.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(cls.database)))
                cursor.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD %s').format(sql.Identifier(cls.role)), (cls.password,))
                cursor.execute(sql.SQL('CREATE ROLE {}').format(sql.Identifier(cls.observer_role)))
            cls.settings['dbname'] = cls.database
            root = Path(__file__).resolve().parents[1]
            with closing(psycopg2.connect(**cls.settings)) as connection:
                connection.autocommit = True
                with connection.cursor() as cursor:
                    cursor.execute((root/'database/init.sql').read_text())
                    cursor.execute('CREATE SCHEMA api')
                    names = set()
                    for source in sorted((root/'database/functions/api').glob('*.sql')):
                        definition = source.read_text()
                        cursor.execute(definition)
                        names.update(re.findall(r'CREATE(?: OR REPLACE)? FUNCTION\s+([a-z_][a-z0-9_]*)', definition, re.I))
                    # The existing installer moves API functions to its private schema.
                    cursor.execute("SELECT p.oid::regprocedure::text FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public' AND p.proname=ANY(%s)", (list(names),))
                    for (signature,) in cursor.fetchall():
                        signature = signature.removeprefix('public.')
                        cursor.execute('ALTER FUNCTION '+signature+' SET SCHEMA api')
                        cursor.execute('ALTER FUNCTION api.'+signature+' SECURITY DEFINER')
                    cursor.execute(sql.SQL('ALTER ROLE {} SET search_path = api, public').format(sql.Identifier(cls.role)))
                    cursor.execute(sql.SQL('GRANT USAGE ON SCHEMA api TO {}').format(sql.Identifier(cls.role)))
                    cursor.execute(sql.SQL('GRANT USAGE ON SCHEMA api TO {}').format(sql.Identifier(cls.observer_role)))
                    cursor.execute(sql.SQL('GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA api TO {}').format(sql.Identifier(cls.role)))
                    cursor.execute("SELECT set_config('heist.web_api_role', %s, false)", (cls.role,))
                    cursor.execute((root/'releases/migrations/0002_web_sessions.sql').read_text())
                    cursor.execute((root/'releases/migrations/0003_learning_visibility.sql').read_text())
                    cursor.execute((root/'releases/migrations/0004_grading_time.sql').read_text())
                    cursor.execute((root/'releases/migrations/0005_account_deletion.sql').read_text())
                    cursor.execute((root/'releases/migrations/0006_authoring_state.sql').read_text())
                    cursor.execute((root/'releases/migrations/0007_monotonic_resource_ids.sql').read_text())
                    cursor.execute((root/'releases/migrations/0008_instance_activation.sql').read_text())
                    cursor.execute((root/'releases/migrations/0009_artifact_availability.sql').read_text())
                    cursor.execute((root/'releases/migrations/0010_registration_acceptance.sql').read_text())
                    cursor.execute("INSERT INTO public.vpn_static_ips(vpn_static_ip) SELECT ('10.64.0.'||n)::inet FROM generate_series(2,250) n ON CONFLICT DO NOTHING")
            cls.api_settings = {**cls.settings, 'user': cls.role, 'password': cls.password}
        except BaseException:
            cls.remove_database(admin)
            raise
        finally:
            admin.close()

    @classmethod
    def remove_database(cls, admin):
        from psycopg2 import sql
        with admin.cursor() as cursor:
            cursor.execute(sql.SQL('DROP DATABASE IF EXISTS {} WITH (FORCE)').format(sql.Identifier(cls.database)))
            cursor.execute(sql.SQL('DROP ROLE IF EXISTS {}').format(sql.Identifier(cls.role)))
            cursor.execute(sql.SQL('DROP ROLE IF EXISTS {}').format(sql.Identifier(cls.observer_role)))

    @classmethod
    def tearDownClass(cls):
        admin_settings = dict(cls.settings)
        from psycopg2.extensions import parse_dsn
        admin_settings['dbname'] = parse_dsn(os.environ['TEST_DATABASE_URL']).get('dbname', 'postgres')
        admin = cls.psycopg2.connect(**admin_settings)
        admin.autocommit = True
        try:
            cls.remove_database(admin)
        finally:
            admin.close()

    def setUp(self):
        self.now = datetime(2026, 10, 30, 12, tzinfo=timezone.utc)
        self.repo = Repository(lambda: self.psycopg2.connect(**self.api_settings))
        self.addCleanup(self.repo.close)
        self.sessions = Sessions(self.repo, 'a'*64, clock=lambda: self.now)
        self.username = 'web_'+uuid.uuid4().hex[:10]
        self.legacy_salt = secrets.token_hex(16)
        self.old_hash = hashlib.sha512((self.legacy_salt+'legacy-password').encode()).hexdigest()
        with closing(self.psycopg2.connect(**self.settings)) as admin:
            admin.autocommit = True
            with admin.cursor() as cursor:
                cursor.execute('SELECT id FROM api.create_user(%s,%s,%s,%s,%s)',
                               (self.username, self.username+'@example.invalid', self.old_hash, self.legacy_salt, '127.0.0.1'))
                self.user_id = cursor.fetchone()[0]

    def test_opaque_session_rotation_expiry_and_revocation_use_real_storage(self):
        guest = self.sessions.rotate()
        self.assertIsNone(self.sessions.load(guest)['user_id'])
        signed_in = self.sessions.rotate(guest, self.user_id, 0)
        self.assertIsNone(self.sessions.load(guest))
        self.assertEqual(self.sessions.load(signed_in)['user_id'], self.user_id)
        self.sessions.revoke(signed_in)
        self.assertIsNone(self.sessions.load(signed_in))
        expired = self.sessions.rotate(user_id=self.user_id)
        self.now += timedelta(hours=2)
        self.assertIsNone(self.sessions.load(expired))

    def test_absolute_expiry_cannot_be_extended_by_continuous_use(self):
        raw = self.sessions.rotate(user_id=self.user_id)
        for _ in range(15):
            self.now += timedelta(minutes=30)
            self.assertIsNotNone(self.sessions.load(raw))
        self.now += timedelta(minutes=30)
        self.assertIsNone(self.sessions.load(raw))

    def test_password_replacement_revokes_sessions_and_rejects_stale_authentication(self):
        raw = self.sessions.rotate(user_id=self.user_id)
        self.repo.call('web_password_replace', self.user_id, self.old_hash, 'adaptive-placeholder', '', True)
        self.assertIsNone(self.sessions.load(raw))
        self.assertEqual(self.repo.call('web_auth_record', self.username, one=True)['auth_version'], 1)
        with self.assertRaises(self.psycopg2.Error):
            self.sessions.rotate(user_id=self.user_id, auth_version=0)
        self.assertEqual(self.sessions.load(self.sessions.rotate(user_id=self.user_id, auth_version=1))['user_id'], self.user_id)

    def test_rehash_preserves_force_reset_and_does_not_revoke_other_sessions(self):
        raw = self.sessions.rotate(user_id=self.user_id)
        self.repo.call('web_password_replace', self.user_id, self.old_hash, 'adaptive-placeholder', '', False)
        self.assertIsNotNone(self.sessions.load(raw))
        self.assertEqual(self.repo.call('web_auth_record', self.username, one=True)['auth_version'], 0)
        with self.assertRaises(self.psycopg2.Error):
            self.repo.call('web_password_replace', self.user_id, self.old_hash, 'another-placeholder', '', False)

    def test_rate_limit_is_atomic_bounded_and_recovers_after_window(self):
        key = hashlib.sha256(self.username.encode()).hexdigest()
        for expected in (True, True, False, False):
            self.assertEqual(self.repo.scalar('web_rate_limit', key, 2, 60, self.now), expected)
        self.now += timedelta(seconds=61)
        self.assertTrue(self.repo.scalar('web_rate_limit', key, 2, 60, self.now))
        self.repo.call('web_cleanup', self.now+timedelta(hours=9))

    def test_restricted_application_role_cannot_read_account_tables_or_create_functions(self):
        with self.assertRaises(self.psycopg2.Error):
            with self.repo.db().cursor() as cursor:
                cursor.execute('SELECT password_hash FROM public.users')
        with self.assertRaises(self.psycopg2.Error):
            with self.repo.db().cursor() as cursor:
                cursor.execute('CREATE TABLE api.forbidden(id int)')
        identity = self.repo.call('web_user_identity', self.user_id, one=True)
        self.assertNotIn('password_hash', identity)
        self.assertFalse(identity['is_admin'])

    def test_schema_observer_does_not_gain_session_issuer_or_password_access(self):
        from psycopg2 import sql
        with closing(self.psycopg2.connect(**self.settings)) as connection:
            connection.autocommit = True
            with connection.cursor() as cursor:
                cursor.execute(sql.SQL('SET ROLE {}').format(sql.Identifier(self.observer_role)))
                try:
                    with self.assertRaises(self.psycopg2.Error):
                        cursor.execute('SELECT * FROM api.web_auth_record(%s)', (self.username,))
                    with self.assertRaises(self.psycopg2.Error):
                        cursor.execute('SELECT api.web_session_rotate(NULL,%s,%s,0,%s)', ('a'*64, self.user_id, self.now))
                    with self.assertRaises(self.psycopg2.Error):
                        cursor.execute('SELECT * FROM api.create_user(%s,%s,%s,%s,%s)', ('observer_user', 'observer@example.invalid', 'unused', '', '127.0.0.1'))
                finally:
                    cursor.execute('RESET ROLE')

    def test_mutation_lease_serializes_one_account_and_is_released_when_connection_closes(self):
        second = Repository(lambda: self.psycopg2.connect(**self.api_settings))
        self.addCleanup(second.close)
        self.assertTrue(self.repo.scalar('web_user_mutation_lock', self.user_id))
        self.assertFalse(second.scalar('web_user_mutation_lock', self.user_id))
        self.assertTrue(second.scalar('web_user_mutation_lock', self.user_id+1))
        self.repo.close()
        self.assertTrue(second.scalar('web_user_mutation_lock', self.user_id))

    def test_temporary_tables_cannot_shadow_legacy_security_definer_relations(self):
        with self.repo.db().cursor() as cursor:
            cursor.execute('CREATE TEMP TABLE users(id bigint, username text, password_hash text)')
            cursor.execute('INSERT INTO pg_temp.users VALUES (%s,%s,%s)', (self.user_id, self.username, 'forged-hash'))
        actual = self.repo.call('get_basic_profile_data', self.user_id, one=True)
        self.assertEqual(actual['email'], self.username+'@example.invalid')
        self.assertNotIn('forged-hash', str(actual))

    def test_public_repository_rejects_privileged_role_even_when_its_name_is_not_special(self):
        privileged = Repository(lambda: self.psycopg2.connect(**self.settings))
        with self.assertRaises(PermissionError):
            privileged.db()
        self.assertIsNone(privileged.connection)

    def test_public_repository_refuses_direct_account_table_grants(self):
        from psycopg2 import sql
        with closing(self.psycopg2.connect(**self.settings)) as connection:
            connection.autocommit = True
            with connection.cursor() as cursor:
                cursor.execute(sql.SQL('GRANT SELECT ON public.users TO {}').format(sql.Identifier(self.role)))
                try:
                    with self.assertRaises(PermissionError):
                        self.repo.db()
                    self.assertIsNone(self.repo.connection)
                finally:
                    cursor.execute(sql.SQL('REVOKE SELECT ON public.users FROM {}').format(sql.Identifier(self.role)))

    def test_public_repository_refuses_additional_role_memberships(self):
        from psycopg2 import sql
        with closing(self.psycopg2.connect(**self.settings)) as connection:
            connection.autocommit = True
            with connection.cursor() as cursor:
                cursor.execute(sql.SQL('GRANT {} TO {}').format(sql.Identifier(self.observer_role), sql.Identifier(self.role)))
                try:
                    with self.assertRaises(PermissionError):
                        self.repo.db()
                finally:
                    cursor.execute(sql.SQL('REVOKE {} FROM {}').format(sql.Identifier(self.observer_role), sql.Identifier(self.role)))

    def test_resource_allocators_never_reuse_reclaimed_ids(self):
        with closing(self.psycopg2.connect(**self.settings)) as connection:
            connection.autocommit = True
            with connection.cursor() as cursor:
                for resource, reclaim in (('user', 'user_id_reclaim'), ('machine', 'machine_id_reclaim'),
                                          ('machine_template', 'machine_template_id_reclaim'),
                                          ('network', 'network_id_reclaim'), ('challenge', 'challenge_id_reclaim')):
                    cursor.execute('SELECT public.allocate_'+resource+'_id()')
                    previous = cursor.fetchone()[0]
                    cursor.execute('INSERT INTO public.'+reclaim+'(id) VALUES (%s) ON CONFLICT DO NOTHING', (previous,))
                    cursor.execute('SELECT public.allocate_'+resource+'_id()')
                    self.assertGreater(cursor.fetchone()[0], previous)

    def test_snapshot_recovery_preserves_allocation_history_and_invalidates_restored_sessions(self):
        from types import SimpleNamespace
        import tempfile
        from heist.rollout.identifiers import preserve, reconcile
        settings = SimpleNamespace(connect=lambda: self.psycopg2.connect(**self.settings))
        self.sessions.rotate(user_id=self.user_id)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/'id-watermarks.json'
            with closing(settings.connect()) as connection:
                with connection.cursor() as cursor:
                    cursor.execute('SELECT public.allocate_challenge_id()')
                    current = cursor.fetchone()[0]
                    cursor.execute("SELECT setval('public.challenges_id_seq',%s,true)", (current+200,))
            history = preserve(settings, path)
            high = history['challenges_id_seq']
            # Model a VM snapshot rewinding PostgreSQL sequence state. No
            # production database or VM is restored by this contract test.
            with closing(settings.connect()) as connection:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT setval('public.challenges_id_seq',%s,true)", (current,))
                    cursor.execute('SELECT username,password_hash FROM public.users WHERE id=%s', (self.user_id,))
                    protected = cursor.fetchone()
            self.assertEqual(preserve(settings, path)['challenges_id_seq'], high)
            reconcile(settings, history)
            reconcile(settings, history)
            with closing(settings.connect()) as connection:
                with connection.cursor() as cursor:
                    cursor.execute('SELECT public.allocate_challenge_id()')
                    self.assertGreater(cursor.fetchone()[0], high)
                    cursor.execute('SELECT count(*) FROM public.web_sessions')
                    self.assertEqual(cursor.fetchone()[0], 0)
                    cursor.execute('SELECT username,password_hash FROM public.users WHERE id=%s', (self.user_id,))
                    self.assertEqual(cursor.fetchone(), protected)

    def test_monotonic_migration_advances_past_existing_and_reclaimed_high_water_marks(self):
        with closing(self.psycopg2.connect(**self.settings)) as connection:
            connection.autocommit = True
            with connection.cursor() as cursor:
                cursor.execute('SELECT last_value FROM public.challenges_id_seq')
                high = cursor.fetchone()[0]+100
                cursor.execute('INSERT INTO public.challenge_id_reclaim(id) VALUES (%s)', (high,))
                cursor.execute("SELECT password_hash, username FROM public.users WHERE id=%s", (self.user_id,))
                protected = cursor.fetchone()
                cursor.execute((Path(__file__).resolve().parents[1]/'releases/migrations/0007_monotonic_resource_ids.sql').read_text())
                cursor.execute('SELECT public.allocate_challenge_id()')
                self.assertGreater(cursor.fetchone()[0], high)
                cursor.execute("SELECT password_hash, username FROM public.users WHERE id=%s", (self.user_id,))
                self.assertEqual(cursor.fetchone(), protected)
