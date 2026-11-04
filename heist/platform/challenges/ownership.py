"""Atomic instance reservation and activation, including cold-start instances."""


def take_ready_instance(connection, template_id, user_id):
    if user_id is None:
        raise ValueError('An instance must be reserved for a specific user')
    with connection.cursor() as cursor:
        cursor.execute("""
            WITH candidate AS (
                SELECT c.id FROM challenges c
                WHERE c.challenge_template_id = %s AND c.lifecycle_state = 'READY'
                  AND (c.pre_assigned_user_id IS NULL OR c.pre_assigned_user_id = %s)
                  AND NOT EXISTS (SELECT 1 FROM users u WHERE u.running_challenge = c.id)
                ORDER BY (c.pre_assigned_user_id IS NOT NULL) DESC, c.id
                LIMIT 1 FOR UPDATE OF c SKIP LOCKED
            )
            UPDATE challenges c
            SET lifecycle_state = 'ASSIGNED', pre_assigned_user_id = %s
            FROM candidate WHERE c.id = candidate.id
            RETURNING c.id, c.subnet
        """, (template_id, user_id, user_id))
        return cursor.fetchone()


def assign_instance(connection, challenge_id, user_id):
    # A single statement also works with the backend's autocommit connections.
    # Lock the user before claiming the instance, preventing concurrent launches
    # for that user from assigning two different instances.
    with connection.cursor() as cursor:
        cursor.execute("""
            WITH eligible_user AS MATERIALIZED (
                SELECT id FROM users WHERE id = %s
                  AND (running_challenge IS NULL OR running_challenge = %s)
                FOR UPDATE
            ), claimed AS (
                UPDATE challenges c
                SET lifecycle_state = 'ACTIVE', pre_assigned_user_id = %s
                FROM eligible_user u
                WHERE c.id = %s AND c.lifecycle_state IN ('READY', 'ASSIGNED')
                  AND (c.pre_assigned_user_id IS NULL OR c.pre_assigned_user_id = u.id)
                  AND NOT EXISTS (
                      SELECT 1 FROM users other
                      WHERE other.running_challenge = c.id AND other.id <> u.id
                  )
                RETURNING c.id
            )
            UPDATE users u SET running_challenge = claimed.id
            FROM claimed WHERE u.id = %s RETURNING u.id
        """, (user_id, challenge_id, user_id, challenge_id, user_id))
        if cursor.fetchone() is None:
            raise RuntimeError('Instance ownership could not be assigned exclusively')


def finalize_launch(connection, challenge_id, user_id):
    """Commit the deadline, attempt and monitoring traces exactly once per instance.

    VM/network setup has finished. Row locks serialize expiry/stop, while the
    activation key makes a response-loss retry unable to create another attempt
    or reset the deadline. This is a database guarantee, not external-task replay.
    """
    with connection:
        with connection.cursor() as cursor:
            cursor.execute('''SELECT c.challenge_template_id, u.username, u.email
                              FROM public.users u JOIN public.challenges c ON c.id=u.running_challenge
                              WHERE u.id=%s AND c.id=%s AND c.lifecycle_state='ACTIVE'
                              FOR UPDATE OF u,c''', (user_id, challenge_id))
            row = cursor.fetchone()
            if row is None:
                raise RuntimeError('Launch assignment changed before activation')
            template, username, email = row
            cursor.execute('SELECT user_id FROM public.instance_activations WHERE challenge_id=%s', (challenge_id,))
            previous = cursor.fetchone()
            if previous:
                if previous[0] != user_id:
                    raise RuntimeError('Activation belongs to another user')
                return
            cursor.execute('''INSERT INTO public.completed_challenges(user_id,challenge_template_id,started_at)
                              VALUES (%s,%s,CURRENT_TIMESTAMP) RETURNING id''', (user_id, template))
            attempt = cursor.fetchone()[0]
            cursor.execute('''INSERT INTO public.user_network_trace(username,email,subnet)
                              SELECT %s,%s,subnet FROM public.networks WHERE challenge_id=%s''', (username, email, challenge_id))
            cursor.execute("UPDATE public.challenges SET expires_at=CURRENT_TIMESTAMP+INTERVAL '1 hour' WHERE id=%s", (challenge_id,))
            cursor.execute('INSERT INTO public.instance_activations(challenge_id,user_id,attempt_id) VALUES (%s,%s,%s)', (challenge_id, user_id, attempt))
