"""A cleaned failed launch is reviewable without keeping its user locked out."""


def can_retry_launch(user_id, previous, *, connect):
    """Called under the journal's user lease; uncertainty fails closed.

    No assignment or reserved instance may remain, including an expired instance
    still awaiting teardown. Administrator work must be reconciled separately.
    The previous failure receipt remains NEEDS_REVIEW in the operation history.
    """
    if (previous.get('scope') != 'user' or previous.get('resource') != user_id
            or previous.get('action') != 'launch_challenge'
            or previous.get('state') != 'NEEDS_REVIEW'):
        return False
    db = connect()
    try:
        with db.cursor() as cursor:
            cursor.execute('''SELECT u.running_challenge IS NULL
                AND NOT EXISTS (SELECT 1 FROM challenges c WHERE c.pre_assigned_user_id=u.id)
                AND NOT EXISTS (SELECT 1 FROM administrator_requests a
                    WHERE a.scope='user' AND a.resource=u.id
                    AND a.state IN ('QUEUED','RUNNING','NEEDS_REVIEW'))
                FROM users u WHERE u.id=%s''', (user_id,))
            row = cursor.fetchone()
            return row is not None and row[0] is True
    finally:
        db.close()
