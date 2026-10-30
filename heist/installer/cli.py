"""Compatibility entry point for the clean-host installer."""
import argparse


def main(argv=None):
    parser = argparse.ArgumentParser(description='Interactive onboarding wizard for heiST')
    parser.add_argument('--mode', choices=('simple', 'advanced'))
    args = parser.parse_args(argv)
    arguments = ['--mode', args.mode] if args.mode else []
    from pathlib import Path
    import subprocess
    from heist.ui_assets import verify_installation
    root = Path(__file__).resolve().parents[2]
    revision = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
    verify_installation(root/'webserver/html', revision)
    from heist.installer.bootstrap import bootstrap_requirements
    bootstrap_requirements(arguments)
    from heist.installer.wizard import main as wizard
    return wizard(arguments)


if __name__ == '__main__':
    main()
