"""Owner-scoped configuration changes with stable grading and machine identities."""
import hashlib
import json

from psycopg2.extras import RealDictCursor

from .definition import DefinitionError, definition, records
from ..images.locking import template_guard


def snapshot(cursor, actor, identifier, *, lock=False):
    from ..administration import AdminError
    cursor.execute('SELECT id,name,description,category,difficulty,hint,solution,is_active,ready_to_launch,marked_for_deletion '
                   'FROM public.challenge_templates WHERE id=%s AND creator_id=%s' + (' FOR UPDATE' if lock else ''), (identifier, actor))
    source = cursor.fetchone()
    if not source:
        raise AdminError('Exercise not found', 404)
    value = {key: source[key] for key in ('name','description','category','difficulty','hint','solution')}
    value['isActive'] = source['is_active']
    cursor.execute('''SELECT m.id,m.name,m.cores,m.ram_gb,m.ad_role::text,d.display_name AS ova_name,d.id AS artifact_id,
        ARRAY(SELECT domain_name FROM public.domain_templates WHERE machine_template_id=m.id ORDER BY domain_name) AS domain_names
        FROM public.machine_templates m JOIN public.disk_files d ON d.id=m.disk_file_id WHERE m.challenge_template_id=%s ORDER BY m.id''', (identifier,))
    value['vms'] = [dict(row) for row in cursor.fetchall()]
    names = {row['id']:row['name'] for row in value['vms']}
    for item in value['vms']:
        item['domain_name'] = item['domain_names'][0] if len(item['domain_names']) == 1 else ''
    cursor.execute('''SELECT n.id,n.name,n.accessible,n.is_dmz AS dmz,
        ARRAY(SELECT m.name FROM public.network_connection_templates c JOIN public.machine_templates m ON m.id=c.machine_template_id
          WHERE c.network_template_id=n.id ORDER BY m.name) AS attached_vms
        FROM public.network_templates n WHERE n.challenge_template_id=%s ORDER BY n.id''', (identifier,))
    value['subnets'] = [dict(row) for row in cursor.fetchall()]
    cursor.execute('SELECT id,flag,description,points,order_index,user_specific,machine_template_id FROM public.challenge_flags WHERE challenge_template_id=%s ORDER BY order_index,id', (identifier,))
    value['flags'] = [{**dict(row), 'vm_name':names.get(row['machine_template_id'])} for row in cursor.fetchall()]
    cursor.execute('SELECT id,hint_text,unlock_points,order_index FROM public.challenge_hints WHERE challenge_template_id=%s ORDER BY order_index,id', (identifier,))
    value['hints'] = [dict(row) for row in cursor.fetchall()]
    cursor.execute('SELECT count(*) AS count FROM public.challenges WHERE challenge_template_id=%s', (identifier,))
    instances = cursor.fetchone()['count']
    fingerprint = hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
    return {'definition':value, 'fingerprint':fingerprint, 'instances':instances,
            'retired':source['marked_for_deletion'], 'ready':source['ready_to_launch']}


def load(service, actor, identifier):
    with service.database(actor) as db, db.cursor(cursor_factory=RealDictCursor) as cursor:
        return snapshot(cursor, actor, identifier)


