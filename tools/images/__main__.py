"""Explicit operator entry points for optional VM image builders."""
import argparse
import importlib
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('builder', choices=('configure', 'windows', 'windows-ad'))
    parser.add_argument('--config', help='Build configuration for the configurable builder')
    parser.add_argument('--execute', action='store_true', help='Explicitly start the VM build')
    args = parser.parse_args(argv)
    if not args.execute:
        parser.error('Review the operator documentation, then supply --execute to start a VM build')
    if args.builder == 'configure':
        if not args.config:
            parser.error('configure requires --config')
        sys.argv = [sys.argv[0], args.config]
        module = 'tools.images.configure_ova'
    else:
        module = 'tools.images.' + args.builder.replace('-', '_')
    importlib.import_module(module).main()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
