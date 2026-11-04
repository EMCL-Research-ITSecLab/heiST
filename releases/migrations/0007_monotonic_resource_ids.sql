-- Never let a delayed cleanup, VPN revocation or hypervisor task address a new
-- resource through a recycled identifier. Run with writers quiesced, inside the
-- release transaction. Existing resource/account IDs and row shapes are unchanged.
DO $$
DECLARE
    item RECORD;
    highest BIGINT;
    sequence_value BIGINT;
BEGIN
    FOR item IN SELECT * FROM (VALUES
        ('users', 'user', 'users_id_seq', 'user_id_reclaim'),
        ('machines', 'machine', 'machines_id_seq', 'machine_id_reclaim'),
        ('machine_templates', 'machine_template', 'machine_templates_id_seq', 'machine_template_id_reclaim'),
        ('networks', 'network', 'networks_id_seq', 'network_id_reclaim'),
        ('challenges', 'challenge', 'challenges_id_seq', 'challenge_id_reclaim')
    ) AS resources(table_name, resource_name, sequence_name, reclaim_table)
    LOOP
        EXECUTE format('LOCK TABLE public.%I IN ACCESS EXCLUSIVE MODE', item.table_name);
        EXECUTE format('SELECT GREATEST(COALESCE((SELECT MAX(id) FROM public.%I), 0), COALESCE((SELECT MAX(id) FROM public.%I), 0))',
                       item.table_name, item.reclaim_table) INTO highest;
        EXECUTE format('SELECT last_value FROM public.%I', item.sequence_name) INTO sequence_value;
        PERFORM pg_catalog.setval(('public.'||item.sequence_name)::regclass, GREATEST(highest, sequence_value), TRUE);
        EXECUTE format('CREATE OR REPLACE FUNCTION public.%I() RETURNS BIGINT LANGUAGE sql SET search_path = pg_catalog, public AS %L',
                       'allocate_'||item.resource_name||'_id', format('SELECT nextval(%L::regclass)', 'public.'||item.sequence_name));
        EXECUTE format('DROP TRIGGER IF EXISTS %I ON public.%I', 'trg_reclaim_'||item.resource_name||'_id', item.table_name);
    END LOOP;
END;
$$;