def update(service, actor, identifier, value, expected, *, request_id=None):
    from ..administration import AdminError
    if not isinstance(value, dict) or not isinstance(expected, str) or len(expected) != 64:
        raise AdminError('Refresh the configuration before saving', 400)

    def change():
        # Launch, warmup, import and teardown share this cross-process lease.
        with template_guard(identifier), service.database(actor) as db, db.cursor(cursor_factory=RealDictCursor) as cursor:
            current = snapshot(cursor, actor, identifier, lock=True)
            old = current['definition']
            if expected != current['fingerprint']:
                raise AdminError('Configuration changed; reload before saving')
            if current['retired'] or old['isActive'] or current['instances']:
                raise AdminError('Set the pool to zero, wait for instances to finish, and pause the exercise before changing its configuration')
            cursor.execute('SELECT * FROM api.get_user_available_disk_files(%s)', (actor,))
            try:
                parsed = definition(value, [dict(row) for row in cursor.fetchall()])
                machines = records(value.get('vms'), 'Machines', 1, 20)
                flags = records(value.get('flags'), 'Flags', 1, 20)
            except DefinitionError as error:
                raise AdminError(str(error), 400) from None
            if parsed['is_active']:
                raise AdminError('Save the configuration paused, then publish it separately', 400)
            old_machines = {row['id']:row for row in old['vms']}
            machine_ids = [row.get('id') for row in machines]
            if any(type(item) is not int for item in machine_ids) or len(set(machine_ids)) != len(machine_ids) or set(machine_ids) != set(old_machines):
                raise AdminError('Keep the existing machines; use a draft clone to add, remove or replace source images', 400)
            for raw, machine in zip(machines, parsed['machines']):
                previous = old_machines[raw['id']]
                if machine['disk_file_id'] != previous['artifact_id']:
                    raise AdminError('Use a draft clone to replace a source image', 400)
                if len(previous['domain_names']) > 1:
                    raise AdminError('This legacy machine has multiple domain names; clone it as a draft for manual authoring')
            old_flags = {row['id']:row for row in old['flags']}
            flag_ids = [row.get('id') for row in flags if row.get('id') is not None]
            if any(type(item) is not int or item not in old_flags for item in flag_ids) or len(set(flag_ids)) != len(flag_ids):
                raise AdminError('Flag identities do not belong to this exercise', 400)
            names = {machine['name']:raw['id'] for raw,machine in zip(machines,parsed['machines'])}
            cursor.execute('SELECT DISTINCT flag_id FROM public.completed_challenges WHERE challenge_template_id=%s AND flag_id IS NOT NULL', (identifier,))
            earned = {row['flag_id'] for row in cursor.fetchall()}
            if earned - set(flag_ids):
                raise AdminError('Flags already earned by students cannot be removed')
            for raw,flag in zip(flags,parsed['flags']):
                flag_id = raw.get('id')
                if flag_id in earned:
                    previous = old_flags[flag_id]
                    target = names.get(flag['vm_name'])
                    if any(previous[key] != flag[key] for key in ('flag','points','user_specific')) or previous['machine_template_id'] != target:
                        raise AdminError('Earned flags must keep their verifier, points and machine assignment')
            cursor.execute('SELECT count(*) AS count FROM public.challenge_templates WHERE creator_id=%s AND id<>%s AND lower(name)=lower(%s)', (actor,identifier,parsed['name']))
            if cursor.fetchone()['count']:
                raise AdminError('You already have an exercise with this name')
            cursor.execute("SELECT api.web_record_exercise_revision(%s,%s,'revision_saved')", (actor, identifier))
            # Rename in two passes to permit swapping names under unique constraints.
            reserved = {row['name'] for row in old['vms']} | {machine['name'] for machine in parsed['machines']}
            for raw in machines:
                candidate = '__heist_edit_'+str(raw['id'])
                while candidate in reserved:
                    candidate += '_'
                reserved.add(candidate)
                cursor.execute('UPDATE public.machine_templates SET name=%s WHERE id=%s', (candidate,raw['id']))
            for raw,machine in zip(machines,parsed['machines']):
                cursor.execute('UPDATE public.machine_templates SET name=%s,cores=%s,ram_gb=%s,ad_role=%s WHERE id=%s',
                               (machine['name'],machine['cores'],machine['ram_gb'],machine['ad_role'],raw['id']))
                cursor.execute('DELETE FROM public.domain_templates WHERE machine_template_id=%s', (raw['id'],))
                cursor.execute('INSERT INTO public.domain_templates(machine_template_id,domain_name) VALUES(%s,%s)', (raw['id'],machine['domain_name']))
            cursor.execute('DELETE FROM public.network_templates WHERE challenge_template_id=%s', (identifier,))
            for network in parsed['networks']:
                cursor.execute('INSERT INTO public.network_templates(challenge_template_id,name,accessible,is_dmz) VALUES(%s,%s,%s,%s) RETURNING id',
                               (identifier,network['name'],network['accessible'],network['dmz']))
                network_id = cursor.fetchone()['id']
                for name in network['attached_vms']:
                    cursor.execute('INSERT INTO public.network_connection_templates(machine_template_id,network_template_id) VALUES(%s,%s)', (names[name],network_id))
            for flag_id in set(old_flags)-set(flag_ids):
                cursor.execute('DELETE FROM public.challenge_flags WHERE id=%s', (flag_id,))
            for raw,flag in zip(flags,parsed['flags']):
                arguments = (flag['flag'],flag['description'],flag['points'],flag['order_index'],flag['user_specific'],names.get(flag['vm_name']))
                if raw.get('id') is None:
                    cursor.execute('INSERT INTO public.challenge_flags(flag,description,points,order_index,user_specific,machine_template_id,challenge_template_id) VALUES(%s,%s,%s,%s,%s,%s,%s)', (*arguments,identifier))
                else:
                    cursor.execute('UPDATE public.challenge_flags SET flag=%s,description=%s,points=%s,order_index=%s,user_specific=%s,machine_template_id=%s WHERE id=%s', (*arguments,raw['id']))
            cursor.execute('DELETE FROM public.challenge_hints WHERE challenge_template_id=%s', (identifier,))
            for hint in parsed['hints']:
                cursor.execute('INSERT INTO public.challenge_hints(challenge_template_id,hint_text,unlock_points,order_index) VALUES(%s,%s,%s,%s)',
                               (identifier,hint['hint_text'],hint['unlock_points'],hint['order_index']))
            cursor.execute('UPDATE public.challenge_templates SET name=%s,description=%s,category=%s,difficulty=%s,hint=%s,solution=%s WHERE id=%s',
                           (*(parsed[key] for key in ('name','description','category','difficulty','hint','solution')),identifier))
            cursor.execute("SELECT api.web_record_exercise_revision(%s,%s,'updated')", (actor,identifier))
            return {'template_id':identifier, 'availability':'paused', 'grades_preserved':True}
    # Cached successful requests must still enforce current role and ownership.
    load(service, actor, identifier)
    return service.journal.execute('template',identifier,'update_configuration',{'actor':actor,'expected':expected,'definition':value},change,request_id=request_id)
