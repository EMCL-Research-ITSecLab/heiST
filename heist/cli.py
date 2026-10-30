"""Explicit command dispatch; importing the CLI never starts services or installs packages."""
import argparse
import importlib
import runpy
import sys

MODULE_COMMANDS = {
    'install': ('heist.installer.cli', 'Configure a clean Proxmox host'),
    'update': ('heist.rollout.cli', 'Alias for the full-platform release controller'),
    'db': ('heist.maintenance.database', 'Back up or restore PostgreSQL'),
    'upgrade': ('heist.rollout.cli', 'Plan, deploy or recover a full platform release'),
}
SERVICE_COMMANDS = {
    'api': ('heist.backend.api', 'Start the internal API service'),
    'pool-manager': ('heist.backend.pool_manager', 'Start the challenge pool service'),
    'cleanup': ('heist.backend.cleanup', 'Run challenge cleanup'),
}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(prog='heist', description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for name, (_, description) in MODULE_COMMANDS.items():
        commands.add_parser(name, help=description, add_help=False)
    for name, (_, description) in SERVICE_COMMANDS.items():
        commands.add_parser(name, help=description)
    args, remaining = parser.parse_known_args(argv)
    if args.command in MODULE_COMMANDS:
        module = importlib.import_module(MODULE_COMMANDS[args.command][0])
        return module.main(remaining) or 0
    if remaining:
        parser.error('Service commands accept no additional arguments')
    runpy.run_module(SERVICE_COMMANDS[args.command][0], run_name='__main__')
    return 0
