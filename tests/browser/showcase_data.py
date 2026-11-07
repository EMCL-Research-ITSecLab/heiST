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
    return {
        'admin/challenges': data({'challenges': challenges, 'stats': {'total_challenges': 3, 'active_challenges': 2, 'active_deployments': 5, 'total_deployments': 72, 'avg_completion_minutes': 48}}),
        'explore': data({'challenges': challenges[:2], 'pagination': {'total_pages': 1, 'total_items': 2}}),
        'dashboard': data({'user': {'username': 'investigator', 'points': 1250, 'rank': 4}, 'progress': {'solved': 5, 'success_rate': 83}, 'challenges': challenges[:2], 'activity': activity, 'timeline': {'labels': ['Mon', 'Tue', 'Wed', 'Thu', 'Fri'], 'points': [50, 150, 75, 200, 150]}}),
        'challenge': {'success': True, 'challenge': {**challenges[0], 'creator_username': 'heiST tutors', 'challenge_status': {'challenge_status': 'running'}, 'remaining_seconds': 3600, 'remaining_extensions': 2, 'challenge_points': 450, 'flags_total': 3, 'flags_submitted': 1, 'entrypoints': ['https://portal.identity.lab', '10.10.42.0/24'], 'hint': 'Begin with the portal. Document what each account can access.', 'leaderboard': [{'username': 'investigator', 'rank': 1, 'total_seconds': 2700}]}},
        'profile': data({'basic': {'username': 'investigator', 'full_name': 'Alex Investigator', 'bio': 'Learning how identity, permissions and evidence fit together.'}, 'stats': {'points': 1250, 'solved': 5}, 'activity': activity}),
        'activity': data({'activities': activity}),
        'admin/artifacts': data({'ovas': [{'filename': 'identity-portal.ova', 'size': 1073741824, 'guest_os': 'linux'}], 'uploads': [], 'limits': {'MAX_FILE_SIZE': 10*1024**3, 'CHUNK_SIZE': 5}}),
        'admin/challenges/options': {'success': True, 'ovas': [{'filename': 'identity-portal.ova'}]},
        'admin/operations': data({'database': 'ready', 'maintenance': False, 'source_version': '0.3.0', 'services': [{'unit': 'backend.service', 'state': 'active', 'detail': 'running'}, {'unit': 'cleanup.service', 'state': 'active', 'detail': 'startup reconciliation complete'}, {'unit': 'pool_manager.service', 'state': 'active', 'detail': 'running'}], 'archive': {'status': 'success', 'last_success_at': '2026-11-01T10:00:00Z', 'counters': {'verified': 24, 'copied': 3}}, 'lifecycle': {'ACTIVE': 5, 'READY': 2}, 'release': {'version': '0.3.0'}, 'storage': {'used_percent': 32, 'free_bytes': 128*1024**3}, 'checked_at': '2026-11-01T10:05:00Z'}),
    }
