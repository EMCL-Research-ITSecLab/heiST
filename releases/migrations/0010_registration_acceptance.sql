CREATE TABLE public.registration_acceptances (
    user_id BIGINT NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    policy_version TEXT NOT NULL CHECK (policy_version ~ '^[a-f0-9]{64}$'),
    imprint_url TEXT NOT NULL CHECK (length(imprint_url) BETWEEN 1 AND 1024),
    privacy_url TEXT NOT NULL CHECK (length(privacy_url) BETWEEN 1 AND 1024),
    accepted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY(user_id,policy_version)
);
REVOKE ALL ON public.registration_acceptances FROM PUBLIC;
CREATE FUNCTION api.web_record_registration(p_user_id BIGINT,p_version TEXT,p_imprint TEXT,p_privacy TEXT)
RETURNS VOID LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
    INSERT INTO public.registration_acceptances(user_id,policy_version,imprint_url,privacy_url)
    VALUES(p_user_id,p_version,p_imprint,p_privacy) ON CONFLICT DO NOTHING;
$$;
REVOKE ALL ON FUNCTION api.web_record_registration(BIGINT,TEXT,TEXT,TEXT) FROM PUBLIC;
DO $$
DECLARE role_name TEXT := current_setting('heist.web_api_role',TRUE);
BEGIN
    IF role_name IS NULL OR role_name='' THEN RAISE EXCEPTION 'Declare restricted web API role'; END IF;
    EXECUTE format('GRANT EXECUTE ON FUNCTION api.web_record_registration(BIGINT,TEXT,TEXT,TEXT) TO %I',role_name);
END;
$$;
