CREATE FUNCTION get_user_running_challenge(
    p_user_id BIGINT
)
RETURNS BIGINT
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    RETURN ( SELECT running_challenge FROM users WHERE id = p_user_id )::BIGINT;
END;
$$;


CREATE FUNCTION get_deployable_conditions(
    p_challenge_template_id BIGINT
)
RETURNS TABLE (
    marked_for_deletion BOOLEAN,
    is_active BOOLEAN
)
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    RETURN QUERY
    SELECT
        ct.marked_for_deletion::BOOLEAN,
        ct.is_active::BOOLEAN
    FROM challenge_templates ct
    WHERE id = p_challenge_template_id;
END;
$$;


CREATE FUNCTION get_creator_id_by_challenge_template(
    p_challenge_template_id BIGINT
)
RETURNS BIGINT
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    RETURN (
        SELECT creator_id FROM challenge_templates
        WHERE id = p_challenge_template_id
    )::BIGINT;
END;
$$;


CREATE FUNCTION create_new_challenge_attempt(
    p_user_id BIGINT,
    p_challenge_template_id BIGINT
) RETURNS VOID
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    INSERT INTO completed_challenges (
        user_id,
        challenge_template_id,
        started_at
    ) VALUES (
        p_user_id,
        p_challenge_template_id,
        CURRENT_TIMESTAMP
    );
END;
$$;


CREATE FUNCTION mark_attempt_completed(
    p_user_id BIGINT,
    p_challenge_template_id BIGINT
) RETURNS VOID
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    UPDATE completed_challenges
    SET completed_at = CURRENT_TIMESTAMP
    WHERE user_id = p_user_id
    AND challenge_template_id = p_challenge_template_id
    AND completed_at IS NULL;
END;
$$;


CREATE FUNCTION challenge_template_should_be_deleted(
    p_challenge_template_id BIGINT
)
RETURNS BOOLEAN
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
DECLARE
    v_count BIGINT;
    v_marked_for_deletion BOOLEAN;
BEGIN
    SELECT COUNT(*) INTO v_count
    FROM challenges
    WHERE challenge_template_id = p_challenge_template_id;

    SELECT marked_for_deletion INTO v_marked_for_deletion
    FROM challenge_templates
    WHERE id = p_challenge_template_id;

    RETURN (v_count = 0 AND v_marked_for_deletion)::BOOLEAN;
END;
$$;


CREATE FUNCTION delete_challenge_template(
    p_challenge_template_id BIGINT
) RETURNS VOID
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    DELETE FROM challenge_templates
    WHERE id = p_challenge_template_id;
END;
$$;


CREATE FUNCTION validate_and_lock_flag(
    p_challenge_template_id BIGINT,
    p_submitted_flag TEXT,
    p_user_id BIGINT
)
RETURNS TABLE (
    id BIGINT,
    points BIGINT
)
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
DECLARE
    v_user_email TEXT;
BEGIN
    SELECT u.email INTO v_user_email
    FROM users u
    WHERE u.id = p_user_id;

    RETURN QUERY
    SELECT
        cf.id::BIGINT AS id,
        cf.points::BIGINT AS points
    FROM challenge_flags cf
    WHERE cf.challenge_template_id = p_challenge_template_id
    AND (
        -- Static flag: direct match
        (cf.user_specific = false AND cf.flag = p_submitted_flag)
        OR
        -- User-specific flag: HMAC match using unique_id
        (cf.user_specific = true AND
         'ITSEC{' || encode(hmac(v_user_email::bytea, cf.flag::bytea, 'sha1'), 'hex') || '}' = p_submitted_flag)
    )
    FOR UPDATE;
END;
$$;


CREATE FUNCTION is_duplicate_flag_submission(
    p_user_id BIGINT,
    p_challenge_template_id BIGINT,
    p_flag_id BIGINT
) RETURNS BOOLEAN
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    RETURN EXISTS (
        SELECT 1 FROM completed_challenges
        WHERE user_id = p_user_id
        AND challenge_template_id = p_challenge_template_id
        AND flag_id = p_flag_id
        FOR UPDATE
    )::BOOLEAN;
END;
$$;


CREATE FUNCTION get_user_submitted_flags_count_for_challenge(
    p_user_id BIGINT,
    p_challenge_template_id BIGINT
) RETURNS BIGINT
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    RETURN (
        SELECT COUNT(DISTINCT flag_id)
        FROM completed_challenges
        WHERE user_id = p_user_id
        AND challenge_template_id = p_challenge_template_id
        AND flag_id IS NOT NULL
    )::BIGINT;
END;
$$;


CREATE FUNCTION get_total_flags_count_for_challenge(
    p_challenge_template_id BIGINT
) RETURNS BIGINT
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    RETURN (
        SELECT COUNT(*) FROM challenge_flags
        WHERE challenge_template_id = p_challenge_template_id
    )::BIGINT;
