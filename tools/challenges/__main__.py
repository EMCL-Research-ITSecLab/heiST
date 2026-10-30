"""Import a reviewed exercise definition through the authenticated web API."""
import argparse
import getpass


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--file', required=True)
    parser.add_argument('--url', required=True)
    parser.add_argument('--username', required=True)
    parser.add_argument('--ca-file')
    parser.add_argument('--skip-upload', action='store_true')
    args = parser.parse_args(argv)
    from .get_authenticated_session import get_authenticated_session
    from .setup_challenge import setup_challenge
    with get_authenticated_session(args.username, getpass.getpass(), base_url=args.url, ca_file=args.ca_file) as session:
        setup_challenge(session, args.file, upload_ovas=not args.skip_upload, prints=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
