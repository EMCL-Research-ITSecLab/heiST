ALTER TABLE public.disk_files ADD COLUMN is_available BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE public.disk_files ADD CONSTRAINT disk_files_unique_storage_name UNIQUE(proxmox_filename);

CREATE FUNCTION api.web_disk_files(p_user_id BIGINT)
RETURNS TABLE(id BIGINT, display_name TEXT, upload_date TIMESTAMP, guest_os public.guest_os, is_available BOOLEAN)
LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
    SELECT d.id,d.display_name,d.upload_date,d.guest_os,d.is_available
    FROM public.disk_files d WHERE d.user_id=p_user_id ORDER BY d.upload_date DESC,d.id;
$$;
REVOKE ALL ON FUNCTION api.web_disk_files(BIGINT) FROM PUBLIC;

CREATE OR REPLACE FUNCTION api.get_user_available_disk_files(p_user_id BIGINT)
RETURNS TABLE(id BIGINT, display_name TEXT, upload_date TIMESTAMP, guest_os public.guest_os)
LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
    SELECT d.id,d.display_name,d.upload_date,d.guest_os
    FROM public.disk_files d WHERE d.user_id=p_user_id AND d.is_available
    ORDER BY d.upload_date DESC,d.id;
$$;

CREATE OR REPLACE FUNCTION api.create_machine_template(
    p_challenge_template_id BIGINT,p_name TEXT,p_disk_file_id BIGINT,
    p_cores BIGINT,p_ram_gb BIGINT,p_ad_role public.machine_ad_role
) RETURNS BIGINT LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE new_id BIGINT;
BEGIN
    -- Hold the artifact until this authoring transaction finishes. Retirement
    -- locks the same row before checking references and disabling availability.
    PERFORM 1 FROM public.disk_files WHERE id=p_disk_file_id AND is_available FOR SHARE;
    IF NOT FOUND THEN RAISE EXCEPTION 'Image is unavailable' USING ERRCODE='23514'; END IF;
    INSERT INTO public.machine_templates(challenge_template_id,name,disk_file_id,cores,ram_gb,ad_role)
    VALUES(p_challenge_template_id,p_name,p_disk_file_id,p_cores,p_ram_gb,p_ad_role) RETURNING id INTO new_id;
    RETURN new_id;
END;
$$;
DO $$
DECLARE role_name TEXT := current_setting('heist.web_api_role',TRUE);
BEGIN
    IF role_name IS NULL OR role_name='' THEN RAISE EXCEPTION 'Declare restricted web API role'; END IF;
    EXECUTE format('GRANT EXECUTE ON FUNCTION api.web_disk_files(BIGINT) TO %I',role_name);
    -- Browser services cannot register/delete arbitrary host image names. Only
    -- verified privileged intake/retirement owns these metadata mutations.
    EXECUTE format('REVOKE ALL ON FUNCTION api.add_user_disk_file(BIGINT,TEXT,TEXT,public.guest_os) FROM %I',role_name);
    EXECUTE format('REVOKE ALL ON FUNCTION api.delete_user_disk_file(BIGINT,BIGINT) FROM %I',role_name);
END;
$$;
