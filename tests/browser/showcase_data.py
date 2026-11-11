"""Deterministic synthetic records shared by UI regressions and documentation captures."""
from copy import deepcopy

CHALLENGES = [
    {'id': 4, 'name': 'The Glass Directory', 'category': 'web', 'difficulty': 'medium',
     'description': 'Trace an identity through the portal, directory and archive. Follow the evidence to uncover excessive permissions.',
     'is_active': True, 'marked_for_deletion': False, 'active_deployments': 3, 'total_deployments': 26, 'solve_count': 18},
    {'id': 6, 'name': 'Tickets, Hosts & Broken Policy', 'category': 'misc', 'difficulty': 'hard',
     'description': 'Investigate service tickets, host access and policy boundaries in an isolated identity environment.',
     'is_active': True, 'marked_for_deletion': False, 'active_deployments': 2, 'total_deployments': 14, 'solve_count': 7},
    {'id': 8, 'name': 'Packet Trail', 'category': 'forensics', 'difficulty': 'easy',
     'description': 'Reconstruct the sequence of events from the network evidence. Your first investigation starts here.',
     'is_active': False, 'marked_for_deletion': True, 'active_deployments': 0, 'total_deployments': 32, 'solve_count': 24},
]


def responses():
    challenges = deepcopy(CHALLENGES)
    def data(value):
        return {'success': True, 'data': value}
    activity = [{'id': 1, 'title': 'Directory evidence found', 'description': 'The Glass Directory · 150 points', 'created_at': '2026-11-01T10:00:00Z', 'time_ago': 'Today'}]
    result = {
        'admin/maintenance':data({'release':{'version':'0.4.0-rc.3','commit':'651263f7096722aef978fe9b29de86f29a06e8f4'},'maintenance':False,'pending_requests':1,
          'acceptance':{'status':'not configured'},'transactions':[{'id':'20261101-rehearsal','version':'0.4.0-rc.5','phase':'RECOVERY_REQUIRED','checkpoint_recorded':True,'committed':False}]}),
        'admin/overview':data({'counts':{'users':42,'administrators':2,'assigned_users':5,'published':2,'machines':12,'networks':8,'allocated_ram_gb':26,'allocated_cores':20,'available_images':6},
          'host':{'status':'ready','cores':16,'cpu_percent':21.5,'memory_used_bytes':40*1024**3,'memory_total_bytes':64*1024**3,'root_used_bytes':128*1024**3,'root_total_bytes':400*1024**3},
          'lifecycle':{'READY':2,'ACTIVE':5,'EXPIRED':1},'training':{'accounts':42,'opted_out':7,'eligible':35,'capture_status':'disabled','export_status':'disabled','reason':'Capture/export and revocation acceptance are unfinished'},
          'exercises':[{'id':4,'name':'The Glass Directory','owner':'investigator','is_active':True,'ready_to_launch':True,'machines':2,'instances':3,'ready_pool':2,'ram_per_instance':4,'pool_revision':0,'pool_size':0,'pool_override':False}]}),
        'admin/audit':data({'events':[{'id':1,'recorded_at':'2026-11-01T10:00:00Z','action':'updated','actor':'investigator','resource_id':4,'revision_id':1}],'page':1,'has_more':False}),
        'admin/jobs/user/2':data({'current':{'state':'SUCCEEDED'},'operations':[{'id':'a'*32,'scope':'user','resource':2,'action':'launch_challenge','state':'SUCCEEDED','actor':1,'started':'2026-11-01T10:00:00Z','finished':'2026-11-01T10:00:20Z','stage':'completed','events':[{'stage':'completed','at':'2026-11-01T10:00:20Z'}]},
          {'id':'b'*32,'scope':'user','resource':2,'instance_id':101,'managed_queue':True,'action':'admin_rebuild','state':'NEEDS_REVIEW','actor':1,'started':'2026-11-01T09:00:00Z','stage':'removing_instance','events':[]}]}),
        'admin/challenges/4/revisions':data({'revisions':[{'id':1,'recorded_at':'2026-11-01T10:00:00Z','actor':'investigator','fingerprint':'a'*64,'is_active':True,'machines':2,'networks':2}],'has_more':False}),
        'admin/challenges/4/revisions/1':data({'definition':{'name':'The Glass Directory','category':'web','difficulty':'medium','description':'A recorded exercise configuration.',
          'vms':[{'name':'portal','ova_name':'identity-portal.ova','artifact_id':1,'cores':1,'ram_gb':2},{'name':'directory','ova_name':'identity-directory.ova','artifact_id':2,'cores':2,'ram_gb':2}],
          'subnets':[{'name':'entry','accessible':True,'attached_vms':['portal','directory']},{'name':'internal','accessible':False,'attached_vms':['directory']}],
          'flags':[{'flag':'synthetic-private-value'}],'hints':[]}}),
        'profile/training-preference': data({'opted_out':False,'revision':1}),
        'admin/monitoring/activity': data({'status':'ready','checked_at':'2026-11-01T10:05:00Z',
            'counts':{'commands':1,'processes':1},'coverage':'unverified','has_more':False,'events':[
                {'machine_id':100000101,'timestamp':'2026-11-01T10:04:30Z','kind':'command','description':'Bash command received','command':'id','truncated':False},
                {'machine_id':100000101,'timestamp':'2026-11-01T10:04:20Z','kind':'process','description':'Process created','command':'/usr/bin/hostname','truncated':False}]}),
        'badges': data({'stats':{'earned':4,'total':9},'badges':[{'id':i+1,'name':name,'description':description,'earned':i<4,'icon':['🕸️','🔐','👁️','🕵️','💣','🧩','💉','⚡','👑'][i]} for i,(name,description) in enumerate([('Web Warrior','Solve five web challenges.'),('Crypto Expert','Solve five cryptography challenges.'),('Reverse Engineer','Solve five reverse engineering challenges.'),('Forensic Analyst','Solve five forensic challenges.'),('Binary Buster','Solve five binary exploitation challenges.'),('Puzzle Master','Solve five miscellaneous challenges.'),('First Blood','Be the first to complete a challenge.'),('Speed Runner','Complete a challenge in five minutes.'),('Master Hacker','Earn the other achievements.')])]}),
        'announcements': data({'announcements':[{'id':1,'title':'Lecture exercises','content':'Exercises are available in the challenge library. Keep notes about your investigation and submit the flags you find.','short_description':'The identity lab is available.','category':'events','importance':'important','created_at':'2026-11-01T09:00:00Z'}],'total':1}),
        'admin/announcements':data({'announcements':[{'id':1,'title':'Lecture exercises','content':'Exercises are available in the challenge library.','short_description':'The identity lab is available.','category':'events','importance':'important','created_at':'2026-11-01T09:00:00Z'}],'total':1}),
        'admin/jobs':data({'jobs':[{'scope':'user','resource':2,'action':'launch_challenge','state':'SUCCEEDED','started':'2026-11-01T10:00:00Z','id':'a'*32},{'scope':'instance','resource':102,'action':'admin_remove','state':'NEEDS_REVIEW','started':'2026-11-01T10:01:00Z','id':'b'*32}],'page':1,'has_more':False,'truncated':False}),
        'admin/users':data({'users':[{'id':1,'username':'investigator','email':'investigator@example.invalid','is_admin':True,'sessions':1,'last_login':'2026-11-01T10:00:00Z'},{'id':2,'username':'student01','email':'student01@example.invalid','is_admin':False,'sessions':2,'vpn_ip':'10.64.0.3','running_challenge':101,'last_login':'2026-11-01T09:30:00Z'}],'page':1,'has_more':False}),
        'admin/instances':data({'instances':[{'id':101,'name':'The Glass Directory','state':'ACTIVE','user_id':2,'username':'student01','expires_at':'2026-11-01T11:00:00Z','machines':2},{'id':102,'name':'Tickets, Hosts & Broken Policy','state':'EXPIRED','pre_assigned_user_id':2,'expires_at':'2026-11-01T09:30:00Z'}],'page':1,'has_more':False}),
        'admin/instances/101':data({'monitoring': {'status':'ready','checked_at':'2026-11-01T10:05:00Z','machines':[
            {'machine_id':100000101,'vm_status':'running','agent_status':'active','last_keepalive':'2026-11-01T10:04:45Z'},
            {'machine_id':100000102,'vm_status':'running','agent_status':'disconnected','last_keepalive':'2026-11-01T09:45:00Z'}
        ],'sensors':[{'id':'host.service.suricata-vpn.service','label':'Suricata VPN','state':'ok'}], 'command_delivery':'unverified','network_coverage':'unverified'}, 'id':101,'name':'The Glass Directory','state':'ACTIVE','username':'student01','machines':[{'id':100000101,'name':'portal','status':'running'},{'id':100000102,'name':'directory','status':'running'}],'networks':[{'id':10,'name':'entry','subnet':'10.128.42.0/28','accessible':True,'is_dmz':False},{'id':11,'name':'internal','subnet':'10.128.42.16/28','accessible':False,'is_dmz':False}],'connections':[{'machine_id':100000101,'network_id':10,'address':'10.128.42.2','mac':'02:00:00:00:00:01'},{'machine_id':100000102,'network_id':10,'address':'10.128.42.3','mac':'02:00:00:00:00:02'},{'machine_id':100000102,'network_id':11,'address':'10.128.42.18','mac':'02:00:00:00:00:03'}],'operation':{'scope':'user','resource':2,'id':'a'*32,'action':'launch_challenge','state':'SUCCEEDED','started':'2026-11-01T10:00:00Z'}}),
        'admin/challenges': data({'challenges': challenges, 'stats': {'total_challenges': 3, 'active_challenges': 2, 'active_deployments': 5, 'total_deployments': 72, 'avg_completion_minutes': 48}}),
        'explore': data({'challenges': challenges[:2], 'pagination': {'total_pages': 1, 'total_items': 2}}),
        'dashboard': data({'news':[{'id':1,'title':'Lecture exercises','short_description':'The identity lab is available. Check the challenge library before the next session.','importance':'important','category':'events','author':'heiST tutors','created_at':'2026-11-01T09:00:00Z'}],'user': {'username': 'investigator', 'points': 1250, 'rank': 4}, 'progress': {'solved': 5, 'success_rate': 83}, 'challenges': challenges[:2], 'activity': activity, 'timeline': {'labels': ['Mon', 'Tue', 'Wed', 'Thu', 'Fri'], 'points': [50, 150, 75, 200, 150]}}),
        'challenge': {'success': True, 'challenge': {**challenges[0], 'creator_username': 'heiST tutors', 'challenge_status': {'challenge_status': 'running'}, 'remaining_seconds': 3600, 'remaining_extensions': 2, 'challenge_points': 450, 'flags_total': 3, 'flags_submitted': 1, 'entrypoints': ['https://portal.identity.lab', '10.10.42.0/24'], 'hint': 'Begin with the portal. Document what each account can access.', 'leaderboard': [{'username': 'investigator', 'rank': 1, 'total_seconds': 2700}]}},
        'profiles/investigator': data({'profile':{'username':'investigator','full_name':'Alex Investigator','bio':'Learning how identity, permissions and evidence fit together.','total_points':1250,'solved_count':5},'stats':{'rank':4},'badges':[{'id':1,'name':'Web Warrior','earned':True}],'activity':activity}),
        'profile': data({'basic': {'username': 'investigator', 'full_name': 'Alex Investigator', 'bio': 'Learning how identity, permissions and evidence fit together.'}, 'stats': {'points': 1250, 'solved': 5}, 'activity': activity}),
        'activity': data({'activities': activity}),
        'admin/artifacts': data({'ovas': [{'filename': 'identity-portal.ova', 'size': 1073741824, 'guest_os': 'linux'}], 'uploads': [], 'limits': {'MAX_FILE_SIZE': 10*1024**3, 'CHUNK_SIZE': 5}}),
        'admin/challenges/options': {'success': True, 'ovas': [{'filename': 'identity-portal.ova'},{'filename':'identity-directory.ova'}]},
        'admin/operations': data({'monitoring': {'status': 'failed', 'checked_at': '2026-11-01T10:05:00Z', 'checks': [
            {'id': 'host.service.suricata-dmz', 'label': 'Suricata DMZ', 'state': 'failed', 'summary': 'Required sensor is stopped; inspect the host service journal.'},
            {'id': 'host.service.vector-vpn', 'label': 'VPN log shipper', 'state': 'ok', 'summary': 'Active; downstream delivery requires a correlated canary.'},
            {'id': 'monitoring.end_to_end', 'label': 'End-to-end validation', 'state': 'unknown', 'summary': 'Correlated event delivery has not been verified.'}
        ]}, 'database': 'ready', 'maintenance': False, 'source_version': '0.3.0', 'services': [{'unit': 'backend.service', 'state': 'active', 'detail': 'running'}, {'unit': 'cleanup.service', 'state': 'active', 'detail': 'startup reconciliation complete'}, {'unit': 'pool_manager.service', 'state': 'active', 'detail': 'running'}], 'archive': {'status': 'success', 'last_success_at': '2026-11-01T10:00:00Z', 'counters': {'verified': 24, 'copied': 3}}, 'lifecycle': {'ACTIVE': 5, 'READY': 2}, 'release': {'version': '0.3.0'}, 'storage': {'used_percent': 32, 'free_bytes': 128*1024**3}, 'checked_at': '2026-11-01T10:05:00Z'}),
    }

    detail=result['admin/instances/101']['data']
    detail.update(challenge_template_id=4,subnet='10.128.42.0/28',activated_at='2026-11-01T09:05:00Z',expires_at='2026-11-01T11:00:00Z')
    for vm in detail['machines']:vm.update(cores=1,ram_gb=2,ad_role='none')
    return result
