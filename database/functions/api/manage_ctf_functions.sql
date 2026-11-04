CREATE FUNCTION get_creator_id_by_challenge_id(
    p_challenge_template_id BIGINT
) RETURNS BIGINT
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    RETURN (
        SELECT creator_id
        FROM challenge_templates
        WHERE id = p_challenge_template_id
    )::BIGINT;
END;
$$;


CREATE FUNCTION get_total_leaderboard_entries_for_author(
    p_challenge_template_id BIGINT
) RETURNS BIGINT
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    RETURN (
        SELECT COUNT(DISTINCT cc.user_id) AS total
        FROM completed_challenges cc
        JOIN challenge_flags cf ON cc.flag_id = cf.id
        WHERE cc.challenge_template_id = p_challenge_template_id
        AND cf.points > 0
    )::BIGINT;
END;
$$;


CREATE FUNCTION get_challenge_template_id_by_name_with_possible_exclude(
    p_name TEXT,
    p_exclude_challenge_template_id BIGINT
) RETURNS BIGINT
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    RETURN (
        SELECT id FROM challenge_templates
        WHERE name = p_name
        AND (p_exclude_challenge_template_id IS NULL OR id != p_exclude_challenge_template_id)
        LIMIT 1
    )::BIGINT;
END;
$$;


CREATE FUNCTION get_challenge_template_data_for_deletion(
    p_user_id BIGINT,
    p_challenge_template_id BIGINT
) RETURNS TABLE (
    id BIGINT,
    marked_for_deletion BOOLEAN
)
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    RETURN QUERY
    SELECT
        ct.id::BIGINT AS id,
        ct.marked_for_deletion::BOOLEAN AS marked_for_deletion
    FROM challenge_templates ct
    WHERE ct.id = p_challenge_template_id AND ct.creator_id = p_user_id;
END;
$$;


CREATE FUNCTION challenge_template_is_marked_for_deletion(
    p_challenge_template_id BIGINT
) RETURNS BOOLEAN
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    RETURN (
        SELECT marked_for_deletion
        FROM challenge_templates
        WHERE id = p_challenge_template_id
    )::BOOLEAN;
END;
$$;


CREATE FUNCTION update_challenge_template(
    p_challenge_template_id BIGINT,
    p_name TEXT,
    p_description TEXT,
    p_category challenge_category,
    p_difficulty challenge_difficulty,
    p_hint TEXT,
    p_solution TEXT,
    p_is_active BOOLEAN
) RETURNS VOID
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    UPDATE challenge_templates SET
        name = p_name,
        description = p_description,
        category = p_category,
        difficulty = p_difficulty,
        hint = p_hint,
        solution = p_solution,
        is_active = p_is_active,
        updated_at = CURRENT_TIMESTAMP
    WHERE id = p_challenge_template_id;
END;
$$;


CREATE FUNCTION restore_challenge_template(
    p_challenge_template_id BIGINT
) RETURNS VOID
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    UPDATE challenge_templates SET
        marked_for_deletion = FALSE,
        is_active = TRUE
    WHERE id = p_challenge_template_id;
END;
$$;


CREATE FUNCTION verify_challenge_template_ownership_for_deletion(
    p_user_id BIGINT,
    p_challenge_template_id BIGINT
) RETURNS TABLE (
    id BIGINT,
    name TEXT
)
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    RETURN QUERY
    SELECT
        ct.id::BIGINT AS id,
        ct.name::TEXT AS name
    FROM challenge_templates ct
    WHERE ct.id = p_challenge_template_id AND ct.creator_id = p_user_id;
END;
$$;


CREATE FUNCTION mark_challenge_template_for_deletion(
    p_challenge_template_id BIGINT
) RETURNS VOID
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    UPDATE challenge_templates SET
        marked_for_deletion = TRUE
    WHERE id = p_challenge_template_id;
END;
$$;


CREATE FUNCTION get_running_instances_of_challenge_template(
    p_challenge_template_id BIGINT
) RETURNS TABLE (
    user_id BIGINT,
    challenge_id BIGINT
)
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    RETURN QUERY
    SELECT
        u.id::BIGINT AS user_id,
        c.id::BIGINT AS challenge_id
    FROM users u
    JOIN challenges c ON u.running_challenge = c.id
    WHERE c.challenge_template_id = p_challenge_template_id;
END;
$$;


