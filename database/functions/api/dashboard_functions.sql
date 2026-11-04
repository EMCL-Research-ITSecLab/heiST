CREATE FUNCTION get_user_data_dashboard(
    p_user_id BIGINT
) RETURNS TABLE (
    username TEXT,
    total_points BIGINT,
    solved_count BIGINT,
    user_rank BIGINT
)
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    RETURN QUERY
    WITH user_points AS (
        SELECT COALESCE(SUM(cf.points), 0) AS total
        FROM completed_challenges cc
        JOIN challenge_flags cf ON cc.flag_id = cf.id
        WHERE cc.user_id = p_user_id
    ),
    solved_challenges AS (
        SELECT cc.challenge_template_id
        FROM completed_challenges cc
        JOIN challenge_flags cf ON cc.flag_id = cf.id
        WHERE cc.user_id = p_user_id
        GROUP BY cc.challenge_template_id
        HAVING COUNT(DISTINCT cf.id) = (
            SELECT COUNT(id)
            FROM challenge_flags
            WHERE challenge_template_id = cc.challenge_template_id
        )
    )
    SELECT
        u.username::TEXT AS username,
        (SELECT total FROM user_points)::BIGINT AS total_points,
        (SELECT COUNT(*) FROM solved_challenges)::BIGINT AS solved_count,
        (
            SELECT COUNT(*) + 1
            FROM (
                SELECT u2.id, COALESCE(SUM(cf2.points), 0) AS points
                FROM users u2
                LEFT JOIN completed_challenges cc2 ON cc2.user_id = u2.id
                LEFT JOIN challenge_flags cf2 ON cc2.flag_id = cf2.id
                GROUP BY u2.id
                HAVING COALESCE(SUM(cf2.points), 0) > (SELECT total FROM user_points)
                OR (COALESCE(SUM(cf2.points), 0) = (SELECT total FROM user_points) AND u2.id < p_user_id)
            ) ranked_users
        )::BIGINT AS user_rank
    FROM users u
    WHERE u.id = p_user_id;
END;
$$;


CREATE FUNCTION get_progress_data_dashboard(
    p_user_id BIGINT
) RETURNS TABLE (
    solved_count BIGINT,
    failed_count BIGINT,
    total_attempts BIGINT,
    avg_time_seconds BIGINT
)
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    RETURN QUERY
    WITH solved_challenges AS (
        SELECT cc.challenge_template_id
        FROM completed_challenges cc
        JOIN challenge_flags cf ON cc.flag_id = cf.id
        WHERE cc.user_id = p_user_id
        GROUP BY cc.challenge_template_id
        HAVING COUNT(DISTINCT cf.id) = (
            SELECT COUNT(id)
            FROM challenge_flags
            WHERE challenge_template_id = cc.challenge_template_id
        )
    ),
    failed_attempts AS (
        SELECT COUNT(DISTINCT challenge_template_id) AS count
        FROM completed_challenges
        WHERE user_id = p_user_id
        AND completed_at IS NOT NULL
        AND challenge_template_id NOT IN (SELECT challenge_template_id FROM solved_challenges)
    )
    SELECT
        (SELECT COUNT(*) FROM solved_challenges)::BIGINT AS solved_count,
        (SELECT count FROM failed_attempts)::BIGINT AS failed_count,
        COUNT(DISTINCT challenge_template_id)::BIGINT AS total_attempts,
        AVG(
            CASE
                WHEN completed_at > started_at
                THEN EXTRACT(EPOCH FROM (completed_at - started_at))
                ELSE NULL
            END
        )::BIGINT AS avg_time_seconds
    FROM completed_challenges
    WHERE user_id = p_user_id;
END;
$$;


CREATE FUNCTION get_total_active_challenges_count_dashboard()
RETURNS BIGINT
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    RETURN (
        SELECT COUNT(*) AS total_challenges FROM challenge_templates WHERE is_active = true
    )::BIGINT;
END;
$$;


