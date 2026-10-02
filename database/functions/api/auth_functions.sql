CREATE FUNCTION is_username_taken(p_username TEXT)
RETURNS BOOLEAN
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    RETURN EXISTS (SELECT 1 FROM users WHERE users.username = p_username);
END;
$$;


CREATE FUNCTION is_email_taken(p_email TEXT)
RETURNS BOOLEAN
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    RETURN EXISTS(SELECT 1 FROM users WHERE users.email = p_email);
END;
$$;


CREATE FUNCTION create_user(
    p_username TEXT,
    p_email TEXT,
    p_password_hash TEXT,
    p_password_salt TEXT,
    p_ip_addr INET
)
RETURNS TABLE (
    id BIGINT,
    vpn_static_ip INET
)
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
DECLARE
    v_user_id BIGINT;
    v_vpn_ip INET;
BEGIN
    v_user_id := allocate_user_id();

    INSERT INTO users (id, username, email, password_hash, password_salt)
    VALUES (v_user_id, p_username, p_email, p_password_hash, p_password_salt);

    v_vpn_ip := assign_lowest_vpn_ip(v_user_id);

    UPDATE users u
    SET vpn_static_ip = v_vpn_ip
    WHERE u.id = v_user_id;

    INSERT INTO user_identification_history (
        username_old,
        username_new,
        email_old,
        email_new,
        ip_addr,
        created,
        changed_at
    )
    VALUES (
        NULL,
        p_username,
        NULL,
        p_email,
        p_ip_addr,
        TRUE,
        CURRENT_TIMESTAMP
    );

    RETURN QUERY
    SELECT
        v_user_id::BIGINT AS id,
        v_vpn_ip::INET AS vpn_static_ip;
END;
$$;



CREATE FUNCTION update_last_login(p_user_id BIGINT)
RETURNS VOID
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    UPDATE users
    SET last_login = CURRENT_TIMESTAMP
    WHERE id = p_user_id;
END;
$$;


CREATE FUNCTION get_user_password_salt(p_username TEXT)
RETURNS TEXT
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    RETURN (SELECT password_salt FROM users WHERE username = p_username)::TEXT;
END;
$$;


CREATE FUNCTION authenticate_user(
    p_username TEXT,
    p_password_hash TEXT
)
RETURNS BIGINT
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
DECLARE
    v_user_id BIGINT;
BEGIN
    SELECT id::BIGINT INTO v_user_id
    FROM users
    WHERE username = p_username AND password_hash = p_password_hash;
    RETURN v_user_id;
END;
$$;


CREATE FUNCTION change_user_password(
    p_user_id BIGINT,
    p_old_password_hash TEXT,
    p_new_password_hash TEXT,
    p_new_password_salt TEXT
)
RETURNS VOID
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    UPDATE users
    SET password_hash = p_new_password_hash,
        password_salt = p_new_password_salt,
        password_reset = False,
        password_reset_timestamp = NULL
    WHERE id = p_user_id AND password_hash = p_old_password_hash;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Old password does not match';
    END IF;
END;
$$;


CREATE FUNCTION is_user_admin(p_user_id BIGINT)
RETURNS BOOLEAN
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    RETURN ( SELECT is_admin FROM users WHERE id = p_user_id );
END;
$$;

CREATE FUNCTION check_password_change(p_user_id BIGINT)
    RETURNS BOOLEAN
    LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
RETURN COALESCE(
        (SELECT password_reset FROM users WHERE id = p_user_id),
        FALSE
       );
END;
$$;

CREATE FUNCTION get_password_reset_valid(p_user_id BIGINT)
    RETURNS BOOLEAN
    LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
DECLARE
v_reset_timestamp TIMESTAMP;
BEGIN
SELECT password_reset_timestamp INTO v_reset_timestamp
FROM users
WHERE id = p_user_id;

IF v_reset_timestamp IS NULL THEN
        RETURN FALSE;
END IF;

RETURN (CURRENT_TIMESTAMP - v_reset_timestamp) <= INTERVAL '5 days';
END;
$$;
