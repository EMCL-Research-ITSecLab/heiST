CREATE FUNCTION get_solve_progress_data(
    p_user_id BIGINT,
    p_challenge_template_id BIGINT
) RETURNS TABLE (
    total_flags BIGINT,
    flags_completed BIGINT,
    is_solved BOOLEAN
)
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    RETURN QUERY
    SELECT
        COUNT(DISTINCT cf.id)::BIGINT AS total_flags,
        COUNT(DISTINCT cc.flag_id)::BIGINT AS flags_completed,
        (COUNT(DISTINCT cf.id) > 0 AND COUNT(DISTINCT cc.flag_id) >= COUNT(DISTINCT cf.id))::BOOLEAN AS is_solved
    FROM challenge_flags cf
    LEFT JOIN completed_challenges cc ON
        cf.id = cc.flag_id AND
        cc.user_id = p_user_id AND
        cc.challenge_template_id = p_challenge_template_id
    WHERE cf.challenge_template_id = p_challenge_template_id;
END;
$$;


CREATE FUNCTION get_elapsed_seconds_for_challenge(
    p_user_id BIGINT,
    p_challenge_template_id BIGINT
) RETURNS BIGINT
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    RETURN (
        WITH possible_flags AS (
                SELECT cf.id AS flag_id
                FROM challenge_flags cf
                WHERE cf.challenge_template_id = p_challenge_template_id
        ),
        submitted_flags AS (
            SELECT cc.flag_id AS flag_id
            FROM completed_challenges cc
            WHERE cc.user_id = p_user_id
              AND cc.challenge_template_id = p_challenge_template_id
              AND cc.flag_id IS NOT NULL
        ),
        eola AS (
            SELECT CASE
                WHEN NOT EXISTS (
                    SELECT 1
                    FROM possible_flags pf
                    WHERE NOT EXISTS (
                        SELECT 1
                        FROM submitted_flags sf
                        WHERE sf.flag_id = pf.flag_id
                    )
                ) THEN
                    (SELECT MAX(cc.completed_at)
                     FROM completed_challenges cc
                     WHERE cc.flag_id IS NOT NULL
                       AND cc.user_id = p_user_id
                       AND cc.challenge_template_id = p_challenge_template_id
                    )
                ELSE CURRENT_TIMESTAMP
            END AS end_of_last_interval
        ),
        intervals AS (
            SELECT COALESCE(cc.completed_at, CURRENT_TIMESTAMP) - cc.started_at AS intvl
            FROM completed_challenges cc, eola
            WHERE cc.user_id = p_user_id
              AND cc.challenge_template_id = p_challenge_template_id
              AND (COALESCE(cc.completed_at, CURRENT_TIMESTAMP) <= eola.end_of_last_interval)
        )
        SELECT EXTRACT(EPOCH FROM SUM(intervals.intvl))::BIGINT AS total_seconds FROM intervals
    );
END;
$$;


CREATE FUNCTION get_solved_leaderboard(
    p_challenge_template_id BIGINT
) RETURNS TABLE (
    username TEXT,
    avatar_url TEXT,
    total_seconds BIGINT,
    rank BIGINT
)
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    RETURN QUERY
    WITH possible_flags AS (
        SELECT cf.id AS flag_id
        FROM challenge_flags cf
        WHERE cf.challenge_template_id = p_challenge_template_id
    ),
    user_submissions AS (
        SELECT cc.user_id, cc.flag_id, cc.completed_at, cc.started_at
        FROM completed_challenges cc
        WHERE cc.challenge_template_id = p_challenge_template_id
    ),
    users_who_solved AS (
        SELECT us.user_id
        FROM (SELECT DISTINCT user_id FROM user_submissions) us
        WHERE NOT EXISTS (
            SELECT 1
            FROM possible_flags pf
            WHERE NOT EXISTS (
                SELECT 1
                FROM user_submissions s
                WHERE s.user_id = us.user_id AND s.flag_id = pf.flag_id
            )
        )
    ),
    user_eola AS (
        SELECT uws.user_id,
               (SELECT MAX(us3.completed_at)
                FROM user_submissions us3
                WHERE us3.user_id = uws.user_id AND us3.flag_id IS NOT NULL) AS end_of_last_interval
        FROM users_who_solved uws
    ),
    intervals AS (
        SELECT us.user_id,
               COALESCE(us.completed_at, CURRENT_TIMESTAMP) - us.started_at AS intvl
        FROM user_submissions us
        JOIN user_eola e ON us.user_id = e.user_id
        WHERE COALESCE(us.completed_at, CURRENT_TIMESTAMP) <= e.end_of_last_interval
    ),
    summed AS (
        SELECT user_id, EXTRACT(EPOCH FROM SUM(intvl))::BIGINT AS total_seconds
        FROM intervals
        GROUP BY user_id
    ),
    ranked AS (
        SELECT u.username, u.avatar_url, s.total_seconds,
               ROW_NUMBER() OVER (ORDER BY s.total_seconds) AS rank
        FROM summed s
        JOIN users u ON u.id = s.user_id
    )
    SELECT
        r.username::TEXT,
        r.avatar_url::TEXT,
        r.total_seconds::BIGINT,
        r.rank::BIGINT
    FROM ranked r
    ORDER BY r.rank
    LIMIT 10;