END;
$$;


CREATE FUNCTION get_active_attempt_id(
    p_user_id BIGINT,
    p_challenge_template_id BIGINT
) RETURNS BIGINT
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    RETURN (
        SELECT id FROM completed_challenges
        WHERE user_id = p_user_id
        AND challenge_template_id = p_challenge_template_id
        AND completed_at IS NULL
        FOR UPDATE
    )::BIGINT;
END;
$$;


CREATE FUNCTION update_running_attempt(
    p_flag_id BIGINT,
    p_attempt_id BIGINT
) RETURNS VOID
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    UPDATE completed_challenges
    SET
        flag_id = p_flag_id,
        completed_at = CURRENT_TIMESTAMP
    WHERE id = p_attempt_id;
END;
$$;


CREATE FUNCTION create_new_completed_attempt(
    p_user_id BIGINT,
    p_challenge_template_id BIGINT,
    p_flag_id BIGINT
) RETURNS VOID
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    INSERT INTO completed_challenges (
        user_id,
        challenge_template_id,
        flag_id,
        started_at,
        completed_at
    ) VALUES (
        p_user_id,
        p_challenge_template_id,
        p_flag_id,
        CURRENT_TIMESTAMP,
        CURRENT_TIMESTAMP
    );
END;
$$;


CREATE FUNCTION get_recent_unflagged_attempt(
    p_user_id BIGINT,
    p_challenge_template_id BIGINT
) RETURNS BIGINT
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    RETURN (
        SELECT id FROM completed_challenges
        WHERE user_id = p_user_id
        AND challenge_template_id = p_challenge_template_id
        AND flag_id IS NULL
        AND completed_at IS NOT NULL
        ORDER BY started_at DESC
        LIMIT 1
        FOR UPDATE
    )::BIGINT;
END;
$$;


CREATE FUNCTION update_recent_attempt(
    p_flag_id BIGINT,
    p_attempt_id BIGINT
) RETURNS VOID
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    UPDATE completed_challenges
    SET flag_id = p_flag_id
    WHERE id = p_attempt_id;
END;
$$;


CREATE FUNCTION get_challenge_template_details(
    p_challenge_template_id BIGINT
)
RETURNS TABLE (
    id BIGINT,
    name TEXT,
    description TEXT,
    category challenge_category,
    difficulty challenge_difficulty,
    image_path TEXT,
    is_active BOOLEAN,
    created_at TIMESTAMP,
    updated_at TIMESTAMP,
    hint TEXT,
    marked_for_deletion BOOLEAN,
    creator_username TEXT,
    creator_id BIGINT,
    solve_count BIGINT
)
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    RETURN QUERY
    SELECT
        ct.id::BIGINT,
        ct.name::TEXT,
        ct.description::TEXT,
        ct.category::challenge_category,
        ct.difficulty::challenge_difficulty,
        ct.image_path::TEXT,
        ct.is_active::BOOLEAN,
        ct.created_at::TIMESTAMP,
        ct.updated_at::TIMESTAMP,
        ct.hint::TEXT,
        ct.marked_for_deletion::BOOLEAN,
        u.username::TEXT as creator_username,
        ct.creator_id::BIGINT as creator_id,
        (
            SELECT COUNT(DISTINCT cc.user_id)
            FROM completed_challenges cc
            WHERE cc.challenge_template_id = ct.id
            AND (
                SELECT COUNT(DISTINCT cf.id)
                FROM challenge_flags cf
                WHERE cf.challenge_template_id = ct.id
            ) = (
                SELECT COUNT(DISTINCT cc2.flag_id)
                FROM completed_challenges cc2
                JOIN challenge_flags cf ON cc2.flag_id = cf.id
                WHERE cc2.user_id = cc.user_id
                AND cc2.challenge_template_id = ct.id
                AND cf.challenge_template_id = ct.id
            )
        )::BIGINT AS solve_count
    FROM challenge_templates ct
    LEFT JOIN users u ON ct.creator_id = u.id
    WHERE ct.id = p_challenge_template_id
    GROUP BY ct.id, u.username, ct.creator_id;
END;
$$;


