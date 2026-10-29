"""Compatibility entry point for the clean-host installer."""
import argparse


def main(argv=None):
    parser = argparse.ArgumentParser(description='Interactive onboarding wizard for heiST')
    parser.add_argument('--mode', choices=('simple', 'advanced'))
    args = parser.parse_args(argv)
    arguments = ['--mode', args.mode] if args.mode else []
    from setup.bootstrap import bootstrap_requirements
    bootstrap_requirements(arguments)
    from setup.installer_ui import main as wizard
    return wizard(arguments)


if __name__ == '__main__':
    main()
