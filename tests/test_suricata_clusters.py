"""Check the generated VPN/DMZ capture settings without privileged setup."""
import ast
from pathlib import Path
import re
import unittest


class CaptureClusterTests(unittest.TestCase):
    def test_parallel_sensors_use_distinct_clusters_in_both_modes(self):
        source = Path(__file__).resolve().parents[1] / 'monitoring/setup_network_monitoring.py'
        tree = ast.parse(source.read_text())
        sensors = {}
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef) or node.name not in (
                'setup_suricata_config', 'setup_suricata_dmz_config'
            ):
                continue
            modes = {}
            for branch in node.body:
                if not isinstance(branch, ast.If) or not isinstance(branch.test, ast.Attribute) or branch.test.attr != 'pf_ring':
                    continue
                for mode, statements in (('pfring', branch.body), ('af-packet', branch.orelse)):
                    assignments = [stmt for stmt in statements if isinstance(stmt, ast.Assign)
                                   and any(isinstance(t, ast.Name) and t.id == 'interface_config' for t in stmt.targets)]
                    self.assertEqual(len(assignments), 1)
                    template = ast.Expression(assignments[0].value)
                    config = eval(compile(template, str(source), 'eval'), {'__builtins__': {}}, {
                        'MONITORING_VPN_INTERFACE': 'test-vpn', 'MONITORING_DMZ_INTERFACE': 'test-dmz'})
                    matches = re.findall(r'^\s+cluster-id:\s*(\d+)\s*$', config, re.M)
                    self.assertEqual(len(matches), 1)
                    modes[mode] = int(matches[0])
                    self.assertGreater(modes[mode], 0)
                    self.assertLessEqual(modes[mode], 65535)
            self.assertEqual(set(modes), {'pfring', 'af-packet'})
            sensors[node.name] = modes
        self.assertEqual(len(sensors), 2)
        for mode in ('pfring', 'af-packet'):
            self.assertEqual(len({settings[mode] for settings in sensors.values()}), 2)

    def test_sensor_pid_files_are_in_systemd_managed_runtime_directories(self):
        import configparser
        import shlex
        source = Path(__file__).resolve().parents[1] / 'monitoring/setup_services.py'
        directories = set()
        services = 0
        for node in ast.parse(source.read_text()).body:
            if not isinstance(node, ast.Assign) or not any(
                isinstance(t, ast.Name) and t.id.startswith('SURICATA_') and t.id.endswith('_SERVICE')
                for t in node.targets
            ):
                continue
            names = {part.id: 'test-' + part.id for part in ast.walk(node.value) if isinstance(part, ast.Name)}
            text = eval(compile(ast.Expression(node.value), str(source), 'eval'), {'__builtins__': {}}, names)
            unit = configparser.ConfigParser(interpolation=None)
            unit.read_string(text)
            runtime = unit['Service']['RuntimeDirectory']
            self.assertNotIn(runtime, directories)
            directories.add(runtime)
            self.assertEqual(unit['Service']['RuntimeDirectoryMode'], '0750')
            command = shlex.split(unit['Service']['ExecStart'])
            pidfile = Path(command[command.index('--pidfile') + 1])
            self.assertEqual(pidfile.parent, Path('/run') / runtime)
            services += 1
        self.assertEqual(services, 3)