CREATE FUNCTION get_user_activity_dashboard(
    p_user_id BIGINT,
    p_limit BIGINT
) RETURNS TABLE (
    challenge_id BIGINT,
    challenge_name TEXT,
    category challenge_category,
    solved_points BIGINT,
    current_points BIGINT,
    solved BOOLEAN,
    attempts BIGINT,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    status TEXT,
    time_ago TEXT
)
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    RETURN QUERY
    WITH user_completed_flags AS (
        SELECT
            cc.challenge_template_id,
            cf.id AS flag_id,
            cf.points
        FROM completed_challenges cc
        JOIN challenge_flags cf ON cc.flag_id = cf.id
        WHERE cc.user_id = p_user_id
    ),
    solved_challenges AS (
        SELECT
            ucf.challenge_template_id,
            MAX(cc.completed_at) as completed_at,
            SUM(ucf.points) as total_points
        FROM user_completed_flags ucf
        JOIN completed_challenges cc ON cc.flag_id = ucf.flag_id AND cc.user_id = p_user_id
        GROUP BY ucf.challenge_template_id
        HAVING COUNT(DISTINCT ucf.flag_id) = (
            SELECT COUNT(id)
            FROM challenge_flags
            WHERE challenge_template_id = ucf.challenge_template_id
        )
    ),
    challenge_attempts AS (
        SELECT
            cc.challenge_template_id,
            COUNT(cc.id) AS attempts,
            MIN(cc.started_at) AS started_at,
            MAX(cc.completed_at) AS completed_at,
            BOOL_OR(cc.completed_at IS NOT NULL) AS has_completed_attempt,
            SUM(CASE WHEN cc.flag_id IS NOT NULL THEN
                (SELECT points FROM challenge_flags WHERE id = cc.flag_id)
            ELSE 0 END) AS earned_points
        FROM completed_challenges cc
        WHERE cc.user_id = p_user_id
        GROUP BY cc.challenge_template_id
    )
    SELECT
        ct.id::BIGINT AS challenge_id,
        ct.name::TEXT AS challenge_name,
        ct.category::challenge_category AS category,
        sc.total_points::BIGINT AS solved_points,
        ca.earned_points::BIGINT AS current_points,
        (sc.completed_at IS NOT NULL)::BOOLEAN AS solved,
        ca.attempts::BIGINT AS attempts,
        ca.started_at::TIMESTAMP AS started_at,
        ca.completed_at::TIMESTAMP AS completed_at,
        (CASE
            WHEN sc.completed_at IS NOT NULL THEN 'solved'
            WHEN ca.has_completed_attempt THEN 'failed'
            ELSE 'active'
        END)::TEXT AS status,
        (CASE
            WHEN sc.completed_at IS NOT NULL THEN
                CASE
                    WHEN EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - sc.completed_at)) / 3600 < 24 THEN
                        EXTRACT(HOUR FROM (CURRENT_TIMESTAMP - sc.completed_at)) || ' hours ago'
                    ELSE
                        EXTRACT(DAY FROM (CURRENT_TIMESTAMP - sc.completed_at)) || ' days ago'
                END
            WHEN ca.completed_at IS NOT NULL THEN
                CASE
                    WHEN EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - ca.completed_at)) / 3600 < 24 THEN
                        'Failed ' || EXTRACT(HOUR FROM (CURRENT_TIMESTAMP - ca.completed_at)) || ' hours ago'
                    ELSE
                        'Failed ' || EXTRACT(DAY FROM (CURRENT_TIMESTAMP - ca.completed_at)) || ' days ago'
                END
            ELSE
                CASE
                    WHEN EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - ca.started_at)) / 3600 < 24 THEN
                        'Started ' || EXTRACT(HOUR FROM (CURRENT_TIMESTAMP - ca.started_at)) || ' hours ago'
                    ELSE
                        'Started ' || EXTRACT(DAY FROM (CURRENT_TIMESTAMP - ca.started_at)) || ' days ago'
                END
        END)::TEXT AS time_ago
    FROM challenge_templates ct
    JOIN challenge_attempts ca ON ca.challenge_template_id = ct.id
    LEFT JOIN solved_challenges sc ON sc.challenge_template_id = ct.id
    WHERE EXISTS (
        SELECT 1 FROM completed_challenges
        WHERE user_id = p_user_id AND challenge_template_id = ct.id
    )
    ORDER BY COALESCE(sc.completed_at, ca.completed_at, ca.started_at) DESC
    LIMIT p_limit;
END;
$$;


CREATE FUNCTION get_user_badges_data_dashboard(
    p_user_id BIGINT
) RETURNS TABLE (
    id BIGINT,
    name TEXT,
    description TEXT,
    icon TEXT,
    color badge_color
)
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    RETURN QUERY
    SELECT
        b.id::BIGINT,
        b.name::TEXT,
        b.description::TEXT,
        b.icon::TEXT,
        b.color::badge_color
    FROM user_badges ub
    JOIN badges b ON b.id = ub.badge_id
    WHERE ub.user_id = p_user_id;
