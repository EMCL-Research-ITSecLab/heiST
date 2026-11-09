"""Real PostgreSQL plus real Flask boundaries; QEMU has separate native tests."""
from contextlib import closing
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.parse import urlsplit

from heist.api.internal import create_app
from heist.api.public.internal_client import ImageRejected, InternalClient
from heist.artifacts.uploads import UploadStore
from heist.artifacts.worker import process
from heist.files import write_json
from heist.platform.images import intake
from tests import test_web_artifacts as fixtures
from tests.test_ova_envelope import XML


class FlaskTransport:
    """Replace sockets only; all host auth/routes/ownership/SQL still execute."""
    def __init__(self, app):
        self.client=app.test_client()
        self.trust_env=False

    def close(self):
        pass

    def request(self,method,url,**kwargs):
        response=self.client.open(urlsplit(url).path,method=method,base_url='https://localhost',
                                  headers=kwargs['headers'],json=kwargs.get('json'),data=kwargs.get('data'))
        return Mock(status_code=response.status_code,headers=response.headers,
                    iter_content=lambda **options:iter([response.data]),close=lambda:None)


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'),'Disposable PostgreSQL administrator connection required')
class ImagePipelineTests(unittest.TestCase):
    setUpClass=classmethod(fixtures.ArtifactUploadTests.setUpClass.__func__)
    tearDownClass=classmethod(fixtures.ArtifactUploadTests.tearDownClass.__func__)
    remove_database=classmethod(fixtures.ArtifactUploadTests.remove_database.__func__)
    request=fixtures.ArtifactUploadTests.request
    bootstrap=fixtures.ArtifactUploadTests.bootstrap
    login=fixtures.ArtifactUploadTests.login
    update_user=fixtures.ArtifactUploadTests.update_user

    def setUp(self):
        fixtures.ArtifactUploadTests.setUp(self)
        self.store=UploadStore(self.root/'artifact-uploads')
        self.host=create_app({'TESTING':False,'BACKEND_AUTHENTICATION_TOKEN':'test-root-token',
            'ARTIFACT_INTAKE_DIRECTORY':str(self.root/'host-incoming'),
            'ARTIFACT_LIBRARY_DIRECTORY':str(self.root/'library'),
            'NORMALIZED_IMAGE_DIRECTORY':str(self.root/'normalized'),
            'OPERATION_DIRECTORY':str(self.root/'operations')}, {'get_db_connection':self.connect})
        self.transport=InternalClient('https://localhost','test-root-token',session=FlaskTransport(self.host))
        self.app.extensions['internal_client_factory']=lambda:InternalClient('https://localhost','test-root-token',session=FlaskTransport(self.host))
        # The independently native-tested normalizer is the only infrastructure
        # boundary replaced here. SQL registration must occur after this gate.
        self.normalizer=Mock(return_value=(self.root/'normalized',{'schema':1}))
        self.patch=patch.object(intake,'normalize',self.normalizer)
        self.patch.start();self.addCleanup(self.patch.stop)

    def connect(self):
        connection=self.psycopg2.connect(**self.settings)
        connection.autocommit=True
        return connection

    def sql(self,statement,arguments=()):
        with closing(self.connect()) as connection:
            with connection.cursor() as cursor:
                cursor.execute(statement,arguments)
                return cursor.fetchall() if cursor.description else None

    def stage(self,content=None):
        self.login()
        if content is None:
            stream=io.BytesIO()
            with tarfile.open(fileobj=stream,mode='w',format=tarfile.USTAR_FORMAT) as archive:
                for name,data in [('machine.ovf',XML),('disk.vmdk',b'disk')]:
                    item=tarfile.TarInfo(name);item.size=len(data)
                    archive.addfile(item,io.BytesIO(data))
            content=stream.getvalue()
        result=self.request('admin/artifact-uploads','POST',json={'name':'pipeline.ova','size':len(content),'guest_os':'linux'})
        self.assertEqual(result.status_code,201,result.json)
        identifier=result.json['data']['id']
        path='admin/artifact-uploads/'+identifier
        self.assertEqual(self.request(path+'/chunks/0','PUT',data=content,content_type='application/octet-stream').status_code,200)
        self.assertEqual(self.request(path+'/seal','POST').status_code,202)
        return identifier

    def test_verified_host_publication_registers_once_and_releases_web_staging(self):
        identifier=self.stage()
        self.assertTrue(process(self.store,self.transport,self.user_id,identifier))
        self.assertFalse(process(self.store,self.transport,self.user_id,identifier))
        self.normalizer.assert_called_once()
        value=self.request('admin/artifacts').json['data']
        self.assertEqual(len(value['ovas']),1)
        self.assertEqual(value['ovas'][0]['display_name'],'pipeline')
        self.assertTrue(value['ovas'][0]['is_available'])
        self.assertEqual(self.store.status(self.user_id,identifier)['state'],'READY')
        self.assertFalse((self.root/'artifact-uploads'/str(self.user_id)/identifier/'payload.ova').exists())
        self.assertEqual(len(list((self.root/'library').glob('*.ova'))),1)

    def test_operator_yaml_import_binds_the_actual_published_image_through_both_apis(self):
        from tools.challenges.setup_challenge import setup_challenge
        identifier = self.stage()
        self.assertTrue(process(self.store, self.transport, self.user_id, identifier))
        artifact = self.repo.call('get_user_available_disk_files', self.user_id)[0]
        self.assertEqual(artifact['display_name'], 'pipeline')
        imports = []

        def import_templates(template, connection, _pool):
            # Only the hypervisor boundary is replaced. Auth, YAML parsing,
            # image ownership, definition writes and readiness use real APIs/SQL.
            with connection.cursor() as cursor:
                cursor.execute('SELECT disk_file_id FROM machine_templates WHERE challenge_template_id=%s', (template,))
                self.assertEqual(cursor.fetchall(), [(artifact['id'],)])
                cursor.execute('UPDATE challenge_templates SET ready_to_launch=TRUE WHERE id=%s', (template,))
            imports.append(template)

        self.host = create_app({**self.host.config, 'TEMPLATE_LOCK_DIRECTORY': str(self.root/'template-locks')},
                               {'get_db_connection': self.connect, 'import_machine_templates': import_templates})
        path = self.root/'exercise.yaml'
        path.write_text('''ctf:
  name: Published image import
  description: Exercise created through the operator helper
  category: misc
  difficulty: easy
  is_active: false
  vms:
    gateway:
      ova_name: pipeline
      cores: 1
      ram_gb: 1
      domain_name: gateway.lab
  subnets:
    students:
      accessible: true
      attached_vms: [gateway]
  flags:
    checkpoint:
      flag: fixture-owned-flag
      points: 1
''')
        def transport(_session, method, endpoint, **arguments):
            response = self.request(endpoint.removeprefix('/api/'), method, json=arguments.get('json'))
            if response.status_code >= 400:
                raise RuntimeError(str(response.json))
            return response.json

        with patch('tools.challenges.setup_challenge.request', side_effect=transport):
            template = setup_challenge(object(), path, upload_ovas=False)
        self.assertEqual(imports, [template])
        self.assertEqual(self.sql('SELECT is_active,ready_to_launch FROM challenge_templates WHERE id=%s', (template,)),
                         [(False, True)])
        self.assertEqual(self.sql('SELECT count(*) FROM network_templates WHERE challenge_template_id=%s', (template,)), [(1,)])

    def test_response_loss_after_database_commit_resumes_same_identity_without_duplicate_image(self):
        identifier=self.stage()
        original=write_json
        def interrupted(path,value):
            if value.get('state')=='READY':
                raise OSError('receipt storage interrupted after commit')
            original(path,value)
        with patch.object(intake,'write_json',side_effect=interrupted):
            self.assertFalse(process(self.store,self.transport,self.user_id,identifier))
        self.assertEqual(self.sql('SELECT COUNT(*) FROM disk_files WHERE user_id=%s',(self.user_id,)),[(1,)])
        with self.store.session(self.user_id,identifier) as (directory,value):
            value['next_attempt']=0;write_json(directory/'metadata.json',value)
        self.assertTrue(process(self.store,self.transport,self.user_id,identifier))
        self.assertEqual(self.sql('SELECT COUNT(*) FROM disk_files WHERE user_id=%s',(self.user_id,)),[(1,)])

    def test_invalid_envelope_never_reaches_host_and_expired_receiving_transfer_is_removed(self):
        identifier=self.stage(b'invalid archive')
        self.assertFalse(process(self.store,self.transport,self.user_id,identifier))
        self.normalizer.assert_not_called()
        self.assertEqual(self.store.status(self.user_id,identifier)['state'],'FAILED')
        self.assertEqual(self.sql('SELECT COUNT(*) FROM disk_files WHERE user_id=%s',(self.user_id,)),[(0,)])
        pending=self.store.create(self.user_id,'unfinished.ova',4,'linux')['id']
        self.store.put(self.user_id,pending,0,io.BytesIO(b'disk'))
        self.store.clock=lambda:10**12
        self.assertEqual(self.store.expire(self.user_id),1)
        self.assertEqual(self.store.status(self.user_id,pending)['state'],'CANCELLED')
        self.assertFalse((self.store.root/str(self.user_id)/pending/'0.chunk').exists())

    def test_retirement_refuses_referenced_image_then_disables_reuse_and_preserves_recovery_copy(self):
        identifier=self.stage()
        self.assertTrue(process(self.store,self.transport,self.user_id,identifier))
        artifact=self.sql('SELECT id FROM disk_files WHERE user_id=%s',(self.user_id,))[0][0]
        template=self.sql("INSERT INTO challenge_templates(name,category,difficulty,creator_id) VALUES('image-use','web','easy',%s) RETURNING id",(self.user_id,))[0][0]
        machine=self.repo.scalar('create_machine_template',template,'gateway',artifact,1,1,'none')
        rejected=self.request('admin/artifacts/'+str(artifact),'DELETE')
        self.assertEqual(rejected.status_code,409,rejected.json)
        self.assertTrue(self.repo.call('web_disk_files',self.user_id)[0]['is_available'])
        self.sql('DELETE FROM machine_templates WHERE id=%s',(machine,))
        result=self.request('admin/artifacts/'+str(artifact),'DELETE')
        self.assertEqual(result.status_code,200,result.json)
        self.assertEqual(self.repo.call('get_user_available_disk_files',self.user_id),[])
        self.assertEqual(len(list((self.root/'library').glob('.retired-*'))),1)
        self.assertEqual(self.request('admin/artifacts/'+str(artifact),'DELETE').status_code,404)
        # A delayed replay of the old publication cannot recreate a retired row.
        with self.store.session(self.user_id,identifier) as (_,metadata):
            checksum=metadata['sha256']
        with self.assertRaises(ImageRejected):
            self.transport.artifact_request(self.user_id,identifier,'publish',payload={'sha256':checksum})
