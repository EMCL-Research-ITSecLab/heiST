CREATE TABLE public.pool_overrides (
    challenge_template_id BIGINT PRIMARY KEY REFERENCES public.challenge_templates(id) ON DELETE CASCADE,
    enabled BOOLEAN NOT NULL,
    size INTEGER NOT NULL CHECK(size BETWEEN 0 AND 10),
    revision BIGINT NOT NULL DEFAULT 1,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    updated_by BIGINT REFERENCES public.users(id) ON DELETE SET NULL
);
REVOKE ALL ON public.pool_overrides FROM PUBLIC;
DO $$ DECLARE role_name TEXT:=current_setting('heist.web_api_role',TRUE);
BEGIN
    IF role_name IS NULL OR role_name='' THEN RAISE EXCEPTION 'Declare restricted web API role'; END IF;
    EXECUTE format('REVOKE ALL ON public.pool_overrides FROM %I',role_name);
END $$;
