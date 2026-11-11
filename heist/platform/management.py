"""Bounded operator read models; unknown host measurements never become zero."""
import json
import socket
import subprocess
from pathlib import Path
import re


def maintenance(settings):
    from .operations import release_status
    root = Path(settings.get('HEIST_STATE_DIRECTORY', '/var/lib/heist'))
    release = release_status(root)
    return {
        'release': release,
        'acceptance': acceptance_status(settings.get('HEIST_DEPLOYMENT_CONFIG'), release),
        'maintenance': Path(settings.get('HEIST_MAINTENANCE_FILE', '/run/heist-maintenance')).exists(),
        **transaction_history(root/'transactions'),
    }


def acceptance_status(configured, release):
    """Reuse rollout admission; never accept a second, weaker UI evidence format."""
    if not configured:
        return {'status': 'not configured'}
    try:
        from types import SimpleNamespace
        from heist.rollout.config import Deployment
        from heist.rollout.admission import read_evidence, require

        path = Path(configured)
        if not path.is_absolute() or '..' in path.parts or path.is_symlink() or path.stat().st_size > 65536:
            raise ValueError('Invalid deployment configuration')
        config = Deployment.load(path)
        if not config.acceptance_receipt:
            return {'status': 'not configured'}
        receipt = read_evidence(config.acceptance_receipt, config.acceptance_sha256)
        plan = SimpleNamespace(source=receipt['baseline_source'], target=receipt['source_commit'], rollback=False)
        verified = require(config, plan)
        return {
            'status': 'verified receipt',
            'target_commit': verified['source_commit'],
            'installed_match': verified['source_commit'] == release.get('commit'),
        }
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError):
        return {'status': 'unavailable'}


def transaction_history(directory):
    """Only bounded public metadata, even when a transaction is corrupt or removed."""
    result = {'transactions': [], 'truncated': False}
    try:
        if not directory.exists():
            return result
        if directory.is_symlink():
            raise ValueError('Transaction history must be a real directory')
        paths = []
        for count, path in enumerate(directory.iterdir()):
            if count >= 500:
                result['truncated'] = True
                break
            if not path.is_symlink() and path.is_dir() and re.fullmatch('[A-Za-z0-9_-]{1,100}', path.name):
                paths.append((path.stat().st_mtime_ns, path))
        paths.sort(key=lambda item: item[0], reverse=True)
        result['truncated'] = result['truncated'] or len(paths) > 25
        for _, path in paths[:25]:
            receipt = path/'transaction.json'
            try:
                if receipt.is_symlink() or receipt.stat().st_size > 1024**2:
                    continue
                data = json.loads(receipt.read_bytes())
                version, phase = data['plan']['version'], data['phase']
                if not isinstance(version, str) or not re.fullmatch(r'\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?', version):
                    continue
                if not isinstance(phase, str) or not re.fullmatch('[A-Z_]{1,64}', phase):
                    continue
                result['transactions'].append({
                    'id': path.name, 'version': version, 'phase': phase,
                    'checkpoint_recorded': data.get('checkpoint_ready') is True,
                    'committed': data.get('committed') is True,
                })
            except (OSError, ValueError, KeyError, TypeError):
                result['truncated'] = True
    except (OSError, ValueError):
        result['unavailable'] = True
    return result


def host_capacity(*,run=subprocess.run):
    try:
        result=run(['pvesh','get','/nodes/'+socket.gethostname()+'/status','--output-format','json'],
                   capture_output=True,text=True,timeout=3,check=True)
        if len(result.stdout)>65536:raise ValueError('Oversized capacity response')
        value=json.loads(result.stdout)
        memory=value['memory'];root=value['rootfs'];cores=value['cpuinfo']['cpus']
        numbers=[memory['total'],memory['used'],root['total'],root['used'],cores]
        if any(type(n) is not int or n<0 for n in numbers) or not memory['total'] or not root['total'] or not cores:
            raise ValueError('Invalid capacity values')
        if memory['used']>memory['total'] or root['used']>root['total']:
            raise ValueError('Capacity usage exceeds total')
        cpu=value['cpu']
        if type(cpu) not in (float,int) or not 0<=cpu<=1:raise ValueError('Invalid CPU usage')
        return {'status':'ready','memory_total_bytes':memory['total'],'memory_used_bytes':memory['used'],
                'root_total_bytes':root['total'],'root_used_bytes':root['used'],'cores':cores,'cpu_percent':round(cpu*100,1)}
    except (OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError):
        return {'status':'unavailable'}


