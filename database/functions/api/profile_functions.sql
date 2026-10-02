CREATE FUNCTION get_basic_profile_data(p_user_id BIGINT)
RETURNS TABLE (
    username TEXT,
    email TEXT,
    created_at TIMESTAMP,
    last_login TIMESTAMP,
    avatar_url TEXT,
    full_name TEXT,
    bio TEXT,
    github_url TEXT,
    twitter_url TEXT,
    website_url TEXT,
    solved_count BIGINT,
    total_points BIGINT,
    ai_training_consent BOOLEAN
)
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    RETURN QUERY
    WITH flag_counts AS (
        SELECT challenge_template_id, COUNT(*) AS total_flags
        FROM challenge_flags
        GROUP BY challenge_template_id
    ),
    user_flags AS (
        SELECT cc.challenge_template_id, COUNT(DISTINCT cc.flag_id) AS user_flag_count
        FROM completed_challenges cc
        JOIN challenge_flags cf ON cc.flag_id = cf.id
        WHERE cc.user_id = p_user_id
        GROUP BY cc.challenge_template_id
    ),
    solved AS (
        SELECT uf.challenge_template_id
        FROM user_flags uf
        JOIN flag_counts fc ON uf.challenge_template_id = fc.challenge_template_id
        WHERE uf.user_flag_count = fc.total_flags
    ),
    total_points AS (
        SELECT COALESCE(SUM(cf.points), 0) AS total_points
        FROM completed_challenges cc
        JOIN challenge_flags cf ON cc.flag_id = cf.id
        WHERE cc.user_id = p_user_id
    )
    SELECT
        u.username::TEXT,
        u.email::TEXT,
        u.created_at::TIMESTAMP,
        u.last_login::TIMESTAMP,
        u.avatar_url::TEXT,
        p.full_name::TEXT,
        p.bio::TEXT,
        p.github_url::TEXT,
        p.twitter_url::TEXT,
        p.website_url::TEXT,
        (SELECT COUNT(*) FROM solved)::BIGINT AS solved_count,
        (SELECT tp.total_points FROM total_points tp)::BIGINT AS total_points,
        u.ai_training_consent::BOOLEAN
    FROM users u
    LEFT JOIN user_profiles p ON p.user_id = u.id
    WHERE u.id = p_user_id;
END;
$$;


CREATE FUNCTION get_user_rank(p_user_id BIGINT, p_user_points BIGINT)
RETURNS BIGINT
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    RETURN (
        SELECT COUNT(*) + 1 AS user_rank
        FROM (
            SELECT u.id, COALESCE(SUM(cf.points), 0) AS points
            FROM users u
            LEFT JOIN completed_challenges cc ON cc.user_id = u.id
            LEFT JOIN challenge_flags cf ON cc.flag_id = cf.id
            GROUP BY u.id
            HAVING COALESCE(SUM(cf.points), 0) > p_user_points
                OR (COALESCE(SUM(cf.points), 0) = p_user_points AND u.id < p_user_id)
        ) ranked_users
    )::BIGINT;
END;
$$;


CREATE FUNCTION get_profile_stats(p_user_id BIGINT)
RETURNS TABLE (
    solved BIGINT,
    attempts BIGINT,
    total_points BIGINT
)
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    RETURN QUERY
    WITH flag_counts AS (
        SELECT challenge_template_id, COUNT(*) AS total_flags
        FROM challenge_flags
        GROUP BY challenge_template_id
    ),
    user_flags AS (
        SELECT cc.challenge_template_id, COUNT(DISTINCT cc.flag_id) AS user_flag_count
        FROM completed_challenges cc
        JOIN challenge_flags cf ON cc.flag_id = cf.id
        WHERE cc.user_id = p_user_id
        GROUP BY cc.challenge_template_id
    ),
    solved AS (
        SELECT uf.challenge_template_id
        FROM user_flags uf
        JOIN flag_counts fc ON uf.challenge_template_id = fc.challenge_template_id
        WHERE uf.user_flag_count = fc.total_flags
    ),
    total_points AS (
        SELECT COALESCE(SUM(cf.points), 0) AS total_points
        FROM completed_challenges cc
        JOIN challenge_flags cf ON cc.flag_id = cf.id
        WHERE cc.user_id = p_user_id
    )
    SELECT
        (SELECT COUNT(*) FROM solved)::BIGINT AS solved,
        (SELECT COUNT(DISTINCT challenge_template_id) FROM completed_challenges WHERE user_id = p_user_id)::BIGINT AS attempts,
        (SELECT tp.total_points FROM total_points tp)::BIGINT AS total_points;