END;
$$;

CREATE FUNCTION get_challenge_leaderboard(
    p_challenge_template_id BIGINT,
    p_limit BIGINT,
    p_offset BIGINT
) RETURNS TABLE (
    username TEXT,
    avatar_url TEXT,
    total_points BIGINT,
    total_seconds BIGINT,
    rank BIGINT
)
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    RETURN QUERY
    WITH possible_flags AS (
        SELECT cf.id AS flag_id, cf.points
        FROM challenge_flags cf
        WHERE cf.challenge_template_id = p_challenge_template_id
    ),
    user_submissions AS (
        SELECT cc.user_id, cc.flag_id, cc.completed_at, cc.started_at
        FROM completed_challenges cc
        WHERE cc.challenge_template_id = p_challenge_template_id
    ),
    user_points AS (
        SELECT us.user_id, SUM(pf.points) AS total_points
        FROM user_submissions us
        JOIN possible_flags pf ON us.flag_id = pf.flag_id
        GROUP BY us.user_id
    ),
    user_eola AS (
        SELECT user_id, MAX(completed_at) AS end_of_last_flagged
        FROM user_submissions
        WHERE flag_id IS NOT NULL
        GROUP BY user_id
    ),
    valid_submissions AS (
        SELECT us.user_id, us.started_at, us.completed_at
        FROM user_submissions us
        JOIN user_eola eola ON us.user_id = eola.user_id
        WHERE us.completed_at <= eola.end_of_last_flagged

        UNION ALL

        SELECT us.user_id, us.started_at,
               CASE
                   WHEN us.completed_at IS NULL OR us.completed_at > eola.end_of_last_flagged
                   THEN eola.end_of_last_flagged
                   ELSE us.completed_at
               END AS completed_at
        FROM user_submissions us
        JOIN user_eola eola ON us.user_id = eola.user_id
        JOIN (
            SELECT user_id, MIN(started_at) as first_flag_started_at
            FROM user_submissions
            WHERE flag_id IS NOT NULL
            GROUP BY user_id
        ) first_flag ON us.user_id = first_flag.user_id
        WHERE us.started_at <= first_flag.first_flag_started_at
        AND (us.completed_at IS NULL OR us.completed_at > eola.end_of_last_flagged)
    ),
    intervals AS (
        SELECT user_id,
               completed_at - started_at AS intvl
        FROM valid_submissions
    ),
    summed_time AS (
        SELECT user_id, EXTRACT(EPOCH FROM SUM(intvl))::BIGINT AS total_seconds
        FROM intervals
        GROUP BY user_id
    ),
    ranked AS (
        SELECT u.username, u.avatar_url,
               up.total_points,
               st.total_seconds,
               ROW_NUMBER() OVER (ORDER BY up.total_points DESC, st.total_seconds) AS rank
        FROM user_points up
        JOIN summed_time st ON up.user_id = st.user_id
        JOIN users u ON u.id = up.user_id
    )
    SELECT
        r.username::TEXT,
        r.avatar_url::TEXT,
        r.total_points::BIGINT,
        r.total_seconds::BIGINT,
        r.rank::BIGINT
    FROM ranked r
    ORDER BY r.rank
    LIMIT p_limit OFFSET p_offset;
END;
$$;