def overview(service,actor):
    from psycopg2.extras import RealDictCursor
    with service.database(actor) as db,db.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute('''SELECT (SELECT count(*) FROM public.users) AS users,
          (SELECT count(*) FROM public.users WHERE is_admin) AS administrators,
          (SELECT count(*) FROM public.users WHERE running_challenge IS NOT NULL) AS assigned_users,
          (SELECT count(*) FROM public.challenge_templates) AS exercises,
          (SELECT count(*) FROM public.challenge_templates WHERE is_active AND NOT marked_for_deletion AND ready_to_launch) AS published,
          (SELECT count(*) FROM public.challenge_templates WHERE is_active AND NOT marked_for_deletion AND NOT ready_to_launch) AS unavailable_exercises,
          (SELECT count(*) FROM public.challenge_templates WHERE marked_for_deletion) AS retired,
          (SELECT count(*) FROM public.machines) AS machines,
          (SELECT count(*) FROM public.networks) AS networks,
          (SELECT COALESCE(sum(t.ram_gb),0) FROM public.machines m JOIN public.machine_templates t ON t.id=m.machine_template_id) AS allocated_ram_gb,
          (SELECT COALESCE(sum(t.cores),0) FROM public.machines m JOIN public.machine_templates t ON t.id=m.machine_template_id) AS allocated_cores,
          (SELECT count(*) FROM public.disk_files WHERE is_available) AS available_images''')
        counts=dict(cursor.fetchone())
        cursor.execute('SELECT lifecycle_state::text AS state,count(*) AS count FROM public.challenges GROUP BY lifecycle_state')
        states={row['state']:row['count'] for row in cursor.fetchall()}
        cursor.execute('''SELECT count(*) AS accounts,count(*) FILTER(WHERE opted_out) AS opted_out,
                          count(*) FILTER(WHERE NOT opted_out) AS eligible FROM public.training_preferences''')
        training=dict(cursor.fetchone())
        cursor.execute('''SELECT c.id,c.name,c.is_active,c.marked_for_deletion,c.ready_to_launch,
                          u.username AS owner,COALESCE(p.enabled,FALSE) AS pool_override,COALESCE(p.size,0) AS pool_size,COALESCE(p.revision,0) AS pool_revision,
                          (SELECT COALESCE(sum(ram_gb),0) FROM public.machine_templates m WHERE m.challenge_template_id=c.id) AS ram_per_instance,
                          (SELECT count(*) FROM public.challenges i WHERE i.challenge_template_id=c.id AND i.lifecycle_state='READY' AND i.pre_assigned_user_id IS NULL) AS ready_pool,
                          (SELECT count(*) FROM public.machine_templates m WHERE m.challenge_template_id=c.id) AS machines,
                          (SELECT count(*) FROM public.challenges i WHERE i.challenge_template_id=c.id) AS instances
                          FROM public.challenge_templates c LEFT JOIN public.users u ON u.id=c.creator_id LEFT JOIN public.pool_overrides p ON p.challenge_template_id=c.id
                          ORDER BY c.id LIMIT 101''')
        exercises=[dict(row) for row in cursor.fetchall()]
    return {'counts':counts,'lifecycle':states,'host':host_capacity(),
            'training':{**training,'capture_status':'disabled','export_status':'disabled',
                        'reason':'Dedicated capture/export and revocation acceptance are unfinished'},
            'exercises':exercises[:100],'exercises_truncated':len(exercises)>100}