END;
$$;


CREATE FUNCTION get_user_progress_data_dashboard(
    p_user_id BIGINT
) RETURNS TABLE (
    solved_count BIGINT,
    total_badges BIGINT,
    earned_badges BIGINT
)
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    RETURN QUERY
    WITH user_completed_flags AS (
        SELECT DISTINCT challenge_template_id, flag_id
        FROM completed_challenges
        WHERE user_id = p_user_id
    ),
    challenge_total_flags AS (
        SELECT challenge_template_id, COUNT(*) as total_flags
        FROM challenge_flags
        GROUP BY challenge_template_id
    ),
    user_solved_challenges AS (
        SELECT ctf.challenge_template_id
        FROM challenge_total_flags ctf
        JOIN (
            SELECT challenge_template_id, COUNT(DISTINCT flag_id) as completed_flags
            FROM user_completed_flags
            GROUP BY challenge_template_id
        ) ucf ON ctf.challenge_template_id = ucf.challenge_template_id
        WHERE ctf.total_flags = ucf.completed_flags
    )
    SELECT
        COUNT(*)::BIGINT AS solved_count,
        (SELECT COUNT(*) FROM badges)::BIGINT AS total_badges,
        (SELECT COUNT(*) FROM user_badges WHERE user_id = p_user_id)::BIGINT AS earned_badges
    FROM user_solved_challenges;
END;
$$;


CREATE FUNCTION get_challenges_data_dashboard(
    p_user_id BIGINT
) RETURNS TABLE (
    id BIGINT,
    name TEXT,
    category challenge_category,
    points BIGINT,
    difficulty challenge_difficulty,
    solved_count BIGINT,
    attempted_count BIGINT
)
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    RETURN QUERY
    WITH per_user_solved AS (
        SELECT cc.challenge_template_id, cc.user_id
        FROM completed_challenges cc
        JOIN challenge_flags cf ON cc.flag_id = cf.id
        GROUP BY cc.challenge_template_id, cc.user_id
        HAVING COUNT(DISTINCT cf.id) = (
            SELECT COUNT(*) FROM challenge_flags f WHERE f.challenge_template_id = cc.challenge_template_id
        )
    ),
    user_solved_challenges AS (
        SELECT challenge_template_id FROM per_user_solved WHERE user_id = p_user_id
    ),
    global_solved_counts AS (
        SELECT challenge_template_id, COUNT(*) AS solved_count
        FROM per_user_solved GROUP BY challenge_template_id
    ),
    attempted_counts AS (
        SELECT
            challenge_template_id,
            COUNT(DISTINCT user_id) AS attempted_count
        FROM completed_challenges
        GROUP BY challenge_template_id
    )
    SELECT
        ct.id::BIGINT AS id,
        ct.name::TEXT AS name,
        ct.category::challenge_category AS category,
        (SELECT SUM(cf.points) FROM challenge_flags cf WHERE challenge_template_id = ct.id)::BIGINT AS points,
        ct.difficulty::challenge_difficulty AS difficulty,
        COALESCE(gsc.solved_count, 0)::BIGINT AS solved_count,
        COALESCE(ac.attempted_count, 0)::BIGINT AS attempted_count
    FROM challenge_templates ct
    LEFT JOIN global_solved_counts gsc ON gsc.challenge_template_id = ct.id
    LEFT JOIN attempted_counts ac ON ac.challenge_template_id = ct.id
    WHERE ct.is_active AND NOT ct.marked_for_deletion AND NOT EXISTS (
        SELECT 1 FROM user_solved_challenges usc
        WHERE usc.challenge_template_id = ct.id
    )
    ORDER BY
        CASE ct.difficulty
            WHEN 'easy' THEN 1
            WHEN 'medium' THEN 2
            WHEN 'hard' THEN 3
            ELSE 0
        END,
        COALESCE(gsc.solved_count, 0)::float / NULLIF(COALESCE(ac.attempted_count, 0), 0) DESC
    LIMIT 5;
END;
$$;


