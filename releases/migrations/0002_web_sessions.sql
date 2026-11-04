-- Public Flask sessions retain account/grade rows and existing password hashes.
CREATE SCHEMA IF NOT EXISTS api;
CREATE TABLE public.web_auth_state (
    user_id BIGINT PRIMARY KEY REFERENCES public.users(id) ON DELETE CASCADE,
    auth_version BIGINT NOT NULL DEFAULT 0 CHECK (auth_version >= 0)
);
CREATE TABLE public.web_sessions (
    token_hash TEXT PRIMARY KEY CHECK (token_hash ~ '^[a-f0-9]{64}$'),
    user_id BIGINT REFERENCES public.users(id) ON DELETE CASCADE,
    auth_version BIGINT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL,
    last_seen TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    absolute_expires_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX web_sessions_expiry ON public.web_sessions(expires_at);
CREATE INDEX web_sessions_user ON public.web_sessions(user_id);
CREATE TABLE public.web_rate_limits (
    bucket_hash TEXT PRIMARY KEY CHECK (bucket_hash ~ '^[a-f0-9]{64}$'),
    attempts BIGINT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX web_rate_limits_expiry ON public.web_rate_limits(expires_at);

CREATE FUNCTION api.web_auth_record(p_username TEXT)
RETURNS TABLE(id BIGINT, username TEXT, password_hash TEXT, password_salt TEXT,
              is_admin BOOLEAN, password_reset BOOLEAN, reset_valid BOOLEAN, auth_version BIGINT)
LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
    SELECT u.id, u.username, u.password_hash, u.password_salt, u.is_admin,
           u.password_reset, COALESCE(u.password_reset_timestamp > CURRENT_TIMESTAMP - INTERVAL '5 days', FALSE),
           COALESCE(a.auth_version, 0)
    FROM public.users u LEFT JOIN public.web_auth_state a ON a.user_id = u.id
    WHERE u.username = p_username;
$$;

CREATE FUNCTION api.web_user_identity(p_user_id BIGINT)
RETURNS TABLE(id BIGINT, username TEXT, avatar_url TEXT, is_admin BOOLEAN, password_reset BOOLEAN, auth_version BIGINT)
LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
    SELECT u.id, u.username, u.avatar_url, u.is_admin, u.password_reset, COALESCE(a.auth_version, 0)
    FROM public.users u LEFT JOIN public.web_auth_state a ON a.user_id = u.id WHERE u.id = p_user_id;
$$;

CREATE FUNCTION api.web_session_read(p_hash TEXT, p_now TIMESTAMPTZ)
RETURNS TABLE(user_id BIGINT, auth_version BIGINT, created_at TIMESTAMPTZ, expires_at TIMESTAMPTZ)
LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
    UPDATE public.web_sessions s
    SET last_seen = p_now, expires_at = LEAST(s.absolute_expires_at, p_now + INTERVAL '1 hour')
    WHERE s.token_hash = p_hash AND s.expires_at > p_now AND s.absolute_expires_at > p_now
      AND (s.user_id IS NULL OR s.auth_version = COALESCE((SELECT a.auth_version FROM public.web_auth_state a WHERE a.user_id = s.user_id), 0))
    RETURNING s.user_id, s.auth_version, s.created_at, s.expires_at;
$$;

CREATE FUNCTION api.web_session_rotate(p_old_hash TEXT, p_new_hash TEXT, p_user_id BIGINT, p_expected_version BIGINT, p_now TIMESTAMPTZ)
RETURNS VOID LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE v_version BIGINT;
BEGIN
    IF p_user_id IS NOT NULL THEN
        PERFORM pg_advisory_xact_lock(hashtextextended('heist-web-auth:' || p_user_id::text, 0));
        SELECT COALESCE(a.auth_version, 0) INTO v_version FROM public.users u
        LEFT JOIN public.web_auth_state a ON a.user_id = u.id WHERE u.id = p_user_id;
        IF NOT FOUND OR v_version <> p_expected_version THEN
            RAISE EXCEPTION 'Authentication changed; retry login' USING ERRCODE = '28000';
        END IF;
    END IF;
    DELETE FROM public.web_sessions WHERE token_hash = p_old_hash;
    INSERT INTO public.web_sessions(token_hash, user_id, auth_version, created_at, last_seen, expires_at, absolute_expires_at)
    VALUES (p_new_hash, p_user_id, p_expected_version, p_now, p_now, p_now + INTERVAL '1 hour', p_now + INTERVAL '8 hours');
END;
$$;

CREATE FUNCTION api.web_session_remove(p_hash TEXT)
RETURNS VOID LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
    DELETE FROM public.web_sessions WHERE token_hash = p_hash;
$$;

CREATE FUNCTION api.web_password_replace(p_user_id BIGINT, p_old_hash TEXT, p_new_hash TEXT, p_new_salt TEXT, p_revoke BOOLEAN)
RETURNS VOID LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
BEGIN
    PERFORM pg_advisory_xact_lock(hashtextextended('heist-web-auth:' || p_user_id::text, 0));
    UPDATE public.users SET password_hash = p_new_hash, password_salt = p_new_salt,
        password_reset = CASE WHEN p_revoke THEN FALSE ELSE password_reset END,
        password_reset_timestamp = CASE WHEN p_revoke THEN NULL ELSE password_reset_timestamp END
    WHERE id = p_user_id AND password_hash = p_old_hash;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Authentication changed; retry login' USING ERRCODE = '28000';
    END IF;
    IF p_revoke THEN
        INSERT INTO public.web_auth_state(user_id, auth_version) VALUES (p_user_id, 1)
        ON CONFLICT (user_id) DO UPDATE SET auth_version = public.web_auth_state.auth_version + 1;
        DELETE FROM public.web_sessions WHERE user_id = p_user_id;
    END IF;
END;
$$;

CREATE FUNCTION api.web_rate_limit(p_hash TEXT, p_limit BIGINT, p_window BIGINT, p_now TIMESTAMPTZ)
RETURNS BOOLEAN LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE v_attempts BIGINT;
BEGIN
    IF p_limit < 1 OR p_limit > 10000 OR p_window < 1 OR p_window > 86400 THEN
        RAISE EXCEPTION 'Invalid rate limit';
    END IF;
    INSERT INTO public.web_rate_limits(bucket_hash, attempts, expires_at)
    VALUES (p_hash, 1, p_now + make_interval(secs => p_window::double precision))
    ON CONFLICT (bucket_hash) DO UPDATE SET
        attempts = CASE WHEN public.web_rate_limits.expires_at <= p_now THEN 1 ELSE LEAST(public.web_rate_limits.attempts + 1, p_limit + 1) END,
        expires_at = CASE WHEN public.web_rate_limits.expires_at <= p_now THEN EXCLUDED.expires_at ELSE public.web_rate_limits.expires_at END
    RETURNING attempts INTO v_attempts;
    RETURN v_attempts <= p_limit;
END;
$$;

CREATE FUNCTION api.web_cleanup(p_now TIMESTAMPTZ)
RETURNS VOID LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
BEGIN
    DELETE FROM public.web_sessions WHERE expires_at <= p_now OR absolute_expires_at <= p_now;
    DELETE FROM public.web_rate_limits WHERE expires_at <= p_now;
END;
$$;

-- A request holds this session lock until its dedicated connection closes.
-- Do not hold a users row lock across a call to the privileged platform API.
CREATE FUNCTION api.web_user_mutation_lock(p_user_id BIGINT)
RETURNS BOOLEAN LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
    SELECT pg_try_advisory_lock(hashtextextended('heist-web-mutation:' || p_user_id::text, 0));
$$;

-- The release adapter declares exactly one restricted web role on this
-- connection. Schema USAGE by itself must never grant session-issuer authority.
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
DO $$
DECLARE v_function RECORD; v_role TEXT;
BEGIN
    v_role := current_setting('heist.web_api_role', TRUE);
    IF v_role IS NULL OR v_role = '' OR NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname = v_role) THEN
        RAISE EXCEPTION 'Declare the restricted web API role before this migration';
    END IF;
    IF NOT has_schema_privilege(v_role, 'api', 'USAGE') THEN
        RAISE EXCEPTION 'The declared web role has no existing API schema access';
    END IF;
    IF EXISTS(SELECT 1 FROM pg_roles r WHERE (r.rolsuper OR r.rolcreatedb OR r.rolcreaterole OR r.rolreplication) AND pg_has_role(v_role, r.oid, 'MEMBER')) THEN
        RAISE EXCEPTION 'The public web API must not use a privileged database role';
    END IF;
    EXECUTE format('REVOKE CREATE ON SCHEMA public FROM %I', v_role);
    IF has_schema_privilege(v_role, 'public', 'CREATE') OR has_schema_privilege(v_role, 'api', 'CREATE') THEN
        RAISE EXCEPTION 'The public web role must not own or create application schema objects';
    END IF;
    FOR v_function IN SELECT p.oid, p.proname, pg_get_function_identity_arguments(p.oid) AS arguments
        FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'api'
    LOOP
        EXECUTE format('REVOKE ALL ON FUNCTION api.%I(%s) FROM PUBLIC', v_function.proname, v_function.arguments);
        EXECUTE format('GRANT EXECUTE ON FUNCTION api.%I(%s) TO %I', v_function.proname, v_function.arguments, v_role);
    END LOOP;
END;
$$;
