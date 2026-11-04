"""Admission gate for the browser-runtime clean-host installer."""
import argparse


def main(argv=None):
    parser = argparse.ArgumentParser(description='Interactive onboarding wizard for heiST')
    parser.add_argument('--mode', choices=('simple', 'advanced'))
    parser.parse_args(argv)
    raise RuntimeError('The Flask browser-runtime installer is not yet approved. '
                       'The legacy PHP installer cannot deploy this UI; no infrastructure was changed.')


if __name__ == '__main__':
    main()
