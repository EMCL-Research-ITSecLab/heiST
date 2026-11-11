CREATE TABLE public.exercise_revisions (
    id BIGSERIAL PRIMARY KEY,
    challenge_template_id BIGINT NOT NULL REFERENCES public.challenge_templates(id) ON DELETE CASCADE,
    actor_id BIGINT REFERENCES public.users(id) ON DELETE SET NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    fingerprint TEXT NOT NULL CHECK(fingerprint ~ '^[a-f0-9]{64}$'),
    definition JSONB NOT NULL,
    UNIQUE(challenge_template_id,fingerprint)
);
CREATE TABLE public.administrator_events (
    id BIGSERIAL PRIMARY KEY,
    actor_id BIGINT REFERENCES public.users(id) ON DELETE SET NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    action TEXT NOT NULL CHECK(action IN ('created','updated','retired','restored','deleted','revision_saved','cloned')),
    resource_kind TEXT NOT NULL DEFAULT 'exercise' CHECK(resource_kind='exercise'),
    resource_id BIGINT NOT NULL,
    revision_id BIGINT,
    fingerprint TEXT
);
REVOKE ALL ON public.exercise_revisions,public.administrator_events FROM PUBLIC;

CREATE FUNCTION api.web_record_exercise_revision(p_actor BIGINT,p_template BIGINT,p_action TEXT)
RETURNS BIGINT LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE payload JSONB;checksum TEXT;revision BIGINT;fresh BOOLEAN;
BEGIN
    PERFORM 1 FROM public.users WHERE id=p_actor AND is_admin;
    IF NOT FOUND THEN RAISE EXCEPTION 'Administrator required' USING ERRCODE='42501'; END IF;
    PERFORM 1 FROM public.challenge_templates WHERE id=p_template AND creator_id=p_actor FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'Exercise not found' USING ERRCODE='42501'; END IF;
    IF p_action NOT IN ('created','updated','retired','restored','deleted','revision_saved','cloned') THEN RAISE EXCEPTION 'Invalid event'; END IF;
    SELECT jsonb_build_object('schema',1,'name',c.name,'description',COALESCE(c.description,''),
      'category',c.category,'difficulty',c.difficulty,'hint',COALESCE(c.hint,''),'solution',COALESCE(c.solution,''),'isActive',c.is_active,'retired',c.marked_for_deletion,
      'vms',COALESCE((SELECT jsonb_agg(jsonb_build_object('name',m.name,'artifact_id',m.disk_file_id,'ova_name',d.display_name,
          'cores',m.cores,'ram_gb',m.ram_gb,'ad_role',m.ad_role,
          'domain_name',COALESCE((SELECT min(domain_name) FROM public.domain_templates WHERE machine_template_id=m.id),''),
          'domain_names',COALESCE((SELECT jsonb_agg(domain_name ORDER BY domain_name) FROM public.domain_templates WHERE machine_template_id=m.id),'[]'::jsonb)) ORDER BY m.id)
        FROM public.machine_templates m LEFT JOIN public.disk_files d ON d.id=m.disk_file_id WHERE m.challenge_template_id=c.id),'[]'::jsonb),
      'subnets',COALESCE((SELECT jsonb_agg(jsonb_build_object('name',n.name,'accessible',n.accessible,'dmz',n.is_dmz,
          'attached_vms',COALESCE((SELECT jsonb_agg(m.name ORDER BY m.id) FROM public.network_connection_templates nc
            JOIN public.machine_templates m ON m.id=nc.machine_template_id WHERE nc.network_template_id=n.id),'[]'::jsonb)) ORDER BY n.id)
        FROM public.network_templates n WHERE n.challenge_template_id=c.id),'[]'::jsonb),
      'flags',COALESCE((SELECT jsonb_agg(jsonb_build_object('flag',f.flag,'description',COALESCE(f.description,''),'points',f.points,
          'order_index',f.order_index,'user_specific',f.user_specific,'vm_name',m.name) ORDER BY f.order_index,f.id)
        FROM public.challenge_flags f LEFT JOIN public.machine_templates m ON m.id=f.machine_template_id WHERE f.challenge_template_id=c.id),'[]'::jsonb),
      'hints',COALESCE((SELECT jsonb_agg(jsonb_build_object('hint_text',h.hint_text,'unlock_points',h.unlock_points,'order_index',h.order_index)
        ORDER BY h.order_index,h.id) FROM public.challenge_hints h WHERE h.challenge_template_id=c.id),'[]'::jsonb)) INTO payload
      FROM public.challenge_templates c WHERE c.id=p_template;
    IF octet_length(payload::text)>1048576 THEN RAISE EXCEPTION 'Exercise revision is oversized'; END IF;
    checksum:=encode(sha256(convert_to(payload::text,'UTF8')),'hex');
    INSERT INTO public.exercise_revisions(challenge_template_id,actor_id,fingerprint,definition)
      VALUES(p_template,p_actor,checksum,payload) ON CONFLICT(challenge_template_id,fingerprint) DO NOTHING RETURNING id INTO revision;
    fresh:=revision IS NOT NULL;
    IF revision IS NULL THEN SELECT id INTO revision FROM public.exercise_revisions WHERE challenge_template_id=p_template AND fingerprint=checksum; END IF;
    IF fresh OR p_action<>'revision_saved' THEN
      INSERT INTO public.administrator_events(actor_id,action,resource_id,revision_id,fingerprint) VALUES(p_actor,p_action,p_template,revision,checksum);
    END IF;
    RETURN revision;
