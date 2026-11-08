"""Configuration editor and admission gate for the clean-host Flask installer."""
import argparse
from importlib import import_module
import sys


def main(argv=None):
    parser=argparse.ArgumentParser(description='Configure a fresh heiST installation')
    parser.add_argument('action',nargs='?',choices=('configure','apply'),default='apply')
    parser.add_argument('--mode',choices=('simple','advanced'))
    args=parser.parse_args(argv)
    if args.action=='configure':
        if not sys.stdin.isatty():
            parser.error('configure requires an interactive terminal; no files were changed')
        wizard=import_module('heist.installer.wizard')
        return wizard.main(['--mode',args.mode] if args.mode else [])
    raise RuntimeError('The Flask browser-runtime installer is not yet approved. '
                       'The legacy PHP installer cannot deploy this UI; no infrastructure was changed.')


if __name__=='__main__':
    main()
