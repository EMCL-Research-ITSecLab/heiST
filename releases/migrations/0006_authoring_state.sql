CREATE FUNCTION api.web_template_state(p_template_id BIGINT)
RETURNS TABLE(ready BOOLEAN, instances BIGINT)
LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
    SELECT t.ready_to_launch, (SELECT COUNT(*) FROM public.challenges c WHERE c.challenge_template_id=t.id)
    FROM public.challenge_templates t WHERE t.id=p_template_id;
$$;
REVOKE ALL ON FUNCTION api.web_template_state(BIGINT) FROM PUBLIC;
DO $$
DECLARE v_role TEXT := current_setting('heist.web_api_role', TRUE);
BEGIN
    IF v_role IS NULL OR v_role = '' THEN
        RAISE EXCEPTION 'Declare the restricted web API role before this migration';
    END IF;
    EXECUTE format('GRANT EXECUTE ON FUNCTION api.web_template_state(BIGINT) TO %I', v_role);
END;
$$;

CREATE OR REPLACE FUNCTION api.get_challenge_templates_for_management(
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
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, api, public
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

-- Trusted persistent schemas precede pg_temp for every SECURITY DEFINER API
-- function, including legacy procedures with unqualified table references.
DO $$
DECLARE f RECORD;
BEGIN
    FOR f IN SELECT p.proname, pg_get_function_identity_arguments(p.oid) AS arguments
        FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace WHERE n.nspname = 'api'
    LOOP
        EXECUTE format('ALTER FUNCTION api.%I(%s) SET search_path = pg_catalog, api, public, pg_temp', f.proname, f.arguments);
    END LOOP;
END;
$$;
