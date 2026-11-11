"""Training eligibility gate. Does not enable capture, copy data or authorize security logs."""
from datetime import datetime, timezone
import re


def eligibility(manifest, preferences, *, enabled=False, now=None):
    """Recheck current preferences, never reuse a prior allow decision.

    Only trusted collector manifests with complete participant provenance can
    enter this gate. Shared platform PCAPs are deliberately inadmissible.
    """
    if enabled is not True:
        return False, 'training_disabled'
    now = now or datetime.now(timezone.utc)
    try:
        if (manifest['schema'] != 1 or manifest['purpose'] != 'training'
                or manifest['scope'] != 'isolated-instance' or manifest['participants_complete'] is not True):
            return False, 'unverified_traffic_scope'
        if manifest['closed'] is not True or not re.fullmatch('[a-f0-9]{64}', manifest['sha256']):
            return False, 'incomplete_capture'
        start = datetime.fromisoformat(manifest['started_at'].replace('Z', '+00:00'))
        end = datetime.fromisoformat(manifest['ended_at'].replace('Z', '+00:00'))
        if start.tzinfo is None or end.tzinfo is None or not start < end <= now:
            return False, 'invalid_capture_interval'
        participants = manifest['participants']
        if not isinstance(participants, list) or not 1 <= len(participants) <= 64:
            return False, 'unknown_participants'
        seen = set()
        for item in participants:
            identifier, revision = item['user_id'], item['preference_revision']
            if type(identifier) is not int or not 0 < identifier < 2**63 or identifier in seen or type(revision) is not int or revision < 1:
                return False, 'unknown_participants'
            seen.add(identifier)
            current = preferences.get(identifier)
            if not current:
                return False, 'unknown_participants'
            if current['opted_out'] is not False:
                return False, 'opted_out'
            if current['revision'] != revision:
                return False, 'preference_changed'
            at = current['updated_at']
            if isinstance(at, str):at = datetime.fromisoformat(at.replace('Z', '+00:00'))
            if at.tzinfo is None or at > start:
                return False, 'preference_changed'
        return True, 'eligible'
    except (KeyError, TypeError, ValueError, AttributeError):
        return False, 'invalid_manifest'


def main(argv=None):
    import argparse
    import json
    import os
    from pathlib import Path
    from dotenv import dotenv_values
    from heist.config import DatabaseSettings
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True, type=Path)
    parser.add_argument('--environment', required=True, type=Path)
    args = parser.parse_args(argv)
    allowed, reason = False, 'policy_unavailable'
    try:
        path = args.manifest
        if path.is_symlink() or path.stat().st_uid != os.geteuid() or path.stat().st_mode & 0o022:
            raise ValueError('Use an operator-owned immutable manifest')
        with path.open('rb') as stream:body = stream.read(65537)
        if len(body) > 65536:raise ValueError('Manifest is oversized')
        manifest = json.loads(body)
        settings = {k:v for k,v in dotenv_values(args.environment).items() if v is not None}
        enabled = settings.get('HEIST_TRAINING_CAPTURE_ENABLED') == '1'
        if not enabled:
            reason = 'training_disabled'
        else:
            identifiers = [item['user_id'] for item in manifest['participants']]
            if len(identifiers) > 64 or any(type(i) is not int or not 0 < i < 2**63 for i in identifiers):
                raise ValueError('Invalid participant scope')
            db = DatabaseSettings.from_mapping(settings).connect(autocommit=False)
            try:
                with db:
                    with db.cursor() as cursor:
                        cursor.execute("SET TRANSACTION READ ONLY")
                        cursor.execute("SET LOCAL statement_timeout='3s'")
                        cursor.execute('SELECT user_id,opted_out,revision,updated_at FROM public.training_preferences WHERE user_id=ANY(%s)',(identifiers,))
                        preferences = {i:{'opted_out':out,'revision':revision,'updated_at':at} for i,out,revision,at in cursor.fetchall()}
                        allowed, reason = eligibility(manifest,preferences,enabled=True)
            finally:db.close()
    except Exception:
        # Never print DSNs, participant IDs or private capture metadata.
        allowed, reason = False, 'policy_unavailable'
    print(json.dumps({'eligible_for_training':allowed,'reason':reason,'data_copied':False}))
    return 0 if allowed else 1


if __name__ == '__main__':
    raise SystemExit(main())
