"""Teardown claims protect assignments; resource metadata is reclaimed atomically."""
from contextlib import closing
import ipaddress
import os
import unittest

from tests import test_web_database as database
from heist.platform.challenges import teardown


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'), 'Disposable PostgreSQL administrator connection required')
class TeardownDatabaseTests(unittest.TestCase):
    setUpClass = classmethod(database.WebDatabaseTests.setUpClass.__func__)
    tearDownClass = classmethod(database.WebDatabaseTests.tearDownClass.__func__)
    remove_database = classmethod(database.WebDatabaseTests.remove_database.__func__)

    def setUp(self):
        database.WebDatabaseTests.setUp(self)
        self.template = self.sql("INSERT INTO challenge_templates(name,category,difficulty,creator_id) VALUES (%s,'web','easy',%s) RETURNING id", (self.username, self.user_id))[0][0]
        self.subnet = str(ipaddress.IPv4Network((int(ipaddress.IPv4Address('10.240.0.0'))+16*self.user_id, 28)))
        self.sql('INSERT INTO challenge_subnets(subnet,available) VALUES (%s,FALSE)', (self.subnet,))
        self.instance = self.sql("INSERT INTO challenges(challenge_template_id,subnet,lifecycle_state,pre_assigned_user_id) VALUES (%s,%s,'ACTIVE',%s) RETURNING id", (self.template, self.subnet, self.user_id))[0][0]

    def sql(self, statement, arguments=()):
        with closing(self.psycopg2.connect(**self.settings)) as connection:
            connection.autocommit = True
            with connection.cursor() as cursor:
                cursor.execute(statement, arguments)
                return cursor.fetchall() if cursor.description else None

    def test_active_assigned_or_wrong_template_instance_cannot_be_claimed_for_teardown(self):
        with closing(self.psycopg2.connect(**self.settings)) as connection:
            connection.autocommit = True
            self.assertIsNone(teardown.fetch_challenge(self.instance, connection, expected_template_id=self.template))
            self.sql("UPDATE challenges SET lifecycle_state='EXPIRED' WHERE id=%s", (self.instance,))
            self.sql('UPDATE users SET running_challenge=%s WHERE id=%s', (self.instance, self.user_id))
            self.assertIsNone(teardown.fetch_challenge(self.instance, connection, expected_template_id=self.template))
            self.sql('UPDATE users SET running_challenge=NULL WHERE id=%s', (self.user_id,))
            self.assertIsNone(teardown.fetch_challenge(self.instance, connection, expected_template_id=self.template+1))
            actual = teardown.fetch_challenge(self.instance, connection, expected_template_id=self.template)
            self.assertEqual(actual.id, self.instance)
            self.assertEqual(actual.template.id, self.template)
        self.assertEqual(self.sql('SELECT lifecycle_state FROM challenges WHERE id=%s', (self.instance,))[0][0], 'TERMINATING')

    def test_reserved_ready_instance_is_not_an_unassigned_pool_surplus(self):
        self.sql("UPDATE challenges SET lifecycle_state='READY' WHERE id=%s", (self.instance,))
        with closing(self.psycopg2.connect(**self.settings)) as connection:
            connection.autocommit = True
            self.assertIsNone(teardown.fetch_challenge(self.instance, connection))
            self.sql('UPDATE challenges SET pre_assigned_user_id=NULL WHERE id=%s', (self.instance,))
            self.assertIsNotNone(teardown.fetch_challenge(self.instance, connection))

    def test_orphan_network_metadata_is_loaded_even_without_machine_rows(self):
        network = self.sql("INSERT INTO network_templates(challenge_template_id,name,accessible) VALUES (%s,'entry',TRUE) RETURNING id", (self.template,))[0][0]
        identifier = self.sql("INSERT INTO networks(network_template_id,challenge_id,subnet,host_device) VALUES (%s,%s,'10.241.0.0/28','vrt123') RETURNING id", (network, self.instance))[0][0]
        self.sql("UPDATE challenges SET lifecycle_state='EXPIRED' WHERE id=%s", (self.instance,))
        with closing(self.psycopg2.connect(**self.settings)) as connection:
            connection.autocommit = True
            challenge = teardown.fetch_challenge(self.instance, connection)
            teardown.fetch_networks(challenge, connection)
        self.assertIn(identifier, challenge.networks)
        self.assertEqual(challenge.networks[identifier].host_device, 'vrt123')

    def test_metadata_reclamation_rolls_back_all_deletes_and_subnet_release_on_failure(self):
        self.sql("UPDATE challenges SET lifecycle_state='EXPIRED' WHERE id=%s", (self.instance,))
        template = self.sql("INSERT INTO network_templates(challenge_template_id,name,accessible) VALUES (%s,'rollback',TRUE) RETURNING id", (self.template,))[0][0]
        network = self.sql("INSERT INTO networks(network_template_id,challenge_id,subnet,host_device) VALUES (%s,%s,'10.241.1.0/28','vrtabc') RETURNING id", (template, self.instance))[0][0]
        with closing(self.psycopg2.connect(**self.settings)) as connection:
            connection.autocommit = True
            challenge = teardown.fetch_challenge(self.instance, connection)
            teardown.fetch_networks(challenge, connection)
            self.sql("CREATE FUNCTION reject_test_challenge_delete() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'injected cleanup failure'; END; $$")
            self.sql('CREATE TRIGGER reject_test_challenge_delete BEFORE DELETE ON challenges FOR EACH ROW EXECUTE FUNCTION reject_test_challenge_delete()')
            try:
                with self.assertRaises(self.psycopg2.Error):
                    teardown.remove_database_entries(challenge, connection)
                self.assertTrue(self.sql('SELECT id FROM challenges WHERE id=%s', (self.instance,)))
                self.assertTrue(self.sql('SELECT id FROM networks WHERE id=%s', (network,)))
                self.assertFalse(self.sql('SELECT id FROM network_id_reclaim WHERE id=%s', (network,)))
                self.assertFalse(self.sql('SELECT available FROM challenge_subnets WHERE subnet=%s', (self.subnet,))[0][0])
            finally:
                self.sql('DROP TRIGGER reject_test_challenge_delete ON challenges')
                self.sql('DROP FUNCTION reject_test_challenge_delete()')
            teardown.remove_database_entries(challenge, connection)
        self.assertFalse(self.sql('SELECT id FROM challenges WHERE id=%s', (self.instance,)))
        self.assertTrue(self.sql('SELECT available FROM challenge_subnets WHERE subnet=%s', (self.subnet,))[0][0])
