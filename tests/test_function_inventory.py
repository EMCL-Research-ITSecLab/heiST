import json
from pathlib import Path
import tempfile
import unittest
from tools.function_inventory import FunctionTrace, evaluate, functions


class InventoryTests(unittest.TestCase):
    def test_nested_and_async_functions_have_stable_unique_identifiers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'heist').mkdir()
            (root/'heist/sample.py').write_text('class Service:\n def run(self):\n  def inner(): pass\nasync def action(): pass\n')
            identifiers = {item['id'] for item in functions(root)}
            self.assertEqual(identifiers, {'heist/sample.py::Service.run', 'heist/sample.py::Service.run.inner', 'heist/sample.py::action'})

    def test_function_execution_alone_cannot_claim_behavioral_verification(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'heist').mkdir()
            (root/'heist/sample.py').write_text('def operation(): pass\n')
            key = 'heist/sample.py::operation'
            self.assertEqual(evaluate({key: 1}, {}, root)[0]['status'], 'unverified')
            self.assertEqual(evaluate({key: 1}, {key: {'tests': ['test_rejects_bad_input'], 'rationale': 'Rejects malformed values before a side effect'}}, root, passed_tests=['test_rejects_bad_input'])[0]['status'], 'verified')

    def test_runtime_trace_counts_actual_function_calls_and_restores_profiler(self):
        import sys
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'heist').mkdir()
            source = root/'heist/sample.py'
            source.write_text('def operation(value): return value + 1\n')
            scope = {}
            exec(compile(source.read_text(), str(source), 'exec'), scope)
            previous = sys.getprofile()
            with FunctionTrace(root) as trace:
                self.assertEqual(scope['operation'](3), 4)
            self.assertEqual(trace.calls['heist/sample.py::operation'], 1)
            self.assertIs(sys.getprofile(), previous)