END $$;

CREATE FUNCTION api.web_exercise_revisions(p_actor BIGINT,p_template BIGINT)
RETURNS TABLE(id BIGINT,recorded_at TIMESTAMPTZ,actor TEXT,fingerprint TEXT,name TEXT,is_active BOOLEAN,machines INTEGER,networks INTEGER)
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
BEGIN
    IF NOT EXISTS(SELECT 1 FROM public.users a WHERE a.id=p_actor AND a.is_admin) THEN RAISE EXCEPTION 'Administrator required' USING ERRCODE='42501'; END IF;
    IF NOT EXISTS(SELECT 1 FROM public.challenge_templates c WHERE c.id=p_template AND c.creator_id=p_actor) THEN RAISE EXCEPTION 'Exercise not found' USING ERRCODE='42501'; END IF;
    RETURN QUERY SELECT r.id,r.recorded_at,u.username::text,r.fingerprint,r.definition->>'name',(r.definition->>'isActive')::boolean,
      jsonb_array_length(r.definition->'vms'),jsonb_array_length(r.definition->'subnets')
      FROM public.exercise_revisions r LEFT JOIN public.users u ON u.id=r.actor_id WHERE r.challenge_template_id=p_template
      ORDER BY r.recorded_at DESC,r.id DESC LIMIT 51;
END $$;
CREATE FUNCTION api.web_exercise_revision(p_actor BIGINT,p_template BIGINT,p_revision BIGINT)
RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
BEGIN
    IF NOT EXISTS(SELECT 1 FROM public.users WHERE id=p_actor AND is_admin) OR
      NOT EXISTS(SELECT 1 FROM public.challenge_templates WHERE id=p_template AND creator_id=p_actor) THEN
      RAISE EXCEPTION 'Exercise not found' USING ERRCODE='42501'; END IF;
    RETURN (SELECT definition FROM public.exercise_revisions WHERE id=p_revision AND challenge_template_id=p_template);
END $$;
REVOKE ALL ON FUNCTION api.web_record_exercise_revision(BIGINT,BIGINT,TEXT),api.web_exercise_revisions(BIGINT,BIGINT),
    api.web_exercise_revision(BIGINT,BIGINT,BIGINT) FROM PUBLIC;
DO $$ DECLARE role_name TEXT:=current_setting('heist.web_api_role',TRUE);
BEGIN
    IF role_name IS NULL OR role_name='' THEN RAISE EXCEPTION 'Declare restricted web API role'; END IF;
    EXECUTE format('REVOKE ALL ON public.exercise_revisions,public.administrator_events FROM %I',role_name);
    EXECUTE format('GRANT EXECUTE ON FUNCTION api.web_record_exercise_revision(BIGINT,BIGINT,TEXT),api.web_exercise_revisions(BIGINT,BIGINT),api.web_exercise_revision(BIGINT,BIGINT,BIGINT) TO %I',role_name);
END $$;
