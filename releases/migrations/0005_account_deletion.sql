-- Keep announcements when their author is deleted; follow a username change.
ALTER TABLE public.announcements ALTER COLUMN author DROP NOT NULL;
ALTER TABLE public.announcements DROP CONSTRAINT announcements_author_fkey;
ALTER TABLE public.announcements ADD CONSTRAINT announcements_author_fkey
    FOREIGN KEY (author) REFERENCES public.users(username) ON UPDATE CASCADE ON DELETE SET NULL;

CREATE FUNCTION api.web_account_deletion_check(p_user_id BIGINT, p_password_hash TEXT)
RETURNS VOID LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
BEGIN
    IF NOT EXISTS(SELECT 1 FROM public.users WHERE id = p_user_id AND password_hash = p_password_hash) THEN
        RAISE EXCEPTION 'Authentication changed; sign in again' USING ERRCODE = '28000';
    END IF;
    IF EXISTS(SELECT 1 FROM public.challenge_templates WHERE creator_id = p_user_id)
       OR EXISTS(SELECT 1 FROM public.disk_files WHERE user_id = p_user_id) THEN
        RAISE EXCEPTION 'Transfer or delete your exercises and VM images before deleting your account' USING ERRCODE = '55000';
    END IF;
    IF EXISTS(SELECT 1 FROM public.users WHERE id = p_user_id AND is_admin)
       AND (SELECT COUNT(*) FROM public.users WHERE is_admin) <= 1 THEN
        RAISE EXCEPTION 'Create another administrator before deleting your account' USING ERRCODE = '55000';
    END IF;
END;
$$;

CREATE FUNCTION api.web_account_remove(p_user_id BIGINT, p_password_hash TEXT, p_ip INET)
RETURNS VOID LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, api, public AS $$
BEGIN
    -- Serialize the last-admin decision and prevent issuing a new session for a
    -- user whose account is being removed. The preflight is repeated atomically.
    PERFORM pg_advisory_xact_lock(hashtextextended('heist-web-admin-accounts', 0));
    PERFORM pg_advisory_xact_lock(hashtextextended('heist-web-auth:' || p_user_id::text, 0));
    PERFORM api.web_account_deletion_check(p_user_id, p_password_hash);
    IF EXISTS(SELECT 1 FROM public.users WHERE id = p_user_id AND running_challenge IS NOT NULL) THEN
        RAISE EXCEPTION 'Stop your running exercise before deleting your account' USING ERRCODE = '55000';
    END IF;
    PERFORM api.delete_user_data(p_user_id, p_password_hash, p_ip);
END;
$$;
REVOKE ALL ON FUNCTION api.web_account_deletion_check(BIGINT,TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION api.web_account_remove(BIGINT,TEXT,INET) FROM PUBLIC;
DO $$
DECLARE v_role TEXT := current_setting('heist.web_api_role', TRUE);
BEGIN
    IF v_role IS NULL OR v_role = '' THEN
        RAISE EXCEPTION 'Declare the restricted web API role before this migration';
    END IF;
    EXECUTE format('GRANT EXECUTE ON FUNCTION api.web_account_deletion_check(BIGINT,TEXT) TO %I', v_role);
    EXECUTE format('GRANT EXECUTE ON FUNCTION api.web_account_remove(BIGINT,TEXT,INET) TO %I', v_role);
END;
$$;
