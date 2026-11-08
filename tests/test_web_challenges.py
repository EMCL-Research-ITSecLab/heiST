"""Real PostgreSQL contracts for grading, challenge ownership and lab timing."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
import hashlib
import hmac
import os
import unittest
from unittest.mock import Mock, patch

from tests import test_web_auth as auth_tests
from tests import test_web_learning as learning_tests
from heist.platform.challenges import stop


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'), 'Disposable PostgreSQL administrator connection required')
class ChallengeTests(unittest.TestCase):
    setUpClass = classmethod(auth_tests.PublicAuthenticationTests.setUpClass.__func__)
    tearDownClass = classmethod(auth_tests.PublicAuthenticationTests.tearDownClass.__func__)
    remove_database = classmethod(auth_tests.PublicAuthenticationTests.remove_database.__func__)
    request = auth_tests.PublicAuthenticationTests.request
    bootstrap = auth_tests.PublicAuthenticationTests.bootstrap
    login = auth_tests.PublicAuthenticationTests.login
    template = learning_tests.LearningViewsTests.template

    def setUp(self):
        auth_tests.PublicAuthenticationTests.setUp(self)
        self.platform = Mock()
        self.app.extensions['internal_client_factory'] = lambda: self.platform
        self.identifier, self.flags = self.template()
        self.sql('UPDATE challenge_templates SET solution=%s WHERE id=%s', ('private-tutor-solution', self.identifier))

    def sql(self, statement, arguments=()):
        with closing(self.psycopg2.connect(**self.settings)) as connection:
            connection.autocommit = True
            with connection.cursor() as cursor:
                cursor.execute(statement, arguments)
                return cursor.fetchall() if cursor.description else None

    def instance(self):
        identifier = self.sql("INSERT INTO challenges(challenge_template_id,subnet,lifecycle_state,pre_assigned_user_id,expires_at) VALUES (%s,NULL,'ACTIVE',%s,CURRENT_TIMESTAMP+INTERVAL '30 minutes') RETURNING id", (self.identifier, self.user_id))[0][0]
        self.sql('UPDATE users SET running_challenge=%s WHERE id=%s', (identifier, self.user_id))
        return identifier

    def action(self, action, **values):
        return self.request('challenge', 'POST', json={'action': action, 'challenge_id': self.identifier, **values})

    def test_read_contract_has_no_flag_values_and_solution_unlocks_only_after_full_completion(self):
        self.assertEqual(self.request('challenge?id='+str(self.identifier)).status_code, 401)
        self.login()
        response = self.request('challenge?id='+str(self.identifier))
        self.assertEqual(response.status_code, 200, response.json)
        self.assertNotIn('not-a-public-flag', str(response.json))
        self.assertNotIn('private-tutor-solution', str(response.json))
        self.assertEqual(response.json['challenge']['flags_total'], 2)
        self.assertEqual(self.action('submit_flag', flag='wrong').status_code, 400)
        result = self.action('submit_flag', flag='not-a-public-flag')
        self.assertEqual(result.status_code, 200, result.json)
        self.assertFalse(result.json['is_complete'])
        self.assertEqual(self.action('submit_flag', flag='not-a-public-flag').status_code, 409)
        partial = self.request('challenge?id='+str(self.identifier)).json['challenge']
        self.assertEqual(partial['user_points'], 100)
        self.assertEqual(partial['flags_submitted'], 1)
        self.assertFalse(partial['isSolved'])
        result = self.action('submit_flag', flag='another-secret-flag')
        self.assertEqual(result.status_code, 200, result.json)
        self.assertTrue(result.json['is_complete'])
        solved = self.request('challenge?id='+str(self.identifier)).json['challenge']
        self.assertTrue(solved['isSolved'])
        self.assertEqual(solved['solution'], 'private-tutor-solution')
        self.assertEqual(solved['user_points'], 150)
        self.assertEqual(solved['leaderboard'][0]['username'], self.username)
        self.platform.request.assert_not_called()

    def test_drafts_and_retired_exercises_are_hidden_from_unrelated_students(self):
        self.login()
        self.sql('UPDATE challenge_templates SET creator_id=NULL,is_active=FALSE WHERE id=%s', (self.identifier,))
        self.assertEqual(self.request('challenge?id='+str(self.identifier)).status_code, 404)
        self.assertEqual(self.action('deploy').status_code, 404)
        self.sql('UPDATE challenge_templates SET is_active=TRUE,marked_for_deletion=TRUE WHERE id=%s', (self.identifier,))
        self.assertEqual(self.request('challenge?id='+str(self.identifier)).status_code, 404)
        self.platform.request.assert_not_called()

    def test_zero_flag_exercises_are_not_automatically_solved(self):
        self.sql('DELETE FROM challenge_flags WHERE challenge_template_id=%s', (self.identifier,))
        self.login()
        response = self.request('challenge?id='+str(self.identifier))
        self.assertFalse(response.json['challenge']['isSolved'])
        self.assertNotIn('private-tutor-solution', str(response.json))

    def test_hint_thresholds_and_user_specific_flags_respect_own_identity(self):
        self.sql("INSERT INTO challenge_hints(challenge_template_id,hint_text,unlock_points) VALUES (%s,'unlocked-hint',100)", (self.identifier,))
        self.sql('UPDATE challenge_flags SET user_specific=TRUE WHERE id=%s', (self.flags[1],))
        unique = self.sql('SELECT unique_id FROM users WHERE id=%s', (self.user_id,))[0][0]
        personal = 'ITSEC{'+hmac.new(b'another-secret-flag', unique.encode(), hashlib.sha1).hexdigest()+'}'
        self.login()
        self.assertEqual(self.request('challenge?id='+str(self.identifier)).json['challenge']['hints'], [])
        self.assertEqual(self.action('submit_flag', flag='another-secret-flag').status_code, 400)
        self.assertEqual(self.action('submit_flag', flag='not-a-public-flag').status_code, 200)
        self.assertEqual(self.request('challenge?id='+str(self.identifier)).json['challenge']['hints'][0]['hint_text'], 'unlocked-hint')
        self.assertEqual(self.action('submit_flag', flag=personal).status_code, 200)

    def test_flag_writer_matches_unique_id_and_legacy_email_graders_without_changing_grades(self):
        from heist.platform.challenges.launch import resolve_user_specific_flag
        self.sql('UPDATE challenge_flags SET user_specific=TRUE WHERE id=%s', (self.flags[1],))
        email, unique = self.sql('SELECT email,unique_id FROM users WHERE id=%s', (self.user_id,))[0]
        original = self.sql("SELECT pg_get_functiondef('api.validate_and_lock_flag(bigint,text,bigint)'::regprocedure)")[0][0]
        grades_before = self.sql('SELECT count(*) FROM completed_challenges WHERE user_id=%s', (self.user_id,))
        try:
            for identity in ('unique_id', 'email'):
                definition = original.replace('SELECT u.unique_id INTO', 'SELECT u.' + identity + ' INTO')
                self.sql(definition)
                with closing(self.psycopg2.connect(**self.settings)) as connection:
                    result = resolve_user_specific_flag(connection, template_id=self.identifier,
                        flag={'id': self.flags[1], 'flag': 'another-secret-flag'}, user_id=self.user_id,
                        user_email=email, user_unique_id=unique)
                    expected_identity = unique if identity == 'unique_id' else email
                    expected = 'ITSEC{' + hmac.new(b'another-secret-flag', expected_identity.encode(), hashlib.sha1).hexdigest() + '}'
                    self.assertEqual(result, expected)
                    for change in ({'user_id': -1}, {'flag': {'id': self.flags[0], 'flag': 'another-secret-flag'}},
                                   {'user_email': 'someone-else@example.invalid', 'user_unique_id': 'someone-else'}):
                        arguments = dict(template_id=self.identifier, flag={'id': self.flags[1], 'flag': 'another-secret-flag'},
                                         user_id=self.user_id, user_email=email, user_unique_id=unique)
                        arguments.update(change)
                        with self.assertRaisesRegex(RuntimeError, 'does not match'):
                            resolve_user_specific_flag(connection, **arguments)
        finally:
            self.sql(original)
        self.assertEqual(self.sql('SELECT count(*) FROM completed_challenges WHERE user_id=%s', (self.user_id,)), grades_before)

    def test_deploy_and_cancel_are_bound_to_session_and_never_stop_another_template(self):
        self.login()
        def operation(name, payload):
            if name == 'start':
                self.instance()
                return {'success': True, 'entrypoints': ['10.128.1.0/24']}
            self.assertEqual(name, 'stop')
            self.sql('UPDATE users SET running_challenge=NULL WHERE id=%s', (self.user_id,))
            return {'success': True}
        self.platform.request.side_effect = operation
        result = self.action('deploy', user_id=self.user_id+1)
        self.assertEqual(result.status_code, 200, result.json)
        self.platform.request.assert_called_with('start', {'user_id': self.user_id, 'challenge_template_id': self.identifier})
        self.assertEqual(self.action('deploy').status_code, 409)
        other, _ = self.template()
        result = self.request('challenge', 'POST', json={'action': 'cancel', 'challenge_id': other})
        self.assertEqual(result.status_code, 409)
        self.assertEqual(self.action('cancel').status_code, 200)
        self.platform.request.assert_called_with('stop', {'user_id': self.user_id})

    def test_extension_adds_hour_preserves_remaining_time_and_enforces_expiry_and_limit(self):
        instance = self.instance()
        self.login()
        before = self.sql('SELECT expires_at FROM challenges WHERE id=%s', (instance,))[0][0]
        result = self.action('extend_time')
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(result.json['remaining_extensions'], 5)
        after = self.sql('SELECT expires_at FROM challenges WHERE id=%s', (instance,))[0][0]
        self.assertEqual((after-before).total_seconds(), 3600)
        self.sql('UPDATE challenges SET used_extensions=6 WHERE id=%s', (instance,))
        self.assertEqual(self.action('extend_time').status_code, 409)
        self.sql("UPDATE challenges SET used_extensions=0, expires_at=CURRENT_TIMESTAMP-INTERVAL '1 second' WHERE id=%s", (instance,))
        self.assertEqual(self.action('extend_time').status_code, 409)

    def test_same_flag_concurrent_requests_award_points_once(self):
        self.login()
        cookie = self.client.get_cookie('__Host-heist_session').value
        def submit(_):
            client = self.app.test_client()
            client.set_cookie('__Host-heist_session', cookie, secure=True)
            return client.post('/api/challenge', base_url='https://localhost', headers={'X-CSRF-Token': self.token},
                               json={'action': 'submit_flag', 'challenge_id': self.identifier, 'flag': 'not-a-public-flag'}).status_code
        with ThreadPoolExecutor(max_workers=2) as workers:
            self.assertEqual(sorted(workers.map(submit, (1, 2))), [200, 409])
        self.assertEqual(self.repo.scalar('get_user_submitted_flags_count_for_challenge', self.user_id, self.identifier), 1)
        self.assertEqual(self.repo.call('get_profile_stats', self.user_id, one=True)['total_points'], 100)

    def test_platform_stop_closes_trace_attempt_and_assignment_together_and_rolls_back_failure(self):
        instance = self.instance()
        network = self.sql("INSERT INTO network_templates(challenge_template_id,name,accessible) VALUES (%s,'entry',TRUE) RETURNING id", (self.identifier,))[0][0]
        self.sql("INSERT INTO networks(network_template_id,challenge_id,subnet,host_device) VALUES (%s,%s,'10.128.1.0/24','test0')", (network, instance))
        self.repo.call('create_new_challenge_attempt', self.user_id, self.identifier)
        self.repo.call('start_user_network_trace', self.user_id, self.identifier)
        @contextmanager
        def connection():
            with closing(self.psycopg2.connect(**self.settings)) as value:
                value.autocommit = True
                yield value
        with patch.object(stop, 'db_connection_context', connection), patch.object(stop, 'remove_user_iptables_rules', side_effect=RuntimeError('firewall unavailable')):
            with self.assertRaises(RuntimeError):
                stop.stop_challenge(self.user_id)
        self.assertEqual(self.repo.scalar('get_user_running_challenge', self.user_id), instance)
        self.assertIsNone(self.sql('SELECT stopped_at FROM user_network_trace WHERE username=%s', (self.username,))[0][0])
        with patch.object(stop, 'db_connection_context', connection), patch.object(stop, 'remove_user_iptables_rules'):
            stop.stop_challenge(self.user_id)
            stop.stop_challenge(self.user_id)  # idempotent after success
        self.assertIsNone(self.repo.scalar('get_user_running_challenge', self.user_id))
        self.assertEqual(self.sql('SELECT lifecycle_state FROM challenges WHERE id=%s', (instance,))[0][0], 'EXPIRED')
        self.assertIsNotNone(self.sql('SELECT stopped_at FROM user_network_trace WHERE username=%s', (self.username,))[0][0])
        self.assertEqual(self.sql('SELECT COUNT(*) FROM completed_challenges WHERE user_id=%s AND completed_at IS NULL', (self.user_id,))[0][0], 0)

    def test_different_final_flags_racing_across_students_award_first_blood_once(self):
        self.sql("INSERT INTO badges(id,name,rarity,requirements) VALUES (7,'First Blood','rare','First full solve') ON CONFLICT DO NOTHING")
        other_name = 'race_'+self.username[4:]
        other_id = self.sql('SELECT id FROM api.create_user(%s,%s,%s,%s,%s)', (other_name, other_name+'@example.invalid', self.old_hash, self.legacy_salt, '127.0.0.1'))[0][0]
        self.sql('INSERT INTO completed_challenges(user_id,challenge_template_id,flag_id,completed_at) VALUES (%s,%s,%s,CURRENT_TIMESTAMP),(%s,%s,%s,CURRENT_TIMESTAMP)',
                 (self.user_id, self.identifier, self.flags[0], other_id, self.identifier, self.flags[1]))
        self.login()
        second = self.app.test_client()
        bootstrap = second.get('/api/session', base_url='https://localhost')
        token = bootstrap.json['data']['csrf_token']
        response = second.post('/api/login', base_url='https://localhost', headers={'X-CSRF-Token': token}, json={'username': other_name, 'password': 'legacy-password'})
        self.assertEqual(response.status_code, 200)
        second_token = response.json['csrf_token']
        def submit(value):
            client, token, flag = value
            return client.post('/api/challenge', base_url='https://localhost', headers={'X-CSRF-Token': token},
                               json={'action': 'submit_flag', 'challenge_id': self.identifier, 'flag': flag})
        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(submit, [(self.client, self.token, 'another-secret-flag'), (second, second_token, 'not-a-public-flag')]))
        self.assertEqual([result.status_code for result in results], [200, 200], [result.json for result in results])
        self.assertEqual(sum('First Blood' in result.json['badges'] for result in results), 1)
        self.assertEqual(self.sql('SELECT COUNT(*) FROM user_badges WHERE badge_id=7 AND user_id=ANY(%s)', ([self.user_id, other_id],))[0][0], 1)

    def test_elapsed_time_stops_at_this_students_last_flag_and_ignores_other_completions(self):
        other_name = 'time_'+self.username[4:]
        other_id = self.sql('SELECT id FROM api.create_user(%s,%s,%s,%s,%s)', (other_name, other_name+'@example.invalid', self.old_hash, self.legacy_salt, '127.0.0.1'))[0][0]
        self.sql("INSERT INTO completed_challenges(user_id,challenge_template_id,flag_id,started_at,completed_at) VALUES (%s,%s,%s,CURRENT_TIMESTAMP-INTERVAL '20 minutes',CURRENT_TIMESTAMP-INTERVAL '19 minutes'),(%s,%s,%s,CURRENT_TIMESTAMP-INTERVAL '18 minutes',CURRENT_TIMESTAMP-INTERVAL '17 minutes'),(%s,%s,NULL,CURRENT_TIMESTAMP-INTERVAL '5 minutes',CURRENT_TIMESTAMP-INTERVAL '4 minutes'),(%s,%s,%s,CURRENT_TIMESTAMP-INTERVAL '2 minutes',CURRENT_TIMESTAMP-INTERVAL '1 minute')",
                 (self.user_id,self.identifier,self.flags[0], self.user_id,self.identifier,self.flags[1], self.user_id,self.identifier, other_id,self.identifier,self.flags[0]))
        self.assertEqual(self.repo.scalar('get_elapsed_seconds_for_challenge', self.user_id, self.identifier), 120)