CREATE FUNCTION get_timeline_data_dashboard(
    p_user_id BIGINT,
    p_start_date TEXT,
    p_end_date TEXT,
    p_range TEXT,
    p_date_format TEXT
) RETURNS TABLE (
    date_group TEXT,
    points_sum BIGINT,
    challenge_count BIGINT,
    challenge_details TEXT
)
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    RETURN QUERY
    WITH date_series AS (
        SELECT generate_series(
            p_start_date::timestamp,
            p_end_date::timestamp,
            CASE
                WHEN p_range = 'week' THEN INTERVAL '1 day'
                WHEN p_range = 'month' THEN INTERVAL '1 day'
                WHEN p_range = 'year' THEN INTERVAL '1 month'
                ELSE INTERVAL '1 day'
            END
        )::date AS date
    ),
    flag_submissions AS (
        SELECT
            cc.id,
            cc.challenge_template_id,
            cf.points,
            TO_CHAR(cc.completed_at, p_date_format) AS date_group,
            cc.completed_at
        FROM completed_challenges cc
        JOIN challenge_flags cf ON cc.flag_id = cf.id
        WHERE cc.user_id = p_user_id
        AND cc.completed_at IS NOT NULL
    ),
    daily_points AS (
        SELECT
            ds.date,
            TO_CHAR(ds.date, p_date_format) AS date_group,
            COALESCE(SUM(fs.points), 0) AS points_sum,
            COUNT(DISTINCT fs.challenge_template_id) AS challenge_count,
            STRING_AGG(DISTINCT CONCAT(
                (SELECT name FROM challenge_templates WHERE id = fs.challenge_template_id),
                '|',
                (SELECT category FROM challenge_templates WHERE id = fs.challenge_template_id),
                '|',
                fs.points
            ), ',') AS challenge_details
        FROM date_series ds
        LEFT JOIN flag_submissions fs ON TO_CHAR(ds.date, p_date_format) = fs.date_group
        GROUP BY ds.date, TO_CHAR(ds.date, p_date_format)
        ORDER BY ds.date
    )
    SELECT
        dp.date_group::TEXT,
        dp.points_sum::BIGINT,
        dp.challenge_count::BIGINT,
        dp.challenge_details::TEXT
    FROM daily_points dp;
END;
$$;


CREATE FUNCTION get_announcements_data_dashboard()
RETURNS TABLE (
    id BIGINT,
    title TEXT,
    short_description TEXT,
    importance announcement_importance,
    category announcement_category,
    author TEXT,
    created_at TEXT
)
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    RETURN QUERY
    SELECT
        a.id::BIGINT AS id,
        a.title::TEXT AS title,
        a.short_description::TEXT AS short_description,
        a.importance::announcement_importance AS importance,
        a.category::announcement_category AS category,
        a.author::TEXT AS author,
        TO_CHAR(a.created_at, 'YYYY-MM-DD')::TEXT AS created_at
    FROM announcements a
    ORDER BY a.created_at DESC
    LIMIT 3;
END;
$$;


CREATE FUNCTION get_challenge_template_id_from_challenge_id(
    p_challenge_id BIGINT
) RETURNS BIGINT
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    RETURN (
        SELECT challenge_template_id
        FROM completed_challenges
        WHERE id = p_challenge_id
        LIMIT 1
    )::BIGINT;
END;
$$;


CREATE FUNCTION get_running_challenge_data_dashboard(
    p_user_id BIGINT,
    p_challenge_template_id BIGINT
)
RETURNS TABLE (
    id BIGINT,
    name TEXT,
    category challenge_category,
    difficulty challenge_difficulty,
    points BIGINT,
    current_attempt_started_at TIMESTAMP,
    completed_challenge_id BIGINT
)
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    RETURN QUERY
    SELECT
        ct.id::BIGINT AS id,
        ct.name::TEXT AS name,
        ct.category::challenge_category AS category,
        ct.difficulty::challenge_difficulty AS difficulty,
        (SELECT SUM(cf.points) FROM challenge_flags cf WHERE challenge_template_id = ct.id)::BIGINT AS points,
        cc.started_at::TIMESTAMP AS current_attempt_started_at,
        cc.id::BIGINT AS completed_challenge_id
    FROM challenge_templates ct
    LEFT JOIN completed_challenges cc
        ON cc.user_id = p_user_id
        AND cc.challenge_template_id = ct.id
        AND cc.completed_at IS NULL
    WHERE ct.id = p_challenge_template_id
    LIMIT 1;
END;
$$;

