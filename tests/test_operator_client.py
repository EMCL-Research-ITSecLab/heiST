"""Prepared-request contracts for operator imports against the Flask upload protocol."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

import requests
from requests.adapters import BaseAdapter

from tools.challenges.get_authenticated_session import get_authenticated_session
from tools.challenges.upload_ova_file import ArtifactPending, upload_ova_file
from tools.challenges.client import request


class BrowserAPI(BaseAdapter):
    def __init__(self):
        self.calls = []
        self.chunks = []
        self.state = 'READY'
        self.redirect = False

    def send(self, prepared, **kwargs):
        self.calls.append(prepared)
        response = requests.Response()
        response.request = prepared
        response.status_code = 200
        response.headers['Content-Type'] = 'application/json'
        path = urlsplit(prepared.url).path
        assert kwargs['verify'] == '/trusted/fixture-ca.pem'
        if self.redirect:
            response.status_code = 302
            response.headers['Location'] = 'https://other.invalid/steal'
            result = {}
        elif path == '/api/session':
            result = {'success': True, 'data': {'csrf_token': 'a'*64}}
        elif path == '/api/login':
            assert prepared.headers['X-CSRF-Token'] == 'a'*64
            assert prepared.headers['Origin'] == 'https://heist.invalid'
            result = {'success': True, 'csrf_token': 'b'*64}
        else:
            assert prepared.headers['X-CSRF-Token'] == 'b'*64
            result = {'success': True}
            if path == '/api/admin/artifacts':
                result['data'] = {'limits': {'MAX_FILE_SIZE': 100}}
            elif path == '/api/admin/artifact-uploads':
                response.status_code = 201
                result['data'] = {'id': 'c'*32, 'chunk_bytes': 5}
            elif '/chunks/' in path:
                assert prepared.method == 'PUT'
                assert prepared.headers['Content-Type'] == 'application/octet-stream'
                self.chunks.append(prepared.body)
            elif path.endswith('/seal'):
                response.status_code = 202
                result['data'] = {'state': 'SEALED'}
            elif path == '/api/admin/artifact-uploads/'+'c'*32:
                result['data'] = {'state': self.state, 'artifact_id': 17}
        response._content = json.dumps(result).encode()
        return response

    def close(self):
        pass


class OperatorClientTests(unittest.TestCase):
    def setUp(self):
        self.adapter = BrowserAPI()
        self.session = requests.Session()
        self.session.mount('https://', self.adapter)
        with patch('requests.Session', return_value=self.session):
            self.client = get_authenticated_session('operator', 'test-only', base_url='https://heist.invalid', ca_file='/trusted/fixture-ca.pem')
        self.addCleanup(self.session.close)
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.image = Path(self.temporary.name)/'fixture.ova'
        self.image.write_bytes(b'abcdefghijkl')

    def test_rotated_csrf_raw_server_sized_chunks_and_confirmed_publication(self):
        self.assertEqual(upload_ova_file(self.image, self.client), 17)
        self.assertEqual(self.adapter.chunks, [b'abcde', b'fghij', b'kl'])
        self.assertEqual([call.method for call in self.adapter.calls], ['GET','POST','GET','POST','PUT','PUT','PUT','POST','GET'])
        self.assertTrue(all('/api/' in call.url for call in self.adapter.calls))

    def test_sealing_does_not_report_success_or_start_another_upload_on_timeout(self):
        self.adapter.state = 'PROCESSING'
        ticks = iter([0, 2])
        with self.assertRaisesRegex(ArtifactPending, 'inspect this receipt'):
            upload_ova_file(self.image, self.client, timeout=1, clock=lambda: next(ticks))
        self.assertEqual(sum(call.url.endswith('/api/admin/artifact-uploads') for call in self.adapter.calls), 1)
        self.assertEqual(sum(call.url.endswith('/seal') for call in self.adapter.calls), 1)

    def test_yaml_alias_and_published_artifact_use_the_same_canonical_filename(self):
        from tools.challenges.yaml_parser import yaml_to_create_challenge_form_data
        path=Path(self.temporary.name)/'exercise.yaml'
        path.write_text('ctf:\n  vms:\n    portal:\n      ova_name: portal-base\n')
        definition=yaml_to_create_challenge_form_data(path)
        upload_ova_file(self.image,self.client,target_filename='portal-base')
        created=next(call for call in self.adapter.calls if call.method=='POST' and call.url.endswith('/api/admin/artifact-uploads'))
        self.assertEqual(json.loads(created.body)['name'],json.loads(definition['vms'])[0]['ova_name'])
        self.assertEqual(json.loads(created.body)['name'],'portal-base.ova')

    def test_redirects_and_invalid_paths_cannot_forward_operator_credentials(self):
        self.adapter.redirect = True
        before = len(self.adapter.calls)
        with self.assertRaisesRegex(RuntimeError, 'HTTP 302'):
            request(self.client, 'POST', '/api/admin/challenges', json={})
        self.assertEqual(len(self.adapter.calls), before+1)
        self.assertTrue(all(urlsplit(call.url).hostname == 'heist.invalid' for call in self.adapter.calls))
        for path in ('https://evil.invalid/api/test','/api/../admin','/api/%2e%2e/admin'):
            with self.assertRaises(ValueError):request(self.client,'POST',path,json={})
        self.client.verify = False
        with self.assertRaisesRegex(ValueError, 'TLS'):request(self.client,'GET','/api/session')
