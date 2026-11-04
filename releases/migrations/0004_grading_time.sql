-- Preserve protected data; correct grading, time accounting and extension semantics.

CREATE OR REPLACE FUNCTION api.get_solve_progress_data(
    p_user_id BIGINT,
    p_challenge_template_id BIGINT
) RETURNS TABLE (
    total_flags BIGINT,
    flags_completed BIGINT,
    is_solved BOOLEAN
)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, api, public
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

CREATE OR REPLACE FUNCTION api.get_elapsed_seconds_for_challenge(
    p_user_id BIGINT,
    p_challenge_template_id BIGINT
) RETURNS BIGINT
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, api, public
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

CREATE OR REPLACE FUNCTION api.extend_user_challenge_time(
    p_challenge_id BIGINT,
    p_extend_scalar BIGINT
) RETURNS VOID
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, api, public
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    UPDATE challenges
    SET
        expires_at = GREATEST(expires_at, CURRENT_TIMESTAMP) + (p_extend_scalar * INTERVAL '1 hour'),
        used_extensions = used_extensions + 1
    WHERE id = p_challenge_id;
END;
$$;

CREATE FUNCTION api.web_challenge_grade_lock(p_template_id BIGINT)
RETURNS VOID LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
    SELECT pg_advisory_xact_lock(hashtextextended('heist-web-grade:' || p_template_id::text, 0));
$$;
REVOKE ALL ON FUNCTION api.web_challenge_grade_lock(BIGINT) FROM PUBLIC;
DO $$
DECLARE v_role TEXT := current_setting('heist.web_api_role', TRUE);
BEGIN
    IF v_role IS NULL OR v_role = '' THEN
        RAISE EXCEPTION 'Declare the restricted web API role before this migration';
    END IF;
    EXECUTE format('GRANT EXECUTE ON FUNCTION api.web_challenge_grade_lock(BIGINT) TO %I', v_role);
END;
$$;
