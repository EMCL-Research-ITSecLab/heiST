-- A training-use preference, not a record of consent or a legal basis.
CREATE TABLE public.training_preferences (
    user_id BIGINT PRIMARY KEY REFERENCES public.users(id) ON DELETE CASCADE,
    opted_out BOOLEAN NOT NULL DEFAULT FALSE,
    revision BIGINT NOT NULL DEFAULT 1 CHECK (revision > 0),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE public.training_preference_history (
    user_id BIGINT NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    revision BIGINT NOT NULL,
    opted_out BOOLEAN NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (user_id,revision)
);
REVOKE ALL ON public.training_preferences,public.training_preference_history FROM PUBLIC;

CREATE FUNCTION public.initialize_training_preference() RETURNS TRIGGER
LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
BEGIN
    INSERT INTO public.training_preferences(user_id) VALUES(NEW.id);
    RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION public.initialize_training_preference() FROM PUBLIC;
CREATE TRIGGER initialize_training_preference AFTER INSERT ON public.users
FOR EACH ROW EXECUTE FUNCTION public.initialize_training_preference();
INSERT INTO public.training_preferences(user_id) SELECT id FROM public.users;

CREATE FUNCTION api.web_training_preference(p_user_id BIGINT)
RETURNS TABLE(opted_out BOOLEAN,revision BIGINT,updated_at TIMESTAMPTZ)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public AS $$
    SELECT p.opted_out,p.revision,p.updated_at FROM public.training_preferences p WHERE p.user_id=p_user_id;
$$;
CREATE FUNCTION api.web_set_training_preference(p_user_id BIGINT,p_opted_out BOOLEAN)
RETURNS TABLE(opted_out BOOLEAN,revision BIGINT,updated_at TIMESTAMPTZ)
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
BEGIN
    IF p_opted_out IS NULL THEN RAISE EXCEPTION 'Choose a training preference'; END IF;
    PERFORM 1 FROM public.training_preferences p WHERE p.user_id=p_user_id FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'Account preference unavailable'; END IF;
    UPDATE public.training_preferences p SET opted_out=p_opted_out,
        revision=p.revision+1,updated_at=clock_timestamp()
        WHERE p.user_id=p_user_id AND p.opted_out IS DISTINCT FROM p_opted_out;
    IF FOUND THEN
        INSERT INTO public.training_preference_history(user_id,revision,opted_out,recorded_at)
        SELECT p.user_id,p.revision,p.opted_out,p.updated_at FROM public.training_preferences p WHERE p.user_id=p_user_id;
    END IF;
    RETURN QUERY SELECT * FROM api.web_training_preference(p_user_id);
END;
$$;
REVOKE ALL ON FUNCTION api.web_training_preference(BIGINT),api.web_set_training_preference(BIGINT,BOOLEAN) FROM PUBLIC;
DO $$
DECLARE role_name TEXT := current_setting('heist.web_api_role',TRUE);
BEGIN
    IF role_name IS NULL OR role_name='' THEN RAISE EXCEPTION 'Declare restricted web API role'; END IF;
    EXECUTE format('REVOKE ALL ON public.training_preferences,public.training_preference_history FROM %I',role_name);
    EXECUTE format('GRANT EXECUTE ON FUNCTION api.web_training_preference(BIGINT),api.web_set_training_preference(BIGINT,BOOLEAN) TO %I',role_name);
END;
$$;
