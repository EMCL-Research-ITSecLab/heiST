CREATE TABLE public.administrator_requests (
    id TEXT PRIMARY KEY CHECK (id ~ '^[a-f0-9]{32}$'),
    actor_id BIGINT REFERENCES public.users(id) ON DELETE SET NULL,
    cancelled_by BIGINT REFERENCES public.users(id) ON DELETE SET NULL,
    resolved_by BIGINT REFERENCES public.users(id) ON DELETE SET NULL,
    resolution_reason TEXT CHECK(resolution_reason IS NULL OR length(resolution_reason) BETWEEN 10 AND 500),
    instance_id BIGINT NOT NULL,
    scope TEXT NOT NULL CHECK (scope IN ('user','instance')),
    resource BIGINT NOT NULL CHECK (resource>0),
    action TEXT NOT NULL CHECK (action IN ('release','rebuild','remove','start','shutdown','reboot')),
    machine_id BIGINT,
    expected TEXT NOT NULL CHECK (expected ~ '^[a-f0-9]{64}$'),
    state TEXT NOT NULL DEFAULT 'QUEUED' CHECK(state IN ('QUEUED','RUNNING','SUCCEEDED','REJECTED','NEEDS_REVIEW','CANCELLED','RESOLVED')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    started_at TIMESTAMPTZ,finished_at TIMESTAMPTZ,
    message TEXT
);
CREATE UNIQUE INDEX administrator_requests_one_pending ON public.administrator_requests(scope,resource)
    WHERE state IN ('QUEUED','RUNNING','NEEDS_REVIEW');
CREATE INDEX administrator_requests_history ON public.administrator_requests(scope,resource,created_at DESC);
CREATE INDEX administrator_requests_created ON public.administrator_requests(created_at DESC);
CREATE INDEX administrator_requests_ready ON public.administrator_requests(created_at,id) WHERE state='QUEUED';
REVOKE ALL ON public.administrator_requests FROM PUBLIC;
DO $$ DECLARE role_name TEXT := current_setting('heist.web_api_role',TRUE);
BEGIN
    IF role_name IS NULL OR role_name='' THEN RAISE EXCEPTION 'Declare restricted web API role'; END IF;
    EXECUTE format('REVOKE ALL ON public.administrator_requests FROM %I',role_name);
END $$;
