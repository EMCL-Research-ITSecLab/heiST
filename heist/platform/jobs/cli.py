"""Inspect or acknowledge an interrupted operation after maintenance recovery."""
import argparse
import json
import os
from pathlib import Path

from .journal import Journal


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('status', 'resolve'))
    parser.add_argument('--scope', choices=('user', 'template', 'pool', 'artifact'), required=True)
    parser.add_argument('--resource', type=int, required=True)
    parser.add_argument('--operation-id')
    parser.add_argument('--reason')
    args = parser.parse_args(argv)
    if os.geteuid() != 0:
        parser.error('Operation recovery requires the local root administrator')
    journal = Journal(os.environ.get('HEIST_OPERATION_DIRECTORY', '/var/lib/heist/operations'))
    if args.action == 'resolve':
        if not Path(os.environ.get('HEIST_MAINTENANCE_FILE', '/run/heist-maintenance')).is_file():
            parser.error('Enter platform maintenance and reconcile native tasks/resources first')
        if not args.operation_id or not args.reason:
            parser.error('Resolution requires the current --operation-id and a recorded --reason')
        journal.resolve(args.scope, args.resource, args.operation_id, args.reason)
    print(json.dumps(journal.inspect(args.scope, args.resource), indent=2))
    return 0
