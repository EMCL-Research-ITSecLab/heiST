-- Historical records retain their original meaning: they did not record terms.
ALTER TABLE public.registration_acceptances ADD COLUMN terms_url TEXT
    CHECK (terms_url IS NULL OR length(terms_url) BETWEEN 1 AND 1024);
DROP FUNCTION api.web_record_registration(BIGINT,TEXT,TEXT,TEXT);
CREATE FUNCTION api.web_record_registration(p_user_id BIGINT,p_version TEXT,p_imprint TEXT,p_privacy TEXT,p_terms TEXT)
RETURNS VOID LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
BEGIN
    IF p_terms IS NULL OR length(p_terms) NOT BETWEEN 1 AND 1024 THEN
        RAISE EXCEPTION 'Terms acceptance is required';
    END IF;
    INSERT INTO public.registration_acceptances(user_id,policy_version,imprint_url,privacy_url,terms_url)
    VALUES(p_user_id,p_version,p_imprint,p_privacy,p_terms) ON CONFLICT DO NOTHING;
END;
$$;
REVOKE ALL ON FUNCTION api.web_record_registration(BIGINT,TEXT,TEXT,TEXT,TEXT) FROM PUBLIC;
DO $$
DECLARE role_name TEXT := current_setting('heist.web_api_role',TRUE);
BEGIN
    IF role_name IS NULL OR role_name='' THEN RAISE EXCEPTION 'Declare restricted web API role'; END IF;
    EXECUTE format('GRANT EXECUTE ON FUNCTION api.web_record_registration(BIGINT,TEXT,TEXT,TEXT,TEXT) TO %I',role_name);
END;
$$;
