"""Definition validation rejects unsafe topology before any provisioning boundary."""
from copy import deepcopy
import unittest
from heist.platform.challenges.definition import DefinitionError, definition


def exercise():
    return {'name': 'Practice lab', 'description': 'Investigate the target', 'category': 'web', 'difficulty': 'easy', 'isActive': 'true',
            'vms': [{'name': 'target', 'ova_name': 'Debian', 'cores': 1, 'ram_gb': 1, 'domain_name': 'lab.test', 'ad_role': 'none'}],
            'subnets': [{'name': 'entry', 'attached_vms': ['target'], 'accessible': True, 'dmz': False}],
            'flags': [{'flag': 'flag-value', 'points': 100, 'order_index': 0, 'user_specific': False}], 'hints': []}


class DefinitionTests(unittest.TestCase):
    def setUp(self):
        self.artifacts = [{'id': 42, 'display_name': 'Debian', 'guest_os': 'linux'}, {'id': 43, 'display_name': 'Windows', 'guest_os': 'windows'}]

    def test_valid_definition_normalizes_form_json_and_owned_artifact_identity(self):
        import json
        source = exercise()
        for name in ('vms', 'subnets', 'flags', 'hints'):
            source[name] = json.dumps(source[name])
        result = definition(source, self.artifacts)
        self.assertTrue(result['is_active'])
        self.assertEqual(result['machines'][0]['disk_file_id'], 42)
        self.assertEqual(result['machines'][0]['domain_name'], 'lab.test')
        self.assertIsNone(result['flags'][0]['vm_name'])

    def test_unknown_foreign_images_bounds_duplicates_and_nonboolean_values_are_rejected(self):
        samples = []
        source = exercise(); source['vms'][0]['ova_name'] = 'Foreign image'; samples.append(source)
        source = exercise(); source['vms'][0]['cores'] = True; samples.append(source)
        source = exercise(); source['vms'][0]['ram_gb'] = 33; samples.append(source)
        source = exercise(); source['vms'][0]['name'] = 'name;exec'; samples.append(source)
        source = exercise(); source['subnets'][0]['attached_vms'] = ['unknown']; samples.append(source)
        source = exercise(); source['subnets'][0]['accessible'] = 'yes'; samples.append(source)
        source = exercise(); source['flags'] *= 2; samples.append(source)
        source = exercise(); source['vms'] = []; samples.append(source)
        source = exercise(); source['isActive'] = 1; samples.append(source)
        source = exercise(); source['flags'][0]['user_specific'] = True; samples.append(source)
        for sample in samples:
            with self.subTest(source=sample), self.assertRaises(DefinitionError):
                definition(sample, self.artifacts)

    def test_reachability_allows_multihomed_pivot_but_rejects_disconnected_machine(self):
        source = exercise()
        source['vms'].append({**source['vms'][0], 'name': 'hidden'})
        source['subnets'].append({'name': 'inside', 'attached_vms': ['target', 'hidden'], 'accessible': False})
        self.assertEqual(len(definition(source, self.artifacts)['machines']), 2)
        source['subnets'][1]['attached_vms'] = ['hidden']
        with self.assertRaisesRegex(DefinitionError, 'path'):
            definition(source, self.artifacts)

    def test_ad_members_require_windows_and_one_shared_domain_controller(self):
        source = exercise()
        source['vms'][0].update(ova_name='Windows', ad_role='dc', name='dc')
        source['vms'].append({**source['vms'][0], 'name': 'member', 'ad_role': 'member'})
        source['subnets'][0]['attached_vms'] = ['dc', 'member']
        self.assertEqual(len(definition(source, self.artifacts)['machines']), 2)
        for change in ({'domain_name': 'other.test'}, {'ova_name': 'Debian'}, {'ad_role': 'dc'}):
            invalid = deepcopy(source)
            invalid['vms'][1].update(change)
            with self.subTest(change=change), self.assertRaises(DefinitionError):
                definition(invalid, self.artifacts)
        source['vms'][0]['ad_role'] = 'none'
        with self.assertRaises(DefinitionError):
            definition(source, self.artifacts)


class YamlDefinitionTests(unittest.TestCase):
    def test_legacy_mapping_import_preserves_topology_flags_and_hints_without_local_paths(self):
        import yaml
        from heist.platform.challenges.yaml_definition import parse_yaml
        source = exercise()
        ctf = {k:v for k,v in source.items() if k not in ('vms','subnets','flags','hints','isActive')}
        ctf.update(is_active=True,vms={'target':{**source['vms'][0],'ova_path':'/private/instructor.ova'}},
                   subnets={'entry':source['subnets'][0]},flags={'first':source['flags'][0]},
                   hints={'first':{'hint_text':'Check the service','unlock_points':0}})
        result = parse_yaml(yaml.safe_dump({'ctf':ctf}))
        self.assertNotIn('ova_path',result['vms'][0])
        self.assertEqual(result['subnets'][0]['attached_vms'],['target'])
        self.assertEqual(result['hints'][0]['order_index'],0)
        parsed = definition(result,[{'id':42,'display_name':'Debian','guest_os':'linux'}])
        self.assertEqual(parsed['machines'][0]['disk_file_id'],42)
        self.assertTrue(parsed['is_active'])

    def test_unsafe_ambiguous_or_unbounded_yaml_is_refused(self):
        from heist.platform.challenges.yaml_definition import parse_yaml
        for source in ('ctf: !!python/object:os.system {}','ctf: &a {vms: *a}',
                       'ctf: {name: first, name: second}','ctf: [wrong]',
                       'ctf: {vms: [wrong]}','ctf: {flags: {a: wrong}}',
                       'x'*262145,'ctf: \ud800','ctf: '+('['*30)+(']'*30)):
            with self.subTest(source=source[:80]),self.assertRaises(DefinitionError):parse_yaml(source)
