-- Hide unpublished exercises and count fully solved users, never collective partial submissions.
CREATE OR REPLACE FUNCTION api.explore_challenges(
    p_category challenge_category,
    p_difficulty challenge_difficulty,
    p_search TEXT,
    p_order_by TEXT,
    p_limit BIGINT,
    p_offset BIGINT
)
RETURNS TABLE (
    id BIGINT,
    name TEXT,
    description TEXT,
    category challenge_category,
    difficulty challenge_difficulty,
    created_at TIMESTAMP,
    image_path TEXT,
    is_active BOOLEAN,
    solved_count BIGINT,
    attempted_count BIGINT
)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, api, public
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    RETURN QUERY
    WITH solved_challenges AS (
        SELECT
            cc.user_id,
            cc.challenge_template_id
        FROM completed_challenges cc
        WHERE NOT EXISTS (
            SELECT 1
            FROM challenge_flags cf
            WHERE cf.challenge_template_id = cc.challenge_template_id
            AND NOT EXISTS (
                SELECT 1
                FROM completed_challenges ccf
                WHERE ccf.user_id = cc.user_id
                AND ccf.flag_id = cf.id
            )
        )
    ),
    solve_counts AS (
        SELECT
            challenge_template_id,
            COUNT(DISTINCT user_id) AS unique_solvers
        FROM solved_challenges
        GROUP BY challenge_template_id
    ),
    attempt_counts AS (
        SELECT
            challenge_template_id,
            COUNT(DISTINCT user_id) AS unique_attempts
        FROM completed_challenges
        GROUP BY challenge_template_id
    )
    SELECT
        ct.id::BIGINT,
        ct.name::TEXT,
        ct.description::TEXT,
        ct.category::challenge_category,
        ct.difficulty::challenge_difficulty,
        ct.created_at::TIMESTAMP,
        ct.image_path::TEXT,
        ct.is_active::BOOLEAN,
        COALESCE(s.unique_solvers, 0)::BIGINT AS solved_count,
        COALESCE(a.unique_attempts, 0)::BIGINT AS attempted_count
    FROM challenge_templates ct
    LEFT JOIN solve_counts s ON ct.id = s.challenge_template_id
    LEFT JOIN attempt_counts a ON ct.id = a.challenge_template_id
    WHERE ct.is_active AND NOT ct.marked_for_deletion
    AND (p_category IS NULL OR ct.category = p_category)
    AND (p_difficulty IS NULL OR ct.difficulty = p_difficulty)
    AND (p_search IS NULL OR ct.name ILIKE p_search OR ct.description ILIKE p_search)
    ORDER BY
        CASE
            WHEN p_order_by = 'date' THEN ct.created_at
        END DESC,
        CASE
            WHEN p_order_by = 'difficulty' THEN
                CASE ct.difficulty
                    WHEN 'easy' THEN 1
                    WHEN 'medium' THEN 2
                    WHEN 'hard' THEN 3
                    ELSE 4
                END
        END DESC,
        CASE
            WHEN p_order_by NOT IN ('date', 'difficulty') THEN solved_count
        END DESC,
        CASE
            WHEN p_order_by NOT IN ('date', 'difficulty') THEN attempted_count
        END DESC,
        ct.id
    LIMIT p_limit OFFSET p_offset;
END;
$$;


CREATE OR REPLACE FUNCTION api.explore_challenges_count(
    p_category challenge_category,
    p_difficulty challenge_difficulty,
    p_search TEXT
)
RETURNS BIGINT
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, api, public
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    RETURN (
        SELECT COUNT(*)::BIGINT
        FROM explore_challenges(
            p_category,
            p_difficulty,
            p_search,
            NULL,
            NULL,
            0
        )
    );
END;
$$;



CREATE OR REPLACE FUNCTION api.get_challenges_data_dashboard(
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
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, api, public
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