CREATE FUNCTION count_active_deployments_of_challenge_template(
    p_challenge_template_id BIGINT
) RETURNS BIGINT
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    RETURN (
        SELECT COUNT(c.id) AS active_count
        FROM challenges c
        JOIN users u ON u.running_challenge = c.id
        WHERE c.challenge_template_id = p_challenge_template_id
        AND u.running_challenge IS NOT NULL
    )::BIGINT;
END;
$$;


CREATE FUNCTION mark_challenge_template_for_soft_deletion(
    p_challenge_template_id BIGINT
) RETURNS VOID
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    UPDATE challenge_templates SET
        marked_for_deletion = TRUE,
        is_active = FALSE
    WHERE id = p_challenge_template_id;
END;
$$;


CREATE FUNCTION get_challenge_templates_for_management(
    p_user_id BIGINT
) RETURNS TABLE (
    id BIGINT,
    name TEXT,
    description TEXT,
    category challenge_category,
    difficulty challenge_difficulty,
    image_path TEXT,
    is_active BOOLEAN,
    created_at TIMESTAMP,
    marked_for_deletion BOOLEAN,
    total_deployments BIGINT,
    hint TEXT,
    solution TEXT,
    active_deployments BIGINT,
    solve_count BIGINT,
    avg_completion_minutes BIGINT
)
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    RETURN QUERY
    WITH user_flags AS (
        SELECT
            challenge_template_id,
            user_id,
            flag_id,
            MAX(completed_at) AS flag_found_at
        FROM completed_challenges
        WHERE flag_id IS NOT NULL AND completed_at IS NOT NULL
        GROUP BY challenge_template_id, user_id, flag_id
    ),
    fully_solved AS (
        SELECT
            uf.challenge_template_id,
            uf.user_id,
            COUNT(DISTINCT uf.flag_id) AS found_flags,
            MAX(uf.flag_found_at) AS last_flag_time
        FROM user_flags uf
        GROUP BY uf.challenge_template_id, uf.user_id
        HAVING COUNT(DISTINCT uf.flag_id) = (
            SELECT COUNT(*) FROM challenge_flags cf
            WHERE cf.challenge_template_id = uf.challenge_template_id
        )
    ),
    valid_attempts AS (
        SELECT
            cc.challenge_template_id,
            cc.user_id,
            cc.started_at,
            cc.completed_at,
            EXTRACT(EPOCH FROM (cc.completed_at - cc.started_at))/60 AS duration_minutes
        FROM completed_challenges cc
        WHERE cc.started_at IS NOT NULL AND cc.completed_at IS NOT NULL
        AND EXTRACT(EPOCH FROM (cc.completed_at - cc.started_at)) > 10
    ),
    pre_completion_attempts AS (
        SELECT
            va.challenge_template_id,
            va.user_id,
            va.started_at,
            va.completed_at,
            va.duration_minutes
        FROM valid_attempts va
        JOIN fully_solved fs ON
            fs.challenge_template_id = va.challenge_template_id AND
            fs.user_id = va.user_id
        WHERE va.completed_at <= fs.last_flag_time
    ),
    aggregated_times AS (
        SELECT
            challenge_template_id,
            user_id,
            SUM(duration_minutes) AS total_duration
        FROM pre_completion_attempts
        GROUP BY challenge_template_id, user_id
    ),
    solved_stats AS (
        SELECT
            fs.challenge_template_id,
            COUNT(*) AS solve_count,
            ROUND(AVG(COALESCE(at.total_duration, 0))) AS avg_completion_minutes
        FROM fully_solved fs
        LEFT JOIN aggregated_times at ON at.challenge_template_id = fs.challenge_template_id AND at.user_id = fs.user_id
        GROUP BY fs.challenge_template_id
    ),
    active_deployments_table AS (
        SELECT
            c.challenge_template_id,
            COUNT(DISTINCT c.id) AS active_count
        FROM challenges c
        JOIN users u ON u.running_challenge = c.id
        WHERE u.running_challenge IS NOT NULL
        GROUP BY c.challenge_template_id
    ),
    real_deployments AS (
        SELECT
            challenge_template_id,
            COUNT(*) AS total_count
        FROM completed_challenges
        WHERE EXTRACT(EPOCH FROM (completed_at - started_at)) > 10
        OR completed_at IS NULL
        GROUP BY challenge_template_id
    )
    SELECT
        ct.id::BIGINT AS id,
        ct.name::TEXT AS name,
        ct.description::TEXT AS description,
        ct.category::challenge_category AS category,
        ct.difficulty::challenge_difficulty AS difficulty,
        ct.image_path::TEXT AS image_path,
        ct.is_active::BOOLEAN AS is_active,
        ct.created_at::TIMESTAMP AS created_at,
        ct.marked_for_deletion::BOOLEAN AS marked_for_deletion,
        COALESCE(rd.total_count, 0)::BIGINT AS total_deployments,
        ct.hint::TEXT AS hint,
        ct.solution::TEXT AS solution,
        COALESCE(ad.active_count, 0)::BIGINT AS active_deployments,
        COALESCE(ss.solve_count, 0)::BIGINT AS solve_count,
        COALESCE(ss.avg_completion_minutes, 0)::BIGINT AS avg_completion_minutes
    FROM challenge_templates ct
    LEFT JOIN solved_stats ss ON ss.challenge_template_id = ct.id
    LEFT JOIN active_deployments_table ad ON ad.challenge_template_id = ct.id
    LEFT JOIN real_deployments rd ON rd.challenge_template_id = ct.id
    WHERE ct.creator_id = p_user_id
    ORDER BY ct.created_at DESC;
