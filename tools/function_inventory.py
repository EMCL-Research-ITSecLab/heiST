"""Inventory named Python functions and distinguish execution from reviewed verification."""
import argparse
import ast
import json
from pathlib import Path
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]


def functions(root=ROOT):
    result = []
    for directory in ('heist', 'tools'):
        for source in sorted((root/directory).rglob('*.py')):
            relative = str(source.relative_to(root))
            tree = ast.parse(source.read_text())
            def visit(node, parents=()):
                for child in ast.iter_child_nodes(node):
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        name = '.'.join((*parents, child.name))
                        result.append({'id': relative+'::'+name, 'path': relative, 'function': name, 'line': child.lineno})
                        visit(child, (*parents, child.name))
                    elif isinstance(child, ast.ClassDef):
                        visit(child, (*parents, child.name))
                    else:
                        visit(child, parents)
            visit(tree)
    return result


class FunctionTrace:
    def __init__(self, root=ROOT):
        self.root = Path(root).resolve()
        self.calls = {}
        self.previous = None
        self.previous_thread = None

    def profile(self, frame, event, argument):
        if event != 'call':
            return
        code = frame.f_code
        if not code.co_filename.startswith(str(self.root)+'/'):
            return
        try:
            relative = Path(code.co_filename).resolve().relative_to(self.root)
        except (ValueError, OSError):
            return
        if not relative.parts or relative.parts[0] not in ('heist', 'tools') or code.co_name == '<module>':
            return
        name = code.co_qualname.replace('.<locals>.', '.')
        key = str(relative)+'::'+name
        self.calls[key] = self.calls.get(key, 0)+1

    def __enter__(self):
        self.previous = sys.getprofile()
        self.previous_thread = threading.getprofile()
        sys.setprofile(self.profile)
        threading.setprofile(self.profile)
        return self

    def __exit__(self, *error):
        sys.setprofile(self.previous)
        threading.setprofile(self.previous_thread)


def evaluate(calls, verification, root=ROOT, *, passed_tests=()):
    entries = []
    for function in functions(root):
        claimed = verification.get(function['id'], {})
        entries.append({**function, 'calls': calls.get(function['id'], 0),
                        'verification_tests': claimed.get('tests', []), 'rationale': claimed.get('rationale', ''),
                        'status': 'verified' if calls.get(function['id'], 0) and claimed.get('tests') and set(claimed['tests']).issubset(set(passed_tests)) and claimed.get('rationale') else 'unverified'})
    return entries


def main(argv=None):
    sys.path.insert(0, str(ROOT))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error('Use a new inventory output path')
    from heist.files import write_json
    args.output.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    entries = evaluate({}, {})
    write_json(args.output, {'schema': 1, 'functions': entries})
    print('Inventoried', len(entries), 'named functions; execution and reviewed assertions must be recorded separately')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