CREATE FUNCTION get_challenge_user_status(
    p_user_id BIGINT,
    p_challenge_template_id BIGINT
)
RETURNS TEXT
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    RETURN (
        SELECT
        CASE
            WHEN EXISTS (
                SELECT 1
                FROM users u
                JOIN challenges c ON u.running_challenge = c.id
                WHERE u.id = p_user_id
                AND c.challenge_template_id = p_challenge_template_id
            ) THEN 'running'

            WHEN (
                SELECT COUNT(DISTINCT cf.id)
                FROM challenge_flags cf
                WHERE cf.challenge_template_id = p_challenge_template_id
            ) = (
                SELECT COUNT(DISTINCT cc.flag_id)
                FROM completed_challenges cc
                JOIN challenge_flags cf ON cc.flag_id = cf.id
                WHERE cc.user_id = p_user_id
                AND cc.challenge_template_id = p_challenge_template_id
                AND cf.challenge_template_id = p_challenge_template_id
            ) THEN 'solved'

            WHEN EXISTS (
                SELECT 1 FROM completed_challenges
                WHERE user_id = p_user_id
                AND challenge_template_id = p_challenge_template_id
                AND completed_at IS NOT NULL
            ) AND (
                SELECT COUNT(DISTINCT cf.id)
                FROM challenge_flags cf
                WHERE cf.challenge_template_id = p_challenge_template_id
            ) > (
                SELECT COUNT(DISTINCT cc.flag_id)
                FROM completed_challenges cc
                JOIN challenge_flags cf ON cc.flag_id = cf.id
                WHERE cc.user_id = p_user_id
                AND cc.challenge_template_id = p_challenge_template_id
                AND cf.challenge_template_id = p_challenge_template_id
            ) THEN 'failed'

            ELSE 'not_tried'
        END AS challenge_status
        FROM users
        WHERE id = p_user_id
    )::TEXT;
END;
$$;


CREATE FUNCTION get_challenge_solution(
    p_challenge_template_id BIGINT
) RETURNS TEXT
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    RETURN (
        SELECT
            solution
        FROM challenge_templates
        WHERE id = p_challenge_template_id
    )::TEXT;
END;
$$;


CREATE FUNCTION get_remaining_seconds_for_user_challenge(
    p_user_id BIGINT,
    p_challenge_template_id BIGINT
) RETURNS BIGINT
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    RETURN (
        SELECT EXTRACT(EPOCH FROM (c.expires_at - CURRENT_TIMESTAMP))::BIGINT AS remaining_seconds
        FROM challenges c
        JOIN users u ON u.running_challenge = c.id
        WHERE u.id = p_user_id
        AND c.challenge_template_id = p_challenge_template_id
    )::BIGINT;
END;
$$;


CREATE FUNCTION get_challenge_flags(
    p_challenge_template_id BIGINT
)
RETURNS TABLE (
    id BIGINT,
    challenge_template_id BIGINT,
    flag TEXT,
    description TEXT,
    points BIGINT,
    order_index BIGINT
)
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    RETURN QUERY
    SELECT
        cf.id::BIGINT AS id,
        cf.challenge_template_id::BIGINT AS challenge_template_id,
        cf.flag::TEXT AS flag,
        cf.description::TEXT AS description,
        cf.points::BIGINT AS points,
        cf.order_index::BIGINT AS order_index
    FROM challenge_flags cf
    WHERE cf.challenge_template_id = p_challenge_template_id
    ORDER BY cf.order_index, cf.id;
END;
$$;


CREATE FUNCTION get_unlocked_challenge_hints(
    p_challenge_template_id BIGINT,
    p_user_points BIGINT
)
RETURNS TABLE (
    id BIGINT,
    challenge_template_id BIGINT,
    hint_text TEXT,
    unlock_points BIGINT,
    order_index BIGINT
)
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    RETURN QUERY
    SELECT
        ch.id::BIGINT AS id,
        ch.challenge_template_id::BIGINT AS challenge_template_id,
        ch.hint_text::TEXT AS hint_text,
        ch.unlock_points::BIGINT AS unlock_points,
        ch.order_index::BIGINT AS order_index
    FROM challenge_hints ch
    WHERE ch.challenge_template_id = p_challenge_template_id
    AND ch.unlock_points <= p_user_points
    ORDER BY ch.order_index, ch.id;
END;
$$;


CREATE FUNCTION get_completed_flag_ids_for_user(
    p_user_id BIGINT,
    p_challenge_template_id BIGINT
) RETURNS TABLE (
    flag_id BIGINT
)
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    RETURN QUERY
    SELECT cc.flag_id::BIGINT
    FROM completed_challenges cc
    WHERE cc.user_id = p_user_id AND cc.challenge_template_id = p_challenge_template_id
    AND cc.flag_id IS NOT NULL;
END;
$$;


CREATE FUNCTION get_entrypoints_for_user_challenge(
    p_user_id BIGINT
) RETURNS TABLE (
    subnet INET
)
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    RETURN QUERY
    SELECT DISTINCT n.subnet::INET AS subnet
    FROM users u
    JOIN machines m ON u.running_challenge = m.challenge_id
    JOIN network_connections nc ON m.id = nc.machine_id
    JOIN networks n ON nc.network_id = n.id
    JOIN network_templates nt ON n.network_template_id = nt.id
    WHERE u.id = p_user_id
    AND nt.accessible = TRUE;
