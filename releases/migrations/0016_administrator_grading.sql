CREATE TABLE public.administrator_flag_submissions (
 id BIGSERIAL PRIMARY KEY, actor_id BIGINT REFERENCES public.users(id) ON DELETE SET NULL,
 user_id BIGINT REFERENCES public.users(id) ON DELETE SET NULL,
 challenge_template_id BIGINT NOT NULL, flag_id BIGINT NOT NULL,
 reason TEXT NOT NULL CHECK(length(reason) BETWEEN 10 AND 500),
 recorded_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
REVOKE ALL ON public.administrator_flag_submissions FROM PUBLIC;

CREATE FUNCTION api.web_admin_grading_user(p_actor BIGINT,p_user BIGINT)
RETURNS TABLE(id BIGINT,username TEXT) LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM public.users WHERE users.id=p_actor AND is_admin) THEN RAISE EXCEPTION 'Administrator required' USING ERRCODE='42501'; END IF;
 RETURN QUERY SELECT u.id,u.username::text FROM public.users u WHERE u.id=p_user;
END $$;

CREATE FUNCTION api.web_admin_record_submission(p_actor BIGINT,p_user BIGINT,p_template BIGINT,p_flag BIGINT,p_reason TEXT)
RETURNS VOID LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
BEGIN
 PERFORM 1 FROM public.users WHERE id=p_actor AND is_admin FOR SHARE;
 IF NOT FOUND THEN RAISE EXCEPTION 'Administrator required' USING ERRCODE='42501'; END IF;
 IF NOT EXISTS(SELECT 1 FROM public.completed_challenges WHERE user_id=p_user AND challenge_template_id=p_template AND flag_id=p_flag AND completed_at IS NOT NULL) THEN RAISE EXCEPTION 'Accepted submission required'; END IF;
 INSERT INTO public.administrator_flag_submissions(actor_id,user_id,challenge_template_id,flag_id,reason) VALUES(p_actor,p_user,p_template,p_flag,p_reason);
END $$;

CREATE FUNCTION api.web_admin_submission_export(p_actor BIGINT,p_template BIGINT,p_after BIGINT)
RETURNS TABLE(submission_id BIGINT,user_id BIGINT,username TEXT,email TEXT,challenge_id BIGINT,challenge TEXT,flag_id BIGINT,points BIGINT,completed_at TIMESTAMP,administrator TEXT,reason TEXT)
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM public.users WHERE id=p_actor AND is_admin) THEN RAISE EXCEPTION 'Administrator required' USING ERRCODE='42501'; END IF;
 RETURN QUERY SELECT c.id,u.id,u.username::text,u.email::text,t.id,t.name::text,f.id,f.points::bigint,c.completed_at,a.username::text,s.reason
 FROM public.completed_challenges c JOIN public.users u ON u.id=c.user_id JOIN public.challenge_templates t ON t.id=c.challenge_template_id
 JOIN public.challenge_flags f ON f.id=c.flag_id
 LEFT JOIN LATERAL (SELECT s0.actor_id,s0.reason FROM public.administrator_flag_submissions s0 WHERE s0.user_id=u.id AND s0.challenge_template_id=t.id AND s0.flag_id=f.id ORDER BY s0.id DESC LIMIT 1) s ON TRUE
 LEFT JOIN public.users a ON a.id=s.actor_id
 WHERE c.completed_at IS NOT NULL AND c.id>p_after AND (p_template=0 OR t.id=p_template) ORDER BY c.id LIMIT 1000;
END $$;
REVOKE ALL ON FUNCTION api.web_admin_grading_user(BIGINT,BIGINT),api.web_admin_record_submission(BIGINT,BIGINT,BIGINT,BIGINT,TEXT),api.web_admin_submission_export(BIGINT,BIGINT,BIGINT) FROM PUBLIC;
DO $$ DECLARE role_name TEXT:=current_setting('heist.web_api_role',TRUE);
BEGIN
 IF role_name IS NULL OR role_name='' THEN RAISE EXCEPTION 'Declare restricted web API role'; END IF;
 EXECUTE format('REVOKE ALL ON public.administrator_flag_submissions FROM %I',role_name);
 EXECUTE format('GRANT EXECUTE ON FUNCTION api.web_admin_grading_user(BIGINT,BIGINT),api.web_admin_record_submission(BIGINT,BIGINT,BIGINT,BIGINT,TEXT),api.web_admin_submission_export(BIGINT,BIGINT,BIGINT) TO %I',role_name);
END $$;