END;
$$;


CREATE FUNCTION get_challenge_template_count_for_user(
    p_user_id BIGINT
) RETURNS BIGINT
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    RETURN (
        SELECT COUNT(*) FROM challenge_templates
        WHERE creator_id = p_user_id
    )::BIGINT;
END;
$$;


CREATE FUNCTION get_active_deployments_of_challenge_templates_by_user(
    p_user_id BIGINT
) RETURNS BIGINT
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    RETURN (
        SELECT COUNT(DISTINCT c.id)
        FROM challenges c
        JOIN users u ON u.running_challenge = c.id
        JOIN challenge_templates ct ON c.challenge_template_id = ct.id
        WHERE ct.creator_id = p_user_id AND u.running_challenge IS NOT NULL
    )::BIGINT;
END;
$$;


CREATE FUNCTION get_total_deployments_of_challenge_templates_by_user(
    p_user_id BIGINT
) RETURNS BIGINT
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    RETURN (
        SELECT COALESCE(SUM(total_count), 0)
        FROM (
            SELECT challenge_template_id, COUNT(*) AS total_count
            FROM completed_challenges
            WHERE EXTRACT(EPOCH FROM (completed_at - started_at)) > 2 OR completed_at IS NULL
            GROUP BY challenge_template_id
        ) rd
        JOIN challenge_templates ct ON rd.challenge_template_id = ct.id
        WHERE ct.creator_id = p_user_id
    )::BIGINT;
END;
$$;


CREATE FUNCTION get_average_completion_time_of_challenge_templates_by_user(
    p_user_id BIGINT
) RETURNS BIGINT
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    RETURN (
        WITH flag_counts AS (
                SELECT challenge_template_id, COUNT(*) AS total_flags
                FROM challenge_flags
                GROUP BY challenge_template_id
            ),
            user_flag_completions AS (
                SELECT
                    cc.challenge_template_id,
                    cc.user_id,
                    COUNT(DISTINCT cc.flag_id) AS flags_found,
                    MAX(cc.completed_at) AS last_flag_time
                FROM completed_challenges cc
                GROUP BY cc.challenge_template_id, cc.user_id
            ),
            successful_users AS (
                SELECT
                    ufc.challenge_template_id,
                    ufc.user_id,
                    ufc.last_flag_time
                FROM user_flag_completions ufc
                JOIN flag_counts fc ON ufc.challenge_template_id = fc.challenge_template_id
                WHERE ufc.flags_found = fc.total_flags
            ),
            valid_sessions AS (
                SELECT
                    cc.challenge_template_id,
                    cc.user_id,
                    cc.started_at,
                    cc.completed_at,
                    EXTRACT(EPOCH FROM (cc.completed_at - cc.started_at))/60 AS duration_minutes,
                    su.last_flag_time
                FROM completed_challenges cc
                JOIN successful_users su ON cc.challenge_template_id = su.challenge_template_id AND cc.user_id = su.user_id
                WHERE cc.started_at < su.last_flag_time
            ),
            avg_times AS (
                SELECT
                    challenge_template_id,
                    user_id,
                    SUM(duration_minutes) AS total_duration
                FROM valid_sessions
                GROUP BY challenge_template_id, user_id
            )
            SELECT COALESCE(ROUND(AVG(total_duration)), 0) AS avg_completion_minutes
            FROM avg_times
            JOIN challenge_templates ct ON avg_times.challenge_template_id = ct.id
            WHERE ct.creator_id = p_user_id
    )::BIGINT;
END;
$$;

