"""Recheck exercise availability at the privileged provisioning boundary."""


def require_available_template(connection, template_id, user_id=None):
    with connection.cursor() as cursor:
        cursor.execute('''
            SELECT t.id FROM challenge_templates t
            WHERE t.id = %s AND t.ready_to_launch AND NOT t.marked_for_deletion
              AND (%s::bigint IS NULL OR EXISTS(SELECT 1 FROM users WHERE id = %s))
              AND (t.is_active OR EXISTS(
                  SELECT 1 FROM users u WHERE u.id = %s AND (u.is_admin OR u.id = t.creator_id)
              ))
        ''', (template_id, user_id, user_id, user_id))
        if cursor.fetchone() is None:
            raise ValueError('Exercise is unavailable or its machine templates are not ready')
