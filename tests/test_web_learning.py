"""Student read contracts run against real PostgreSQL and real session authorization."""
from contextlib import closing
import os
import unittest
from tests import test_web_auth as authentication
from tests import test_web_database as database


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'), 'Disposable PostgreSQL administrator connection required')
class LearningViewsTests(unittest.TestCase):
    setUpClass = classmethod(database.WebDatabaseTests.setUpClass.__func__)
    tearDownClass = classmethod(database.WebDatabaseTests.tearDownClass.__func__)
    remove_database = classmethod(database.WebDatabaseTests.remove_database.__func__)
    setUp = authentication.PublicAuthenticationTests.setUp
    request = authentication.PublicAuthenticationTests.request
    bootstrap = authentication.PublicAuthenticationTests.bootstrap
    login = authentication.PublicAuthenticationTests.login

    def template(self, *, active=True, deleted=False):
        with closing(self.psycopg2.connect(**self.settings)) as connection:
            connection.autocommit = True
            with connection.cursor() as cursor:
                cursor.execute("INSERT INTO challenge_templates(name,description,category,difficulty,creator_id,is_active,marked_for_deletion,ready_to_launch) VALUES (%s,'<script>test only</script>','web','easy',%s,%s,%s,TRUE) RETURNING id", (self.username, self.user_id, active, deleted))
                identifier = cursor.fetchone()[0]
                cursor.execute("INSERT INTO challenge_flags(challenge_template_id,flag,description,points) VALUES (%s,'not-a-public-flag','First discovery',100),(%s,'another-secret-flag','Second discovery',50) RETURNING id", (identifier, identifier))
                return identifier, [value[0] for value in cursor.fetchall()]

    def test_public_explore_hides_inactive_and_retired_exercises_without_flag_leak(self):
        visible, _ = self.template()
        hidden, _ = self.template(active=False)
        retired, _ = self.template(deleted=True)
        response = self.request('explore?search='+self.username)
        self.assertEqual(response.status_code, 200, response.json)
        data = response.json['data']
        self.assertEqual([value['id'] for value in data['challenges']], [visible])
        self.assertEqual(data['pagination']['total_items'], 1)
        self.assertNotIn('not-a-public-flag', str(data))
        self.assertNotIn('another-secret-flag', str(data))

    def test_learning_screens_require_session_and_validate_query_constraints(self):
        for endpoint in ('dashboard', 'activity', 'badges', 'announcements'):
            self.assertEqual(self.request(endpoint).status_code, 401)
        self.login()
        for endpoint in ('dashboard', 'activity', 'badges', 'announcements'):
            result = self.request(endpoint)
            self.assertEqual(result.status_code, 200, (endpoint, result.json))
            self.assertTrue(result.json['success'])
        for endpoint in ('explore?page=0','explore?sort=DROP','activity?type=unknown','announcements?importance=unknown','dashboard?data_type=unknown','dashboard?data_type=timeline&range=unknown'):
            self.assertEqual(self.request(endpoint).status_code, 400)

    def test_dashboard_does_not_count_collective_partial_flags_as_full_solves(self):
        identifier, flags = self.template()
        with closing(self.psycopg2.connect(**self.settings)) as connection:
            connection.autocommit = True
            with connection.cursor() as cursor:
                cursor.execute('SELECT id FROM api.create_user(%s,%s,%s,%s,%s)', ('other_'+self.username[4:], 'other_'+self.username+'@example.invalid', self.old_hash, self.legacy_salt, '127.0.0.1'))
                other = cursor.fetchone()[0]
                cursor.execute('INSERT INTO completed_challenges(user_id,challenge_template_id,flag_id,completed_at) VALUES (%s,%s,%s,CURRENT_TIMESTAMP),(%s,%s,%s,CURRENT_TIMESTAMP)', (self.user_id, identifier, flags[0], other, identifier, flags[1]))
        self.login()
        result = self.request('dashboard')
        self.assertEqual(result.status_code, 200, result.json)
        challenge = next(value for value in result.json['data']['challenges'] if value['id'] == identifier)
        self.assertEqual(challenge['solved_count'], 0)
        self.assertFalse(challenge['solved'])
        self.assertEqual(result.json['data']['progress']['solved'], 0)
        timeline = self.request('dashboard?data_type=timeline&range=week&view=cumulative')
        self.assertEqual(timeline.status_code, 200, timeline.json)
        self.assertEqual(len(timeline.json['data']['labels']), 7)
