"""Delegated grading remains transactional, attributed, and restricted to admins."""
import csv
import io
import os
import unittest
from tests import test_web_challenges as challenges


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'), 'Disposable PostgreSQL required')
class GradingTests(unittest.TestCase):
    setUpClass=classmethod(challenges.ChallengeTests.setUpClass.__func__)
    tearDownClass=classmethod(challenges.ChallengeTests.tearDownClass.__func__)
    remove_database=classmethod(challenges.ChallengeTests.remove_database.__func__)
    setUp=challenges.ChallengeTests.setUp
    sql=challenges.ChallengeTests.sql
    template=challenges.ChallengeTests.template
    request=challenges.ChallengeTests.request
    bootstrap=challenges.ChallengeTests.bootstrap
    login=challenges.ChallengeTests.login

    def test_delegated_submission_csv_duplicate_and_role_revocation(self):
        path='admin/grading/submissions'
        self.assertEqual(self.request('admin/grading/submissions.csv').status_code,401)
        self.login()
        values={'user_id':self.user_id,'challenge_id':self.identifier,'flag':'not-a-public-flag',
                'confirmation':self.username,'reason':'Student requested help after a browser failure'}
        self.assertEqual(self.request(path,'POST',json=values).status_code,403)
        self.sql('UPDATE users SET is_admin=TRUE WHERE id=%s',(self.user_id,))
        self.assertEqual(self.request(path,'POST',json={**values,'confirmation':'wrong'}).status_code,400)
        self.assertEqual(self.request(path,'POST',json={**values,'flag':'wrong'}).status_code,400)
        self.assertEqual(self.request(path,'POST',json=values).status_code,200)
        self.assertEqual(self.request(path,'POST',json=values).status_code,409)
        self.assertEqual(self.sql('SELECT actor_id,user_id,flag_id FROM administrator_flag_submissions'),[(self.user_id,self.user_id,self.flags[0])])
        exported=self.request('admin/grading/submissions.csv?challenge_id='+str(self.identifier))
        self.assertEqual(exported.status_code,200)
        self.assertIn('no-store',exported.headers['Cache-Control'])
        contents=list(csv.DictReader(io.StringIO(exported.text)))
        self.assertEqual(len(contents),1)
        self.assertEqual(contents[0]['administrator'],self.username)
        self.assertNotIn('not-a-public-flag',exported.text)
        moodle=self.request(f'admin/grading/submissions.csv?format=moodle&challenge_id={self.identifier}')
        self.assertEqual(list(csv.DictReader(io.StringIO(moodle.text)))[0]['Grade'],'100')
        self.assertEqual(self.request('admin/grading/submissions.csv?format=moodle').status_code,400)
        self.sql('UPDATE users SET is_admin=FALSE WHERE id=%s',(self.user_id,))
        self.assertEqual(self.request('admin/grading/submissions.csv').status_code,403)

    def test_audit_failure_rolls_back_grading_and_exports_neutralize_formulas(self):
        from unittest.mock import patch
        from heist.api.public.grading import csv_cell
        for value in ['=SUM(A1)', ' +cmd', '@test', '\tcommand']:
            self.assertTrue(csv_cell(value).startswith("'"))
        self.login();self.sql('UPDATE users SET is_admin=TRUE WHERE id=%s',(self.user_id,))
        from heist.api.public.repository import Repository
        original=Repository.call
        def fail(repo,function,*args,**kwargs):
            if function=='web_admin_record_submission':raise ValueError('audit unavailable')
            return original(repo,function,*args,**kwargs)
        with patch.object(Repository,'call',fail):
            response=self.request('admin/grading/submissions','POST',json={'user_id':self.user_id,'challenge_id':self.identifier,
                'flag':'not-a-public-flag','confirmation':self.username,'reason':'Student requested manual assistance'})
            self.assertEqual(response.status_code,503)
        self.assertEqual(self.sql('SELECT count(*) FROM completed_challenges WHERE user_id=%s AND flag_id IS NOT NULL',(self.user_id,)),[(0,)])

    def test_personal_flags_are_checked_against_target_student_not_admin(self):
        import hashlib
        import hmac
        target_name='s_'+self.username
        target=self.sql("SELECT id FROM api.create_user(%s,%s,%s,%s,'127.0.0.1')",(target_name,target_name+'@example.invalid',self.old_hash,self.legacy_salt))[0][0]
        self.sql('UPDATE challenge_flags SET user_specific=TRUE WHERE id=%s',(self.flags[1],))
        unique=self.sql('SELECT unique_id FROM users WHERE id=%s',(target,))[0][0]
        personal='ITSEC{'+hmac.new(b'another-secret-flag',unique.encode(),hashlib.sha1).hexdigest()+'}'
        self.login();self.sql('UPDATE users SET is_admin=TRUE WHERE id=%s',(self.user_id,))
        response=self.request('admin/grading/submissions','POST',json={'user_id':target,'challenge_id':self.identifier,
            'flag':personal,'confirmation':target_name,'reason':'Student needs help submitting recovered personal flag'})
        self.assertEqual(response.status_code,200,response.json)
        self.assertEqual(self.sql('SELECT actor_id,user_id FROM administrator_flag_submissions WHERE user_id=%s',(target,)),[(self.user_id,target)])
