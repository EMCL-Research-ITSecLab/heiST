"""Real upgrade of historical registration records to explicit terms acceptance."""
from contextlib import closing
import os
from pathlib import Path
import unittest
import uuid


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'), 'Disposable PostgreSQL administrator connection required')
class TermsAcceptanceMigrationTests(unittest.TestCase):
    def test_old_consent_is_not_relabelled_and_new_terms_are_required_with_restricted_grants(self):
        import psycopg2
        from psycopg2 import sql
        from psycopg2.extensions import parse_dsn
        settings = parse_dsn(os.environ['TEST_DATABASE_URL'])
        identifier = uuid.uuid4().hex
        database = 'heist_terms_' + identifier
        role, observer = 'heist_web_' + identifier, 'heist_observer_' + identifier
        root = Path(__file__).resolve().parents[1]
        with closing(psycopg2.connect(**settings)) as owner:
            owner.autocommit = True
            try:
                with owner.cursor() as cursor:
                    cursor.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(database)))
                    for name in (role, observer):cursor.execute(sql.SQL('CREATE ROLE {}').format(sql.Identifier(name)))
                with closing(psycopg2.connect(**{**settings, 'dbname':database})) as connection:
                    connection.autocommit = True
                    with connection.cursor() as cursor:
                        cursor.execute('CREATE TABLE public.users(id BIGINT PRIMARY KEY); CREATE SCHEMA api')
                        cursor.execute("SELECT set_config('heist.web_api_role',%s,false)", (role,))
                        cursor.execute((root/'releases/migrations/0010_registration_acceptance.sql').read_text())
                        cursor.execute('INSERT INTO users VALUES(1),(2)')
                        cursor.execute("INSERT INTO registration_acceptances(user_id,policy_version,imprint_url,privacy_url,accepted_at) VALUES(1,%s,'https://operator.invalid/imprint','https://operator.invalid/privacy','2026-01-01T00:00:00Z')", ('c'*64,))
                        cursor.execute('SELECT * FROM registration_acceptances');before = cursor.fetchone()
                        cursor.execute((root/'releases/migrations/0011_terms_acceptance.sql').read_text())
                        cursor.execute('SELECT * FROM registration_acceptances');self.assertEqual(cursor.fetchone(), before + (None,))
                        cursor.execute("SELECT to_regprocedure('api.web_record_registration(bigint,text,text,text)')")
                        self.assertEqual(cursor.fetchone(), (None,))
                        signature = 'api.web_record_registration(bigint,text,text,text,text)'
                        cursor.execute("SELECT has_function_privilege(%s,%s,'EXECUTE'),has_function_privilege(%s,%s,'EXECUTE')", (role,signature,observer,signature))
                        self.assertEqual(cursor.fetchone(), (True,False))
                        for terms in (None, ''):
                            with self.assertRaises(psycopg2.errors.RaiseException):
                                cursor.execute('SELECT api.web_record_registration(2,%s,%s,%s,%s)', ('d'*64,'https://operator.invalid/imprint','https://operator.invalid/privacy',terms))
                        cursor.execute('SELECT count(*) FROM registration_acceptances');self.assertEqual(cursor.fetchone(), (1,))
                        cursor.execute('SELECT api.web_record_registration(2,%s,%s,%s,%s)', ('d'*64,'https://operator.invalid/imprint','https://operator.invalid/privacy','https://operator.invalid/terms'))
                        cursor.execute('SELECT terms_url FROM registration_acceptances WHERE user_id=2');self.assertEqual(cursor.fetchone(), ('https://operator.invalid/terms',))
            finally:
                with owner.cursor() as cursor:
                    cursor.execute(sql.SQL('DROP DATABASE IF EXISTS {} WITH (FORCE)').format(sql.Identifier(database)))
                    for name in (role, observer):cursor.execute(sql.SQL('DROP ROLE IF EXISTS {}').format(sql.Identifier(name)))
