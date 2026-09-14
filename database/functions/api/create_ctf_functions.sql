CREATE FUNCTION count_user_challenges_with_same_name(
    p_name TEXT,
    p_user_id BIGINT
) RETURNS BIGINT
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    RETURN (
        SELECT COUNT(*) FROM challenge_templates
        WHERE LOWER(name) = LOWER(p_name) AND creator_id = p_user_id
    )::BIGINT;
END;
$$;


CREATE FUNCTION create_challenge_template(
    p_name TEXT,
    p_description TEXT,
    p_category challenge_category,
    p_difficulty challenge_difficulty,
    p_image_path TEXT,
    p_is_active BOOLEAN,
    p_creator_id BIGINT,
    p_hint TEXT,
    p_solution TEXT
) RETURNS BIGINT
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
DECLARE
    new_challenge_id BIGINT;
BEGIN
    INSERT INTO challenge_templates (
        name,
        description,
        category,
        difficulty,
        image_path,
        is_active,
        creator_id,
        hint,
        solution
    ) VALUES (
        p_name,
        p_description,
        p_category,
        p_difficulty,
        p_image_path,
        p_is_active,
        p_creator_id,
        p_hint,
        p_solution
     ) RETURNING id INTO new_challenge_id;
    RETURN new_challenge_id::BIGINT;
END;
$$;


CREATE FUNCTION create_machine_template(
    p_challenge_template_id BIGINT,
    p_name TEXT,
    p_disk_file_id BIGINT,
    p_cores BIGINT,
    p_ram_gb BIGINT
) RETURNS BIGINT
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
DECLARE
    new_machine_id BIGINT;
BEGIN
    INSERT INTO machine_templates (
        challenge_template_id,
        name,
        disk_file_id,
        cores,
        ram_gb
    ) VALUES (
        p_challenge_template_id,
        p_name,
        p_disk_file_id,
        p_cores,
        p_ram_gb
    ) RETURNING id INTO new_machine_id;
    RETURN new_machine_id::BIGINT;
END;
$$;


CREATE FUNCTION create_domain_template(
    p_machine_template_id BIGINT,
    p_domain_name TEXT
) RETURNS VOID
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    INSERT INTO domain_templates (
        machine_template_id,
        domain_name
    ) VALUES (
        p_machine_template_id,
        p_domain_name
    );
END;
$$;


CREATE FUNCTION create_network_template(
    p_name TEXT,
    p_accessible BOOLEAN,
    p_is_dmz BOOLEAN,
    p_challenge_template_id BIGINT
) RETURNS BIGINT
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
DECLARE
    new_network_id BIGINT;
BEGIN
    INSERT INTO network_templates (
        name,
        accessible,
        is_dmz,
        challenge_template_id
    ) VALUES (
        p_name,
        p_accessible,
        p_is_dmz,
        p_challenge_template_id
    ) RETURNING id INTO new_network_id;
    RETURN new_network_id::BIGINT;
END;
$$;


CREATE FUNCTION get_machine_template_id_by_name_and_challenge_id(
    p_name TEXT,
    p_challenge_template_id BIGINT
) RETURNS BIGINT
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    RETURN (
        SELECT id FROM machine_templates
        WHERE name = p_name AND challenge_template_id = p_challenge_template_id
        LIMIT 1
    )::BIGINT;
END;
$$;


CREATE FUNCTION create_network_connection_template(
    p_machine_template_id BIGINT,
    p_network_template_id BIGINT
) RETURNS VOID
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    INSERT INTO network_connection_templates (
        machine_template_id,
        network_template_id
    ) VALUES (
        p_machine_template_id,
        p_network_template_id
    );
END;
$$;


CREATE FUNCTION create_challenge_flag(
    p_challenge_template_id BIGINT,
    p_flag TEXT,
    p_description TEXT,
    p_points BIGINT,
    p_order_index BIGINT,
    p_user_specific BOOLEAN,
    p_machine_template_id BIGINT
) RETURNS BIGINT
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
DECLARE
    new_flag_id BIGINT;
BEGIN
    INSERT INTO challenge_flags (
        challenge_template_id,
        flag,
        description,
        points,
        order_index,
        user_specific,
        machine_template_id
    ) VALUES (
        p_challenge_template_id,
        p_flag,
        p_description,
        p_points,
        p_order_index,
        p_user_specific,
        p_machine_template_id
    ) RETURNING id INTO new_flag_id;
    RETURN new_flag_id::BIGINT;
END;
$$;


CREATE FUNCTION create_challenge_hint(
    p_challenge_template_id BIGINT,
    p_hint_text TEXT,
    p_unlock_points BIGINT,
    p_order_index BIGINT
) RETURNS BIGINT
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
DECLARE
    new_hint_id BIGINT;
BEGIN
    INSERT INTO challenge_hints (
        challenge_template_id,
        hint_text,
        unlock_points,
        order_index
    ) VALUES (
        p_challenge_template_id,
        p_hint_text,
        p_unlock_points,
        p_order_index
    ) RETURNING id INTO new_hint_id;
    RETURN new_hint_id::BIGINT;
END;
$$;


CREATE FUNCTION get_user_available_disk_files(
    p_user_id BIGINT
) RETURNS TABLE (
    id BIGINT,
    display_name TEXT,
    upload_date TIMESTAMP
)
LANGUAGE plpgsql
SET plpgsql.variable_conflict = 'use_column'
AS $$
BEGIN
    RETURN QUERY
    SELECT
        df.id::BIGINT,
        df.display_name::TEXT AS name,
        df.upload_date::TIMESTAMP AS date
    FROM disk_files df
    WHERE df.user_id = p_user_id
    ORDER BY df.upload_date DESC, df.id;
END;
$$;