END;
$$;


CREATE FUNCTION get_profile_badges(p_user_id BIGINT)
RETURNS TABLE (
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
    WHERE ub.user_id = p_user_id
    ORDER BY b.rarity DESC, ub.earned_at DESC;
END;
$$;


CREATE FUNCTION get_total_badges_count()
RETURNS BIGINT
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    RETURN (SELECT COUNT(*) AS total FROM badges)::BIGINT;
END;
$$;


CREATE FUNCTION get_recent_activity(p_user_id BIGINT, p_limit BIGINT)
RETURNS TABLE (
    challenge_id BIGINT,
    challenge_name TEXT,
    category challenge_category,
    points BIGINT,
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
    WITH solved_challenges AS (
        SELECT cc.challenge_template_id, MAX(cc.completed_at) as completed_at
        FROM completed_challenges cc
        JOIN challenge_flags cf ON cc.flag_id = cf.id
        WHERE cc.user_id = p_user_id
        GROUP BY cc.challenge_template_id
        HAVING COUNT(DISTINCT cf.id) = (
            SELECT COUNT(*)
            FROM challenge_flags
            WHERE challenge_template_id = cc.challenge_template_id
        )
    ),
    challenge_attempts AS (
        SELECT
            cc.challenge_template_id,
            COUNT(cc.id) AS attempts,
            MIN(cc.started_at) AS started_at,
            MAX(cc.completed_at) AS completed_at,
            BOOL_OR(cc.completed_at IS NOT NULL) AS has_completed_attempt
        FROM completed_challenges cc
        WHERE cc.user_id = p_user_id
        GROUP BY cc.challenge_template_id
    )
    SELECT
        ct.id::BIGINT AS challenge_id,
        ct.name::TEXT AS challenge_name,
        ct.category::challenge_category AS category,
        (SELECT MAX(cf.points) FROM challenge_flags cf WHERE cf.challenge_template_id = ct.id)::BIGINT AS points,
        (sc.completed_at IS NOT NULL)::BOOLEAN AS solved,
        ca.attempts::BIGINT AS attempts,
        ca.started_at::TIMESTAMP AS started_at,
        ca.completed_at::TIMESTAMP AS completed_at,
        (CASE
            WHEN sc.completed_at IS NOT NULL THEN 'solved'
            WHEN ca.has_completed_attempt THEN 'failed'
            ELSE 'started'
        END)::TEXT AS status,
        (CASE
            WHEN sc.completed_at IS NOT NULL THEN
                CASE
                    WHEN EXTRACT(HOUR FROM (CURRENT_TIMESTAMP - sc.completed_at)) < 24
                    THEN EXTRACT(HOUR FROM (CURRENT_TIMESTAMP - sc.completed_at)) || ' hours ago'
                    ELSE EXTRACT(DAY FROM (CURRENT_TIMESTAMP - sc.completed_at)) || ' days ago'
                END
            WHEN ca.completed_at IS NOT NULL THEN
                CASE
                    WHEN EXTRACT(HOUR FROM (CURRENT_TIMESTAMP - ca.completed_at)) < 24
                    THEN 'Failed ' || EXTRACT(HOUR FROM (CURRENT_TIMESTAMP - ca.completed_at)) || ' hours ago'
                    ELSE 'Failed ' || EXTRACT(DAY FROM (CURRENT_TIMESTAMP - ca.completed_at)) || ' days ago'
                END
            ELSE
                CASE
                    WHEN EXTRACT(HOUR FROM (CURRENT_TIMESTAMP - ca.started_at)) < 24
                    THEN 'Started ' || EXTRACT(HOUR FROM (CURRENT_TIMESTAMP - ca.started_at)) || ' hours ago'
                    ELSE 'Started ' || EXTRACT(DAY FROM (CURRENT_TIMESTAMP - ca.started_at)) || ' days ago'
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


CREATE FUNCTION is_username_taken_by_other_user(
    p_user_id BIGINT,
    p_username TEXT
)
RETURNS BOOLEAN
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    RETURN (
        SELECT EXISTS (SELECT 1 FROM users WHERE username = p_username AND id <> p_user_id)
    )::BOOLEAN;
END;
$$;


CREATE FUNCTION update_username(
    p_user_id BIGINT,
    p_new_username TEXT,
    p_ip_addr INET
)
RETURNS VOID
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
DECLARE
    v_old_username TEXT;
    v_email TEXT;
BEGIN
    SELECT username, email INTO v_old_username, v_email
    FROM users
    WHERE id = p_user_id;

    UPDATE users
    SET username = p_new_username
    WHERE id = p_user_id;

    INSERT INTO user_identification_history (
        username_old,
        username_new,
        email_old,
        email_new,
        ip_addr,
        changed_at
    )
    VALUES (
        v_old_username,
        p_new_username,
        v_email,
        v_email,
        p_ip_addr,
        CURRENT_TIMESTAMP
    );
END;
$$;


CREATE FUNCTION is_email_taken_by_other_user(
    p_user_id BIGINT,
    p_email TEXT
)
RETURNS BOOLEAN
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    RETURN (
        SELECT EXISTS (SELECT 1 FROM users WHERE email = p_email AND id <> p_user_id)
    )::BOOLEAN;
END;
$$;


CREATE FUNCTION update_email(
    p_user_id BIGINT,
    p_new_email TEXT,
    p_ip_addr INET
)
RETURNS VOID
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
DECLARE
    v_old_email TEXT;
    v_username TEXT;
BEGIN
    SELECT email, username INTO v_old_email, v_username
    FROM users
    WHERE id = p_user_id;

    UPDATE users
    SET email = p_new_email
    WHERE id = p_user_id;

    INSERT INTO user_identification_history (
        username_old,
        username_new,
        email_old,
        email_new,
        ip_addr,
        changed_at
    )
    VALUES (
        v_username,
        v_username,
        v_old_email,
        p_new_email,
        p_ip_addr,
        CURRENT_TIMESTAMP
    );
END;
$$;


CREATE FUNCTION user_profile_exists(p_user_id BIGINT)
RETURNS BOOLEAN
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    RETURN (
        SELECT EXISTS (SELECT 1 FROM user_profiles WHERE user_id = p_user_id)
    )::BOOLEAN;
END;
$$;


CREATE FUNCTION update_full_name(
    p_user_id BIGINT,
    p_full_name TEXT
)
RETURNS VOID
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    IF user_profile_exists(p_user_id) THEN
        UPDATE user_profiles
        SET full_name = p_full_name
        WHERE user_id = p_user_id;
    ELSE
        INSERT INTO user_profiles (user_id, full_name)
        VALUES (p_user_id, p_full_name);
    END IF;
END;
$$;


CREATE FUNCTION update_bio(
    p_user_id BIGINT,
    p_bio TEXT
)
RETURNS VOID
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    IF user_profile_exists(p_user_id) THEN
        UPDATE user_profiles
        SET bio = p_bio
        WHERE user_id = p_user_id;
    ELSE
        INSERT INTO user_profiles (user_id, bio)
        VALUES (p_user_id, p_bio);
    END IF;
END;
$$;


CREATE FUNCTION update_urls(
    p_user_id BIGINT,
    p_github_url TEXT,
    p_twitter_url TEXT,
    p_website_url TEXT
)
RETURNS VOID
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    IF user_profile_exists(p_user_id) THEN
        UPDATE user_profiles
        SET github_url = p_github_url,
            twitter_url = p_twitter_url,
            website_url = p_website_url
        WHERE user_id = p_user_id;
    ELSE
        INSERT INTO user_profiles (user_id, github_url, twitter_url, website_url)
        VALUES (p_user_id, p_github_url, p_twitter_url, p_website_url);
    END IF;
END;
$$;


CREATE FUNCTION get_user_avatar(p_user_id BIGINT)
RETURNS TEXT
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    RETURN (SELECT avatar_url FROM users WHERE id = p_user_id)::TEXT;
END;
$$;


CREATE FUNCTION update_user_avatar(
    p_user_id BIGINT,
    p_avatar_url TEXT
)
RETURNS VOID
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    UPDATE users
    SET avatar_url = p_avatar_url
    WHERE id = p_user_id;
END;
$$;


CREATE FUNCTION get_all_challenge_categories()
RETURNS TABLE (
    category challenge_category
)
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    RETURN QUERY
    SELECT unnest(
        enum_range(NULL::challenge_category)
    ) AS category
    ORDER BY category;
END;
$$;


CREATE FUNCTION get_challenge_count_by_categories()
RETURNS TABLE (
    category challenge_category,
    total BIGINT
)
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    RETURN QUERY
    SELECT
        ct.category::challenge_category,
        COUNT(ct.id)::BIGINT AS total
    FROM challenge_templates ct
    GROUP BY ct.category
    ORDER BY ct.category;
END;
$$;


CREATE FUNCTION get_user_solved_challenge_count_by_categories(p_user_id BIGINT)
RETURNS TABLE (
    category challenge_category,
    solved BIGINT
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
            SELECT COUNT(*)
            FROM challenge_flags
            WHERE challenge_template_id = cc.challenge_template_id
        )
    )
    SELECT
        ct.category::challenge_category,
        COUNT(sc.challenge_template_id)::BIGINT as solved
    FROM solved_challenges sc
    JOIN challenge_templates ct ON ct.id = sc.challenge_template_id
    GROUP BY ct.category
    ORDER BY ct.category;
END;
$$;


CREATE FUNCTION get_user_disk_files_display_data(p_user_id BIGINT)
RETURNS TABLE(
    ova_id BIGINT,
    proxmox_filename TEXT
)
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    RETURN QUERY
    SELECT
        df.id::BIGINT AS ova_id,
        df.proxmox_filename::TEXT AS proxmox_filename
    FROM disk_files df
    WHERE user_id = p_user_id;
END;
$$;


CREATE FUNCTION delete_user_disk_files(
    p_user_id BIGINT,
    p_ova_id BIGINT,
    p_hashed_password TEXT
)
RETURNS VOID
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM users WHERE id = p_user_id AND password_hash = p_hashed_password) THEN
        DELETE FROM disk_files
        WHERE user_id = p_user_id AND id = p_ova_id;
    ELSE
        RAISE EXCEPTION 'Authentication failed: Invalid password.';
    END IF;
END;
$$;


CREATE FUNCTION delete_user_data(
    p_user_id BIGINT,
    p_hashed_password TEXT,
    p_ip_addr INET
)
RETURNS VOID
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
DECLARE
    v_username TEXT;
    v_email TEXT;
BEGIN
    SELECT username, email INTO v_username, v_email
    FROM users
    WHERE id = p_user_id;

    IF FOUND AND (SELECT password_hash FROM users WHERE id = p_user_id) = p_hashed_password THEN
        DELETE FROM user_badges WHERE user_id = p_user_id;
        DELETE FROM user_profiles WHERE user_id = p_user_id;
        DELETE FROM completed_challenges WHERE user_id = p_user_id;
        DELETE FROM disk_files WHERE user_id = p_user_id;
        UPDATE vpn_static_ips SET user_id = NULL WHERE user_id = p_user_id;
        DELETE FROM users WHERE id = p_user_id;

        INSERT INTO user_identification_history (
            username_old,
            username_new,
            email_old,
            email_new,
            ip_addr,
            deleted,
            changed_at
        )
        VALUES (
            v_username,
            NULL,
            v_email,
            NULL,
            p_ip_addr,
            TRUE,
            CURRENT_TIMESTAMP
        );
    ELSE
        RAISE EXCEPTION 'Authentication failed: Invalid password.';
    END IF;
END;
$$;


CREATE FUNCTION get_header_data(p_user_id BIGINT)
RETURNS TABLE (
    avatar_url TEXT,
    is_admin BOOLEAN
)
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    RETURN QUERY
    SELECT
        u.avatar_url::TEXT,
        u.is_admin::BOOLEAN
    FROM users u
    WHERE u.id = p_user_id;
END;
$$;


CREATE FUNCTION get_id_by_username(p_username TEXT)
RETURNS BIGINT
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    RETURN (SELECT id FROM users WHERE username = p_username)::BIGINT;
END;
$$;


CREATE FUNCTION get_public_profile_data(p_user_id BIGINT)
RETURNS TABLE (
    username TEXT,
    created_at TIMESTAMP,
    avatar_url TEXT,
    full_name TEXT,
    bio TEXT,
    github_url TEXT,
    twitter_url TEXT,
    website_url TEXT,
    solved_count BIGINT,
    total_points BIGINT
)
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    RETURN QUERY
    WITH flag_counts AS (
        SELECT challenge_template_id, COUNT(*) AS total_flags
        FROM challenge_flags
        GROUP BY challenge_template_id
    ),
    user_flags AS (
        SELECT cc.challenge_template_id, COUNT(DISTINCT cc.flag_id) AS user_flag_count
        FROM completed_challenges cc
        JOIN challenge_flags cf ON cc.flag_id = cf.id
        WHERE cc.user_id = p_user_id
        GROUP BY cc.challenge_template_id
    ),
    solved AS (
        SELECT uf.challenge_template_id
        FROM user_flags uf
        JOIN flag_counts fc ON uf.challenge_template_id = fc.challenge_template_id
        WHERE uf.user_flag_count = fc.total_flags
    ),
    total_points AS (
        SELECT COALESCE(SUM(cf.points), 0) AS total_points
        FROM completed_challenges cc
        JOIN challenge_flags cf ON cc.flag_id = cf.id
        WHERE cc.user_id = p_user_id
    )
    SELECT
        u.username::TEXT,
        u.created_at::TIMESTAMP,
        u.avatar_url::TEXT,
        p.full_name::TEXT,
        p.bio::TEXT,
        p.github_url::TEXT,
        p.twitter_url::TEXT,
        p.website_url::TEXT,
        (SELECT COUNT(*) FROM solved)::BIGINT AS solved_count,
        (SELECT tp.total_points FROM total_points tp)::BIGINT AS total_points
    FROM users u
    LEFT JOIN user_profiles p ON p.user_id = u.id
    WHERE u.id = p_user_id;
END;
$$;


CREATE FUNCTION get_active_challenge_templates_by_category()
RETURNS TABLE (
    category challenge_category,
    total BIGINT
)
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    RETURN QUERY
    SELECT
        ct.category::challenge_category,
        COUNT(*)::BIGINT as total
    FROM challenge_templates ct
    WHERE ct.is_active = true
    GROUP BY ct.category
    ORDER BY ct.category;
END;
$$;

CREATE FUNCTION get_user_earned_badges_data(p_user_id BIGINT)
RETURNS TABLE (
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
    WHERE ub.user_id = p_user_id
    ORDER BY b.rarity DESC, ub.earned_at DESC, b.id;
END;
$$;

CREATE FUNCTION update_ai_training_consent(
    p_user_id INTEGER,
    p_consent BOOLEAN
) RETURNS VOID AS $$
BEGIN
    UPDATE users
    SET ai_training_consent = p_consent
    WHERE id = p_user_id;
END;
$$ LANGUAGE plpgsql;

CREATE FUNCTION get_challenge_template_id_from_running_challenge(p_user_id BIGINT)
RETURNS BIGINT
LANGUAGE plpgsql
AS $$
DECLARE
    v_challenge_template_id BIGINT;
BEGIN
    SELECT c.challenge_template_id
    INTO v_challenge_template_id
    FROM users u
    JOIN challenges c ON u.running_challenge = c.id
    WHERE u.id = p_user_id;

    RETURN v_challenge_template_id;
END;
$$;