END;
$$;


CREATE FUNCTION is_first_blood(
    p_challenge_template_id BIGINT,
    p_user_id BIGINT
) RETURNS BOOLEAN
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    RETURN (
        SELECT NOT EXISTS (
            SELECT 1 FROM (
                SELECT DISTINCT cc.user_id
                FROM completed_challenges cc
                WHERE cc.challenge_template_id = p_challenge_template_id
                AND cc.user_id != p_user_id
                GROUP BY cc.user_id
                HAVING COUNT(DISTINCT cc.flag_id) = (
                    SELECT COUNT(*)
                    FROM challenge_flags
                    WHERE challenge_template_id = p_challenge_template_id
                )
            ) AS is_first_blood
        )
    )::BOOLEAN;
END;
$$;


CREATE FUNCTION get_remaining_extensions_for_user_challenge(
    p_user_id BIGINT,
    p_challenge_template_id BIGINT
) RETURNS BIGINT
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    RETURN (
        SELECT used_extensions
        FROM challenges c
        JOIN users u ON u.running_challenge = c.id
        WHERE u.id = p_user_id
        AND c.challenge_template_id = p_challenge_template_id
    )::BIGINT;
END;
$$;


CREATE FUNCTION get_category_of_challenge_instance(
    p_challenge_id BIGINT
) RETURNS challenge_category
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    RETURN (
        SELECT category FROM challenge_templates WHERE id = p_challenge_id
    )::challenge_category;
END;
$$;


CREATE FUNCTION get_user_solved_challenges_in_category(
    p_user_id BIGINT,
    p_category challenge_category
)
RETURNS BIGINT
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    RETURN (
        SELECT COUNT(DISTINCT ct.id)
            FROM challenge_templates ct
            JOIN (
                SELECT cc.challenge_template_id
                FROM completed_challenges cc
                WHERE cc.user_id = p_user_id
                GROUP BY cc.challenge_template_id
                HAVING COUNT(DISTINCT cc.flag_id) = (
                    SELECT COUNT(*)
                    FROM challenge_flags
                    WHERE challenge_template_id = cc.challenge_template_id
                )
            ) solved ON ct.id = solved.challenge_template_id
            WHERE ct.category = p_category
    )::BIGINT;
END;
$$;


CREATE FUNCTION count_user_badges_excluding_one(
    p_user_id BIGINT,
    p_excluded_badge_id BIGINT
) RETURNS BIGINT
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    RETURN (
        SELECT COUNT(DISTINCT b.id) FROM badges b
        LEFT JOIN user_badges ub ON b.id = ub.badge_id AND ub.user_id = p_user_id
        WHERE b.id != p_excluded_badge_id AND ub.user_id IS NULL
    )::BIGINT;
END;
$$;


CREATE FUNCTION badge_with_id_exists(
    p_badge_id BIGINT
) RETURNS BOOLEAN
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    RETURN (
        SELECT EXISTS (SELECT 1 FROM badges WHERE id = p_badge_id)
    )::BOOLEAN;
END;
$$;


CREATE FUNCTION user_already_has_badge(
    p_user_id BIGINT,
    p_badge_id BIGINT
) RETURNS BOOLEAN
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    RETURN (
        SELECT EXISTS (SELECT 1 FROM user_badges WHERE user_id = p_user_id AND badge_id = p_badge_id)
    )::BOOLEAN;
END;
$$;


CREATE FUNCTION award_badge_to_user(
    p_user_id BIGINT,
    p_badge_id BIGINT
) RETURNS VOID
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    INSERT INTO user_badges (user_id, badge_id, earned_at)
    VALUES (p_user_id, p_badge_id, CURRENT_TIMESTAMP)
    ON CONFLICT (user_id, badge_id) DO NOTHING;
END;
$$;


CREATE FUNCTION get_id_and_used_extensions_of_running_challenge(
    p_user_id BIGINT,
    p_challenge_template_id BIGINT
) RETURNS TABLE (
    id BIGINT,
    used_extensions BIGINT
)
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    RETURN QUERY
    SELECT
        c.id::BIGINT AS id,
        c.used_extensions::BIGINT AS used_extensions
    FROM challenges c
    JOIN users u ON u.running_challenge = c.id
    WHERE u.id = p_user_id
    AND c.challenge_template_id = p_challenge_template_id
    FOR UPDATE;
END;
$$;


CREATE FUNCTION extend_user_challenge_time(
    p_challenge_id BIGINT,
    p_extend_scalar BIGINT
) RETURNS VOID
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    UPDATE challenges
    SET
        expires_at = CURRENT_TIMESTAMP + (p_extend_scalar * INTERVAL '1 hour'),
        used_extensions = used_extensions + 1
    WHERE id = p_challenge_id;
END;
$$;
